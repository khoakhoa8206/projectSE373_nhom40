"""Kiểm lớp /api/ui/* trên graph thật của nhóm (planner giả): lập lịch, duyệt, kiểm chứng, tách dữ liệu theo người dùng."""

import sys
import time

import pytest

from agent.db import repo

FORM = {"start_date": "2026-11-25", "end_date": "2026-11-26", "adults": 2, "children": [{"age": 6}], "budget_total_vnd": 8000000,
        "interests": ["history"], "pace": "relaxed", "language": "vi", "mobility_notes": None}  # fmt: skip


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ui")
    patch = pytest.MonkeyPatch()
    patch.setenv("DB_PATH", str(tmp / "t.db"))
    patch.setenv("TRACE_DIR", str(tmp / "traces"))
    patch.delenv("LLM_API_KEY", raising=False)
    patch.setenv("WEATHER_BASE_URL", "http://127.0.0.1:9")  # không có mock: tool phải báo không có dự báo, không giả định
    from agent.db.init import init_db
    from scripts import load_destination

    init_db()
    patch.setattr(sys, "argv", ["load_destination.py", "hue", "--complete"])
    load_destination.main()
    from fastapi.testclient import TestClient

    from fullstack.api import app

    yield TestClient(app)
    patch.undo()


def login(client, user):
    assert client.post("/api/session", json={"user_id": user}).status_code == 200


def wait(run_id):
    for _ in range(300):
        status = repo.query("SELECT status FROM runs WHERE run_id = ?", (run_id,))[0]["status"]
        if status != "running":
            return status
        time.sleep(0.2)
    raise AssertionError("run chưa xong")


def test_form_goes_through_real_graph_and_is_private(client):
    login(client, "u-ha")
    assert client.post("/api/ui/start-form", json=FORM | {"start_date": None}).status_code == 400
    assert client.post("/api/ui/start-form", json=FORM | {"adults": 6}).status_code == 400  # 6 người lớn + 1 trẻ
    started = client.post("/api/ui/start-form", json=FORM).json()
    trip, run = started["trip_id"], started["run_id"]
    assert wait(run) == "interrupted"

    detail = client.get(f"/api/ui/trips/{trip}").json()
    assert detail["pending"]["kind"] == "itinerary_approval" and detail["itinerary"]["slots"] and detail["claims"]
    assert all(c["status"] != "contradicted" or c["corrected_text"] for c in detail["claims"])
    assert len(client.get(f"/api/ui/trips/{trip}").json()["claims"]) == len(detail["claims"])  # không kiểm lại lần hai

    resumed = client.post(f"/api/trips/{trip}/resume?background=true",
                          json={"approval_id": detail["pending"]["approval_id"], "decision": "approved", "response": None}).json()  # fmt: skip
    assert wait(resumed["run_id"]) == "interrupted"
    assert client.get(f"/api/ui/trips/{trip}").json()["pending"]["kind"] == "memory_save"
    assert any(t["trip_id"] == trip and t["waiting"] for t in client.get("/api/ui/trips").json())

    login(client, "u-emma")
    assert client.get(f"/api/ui/trips/{trip}").status_code == 404
    assert client.delete(f"/api/ui/trips/{trip}").status_code == 404
    login(client, "u-ha")
    assert client.delete(f"/api/ui/trips/{trip}").status_code == 200
    assert not repo.query("SELECT 1 FROM trips WHERE trip_id = ?", (trip,))


def test_text_entry_never_guesses(client):
    login(client, "u-minh")
    missing = client.post("/api/ui/start-text", json={"text": "Cuối tháng 11 đi Huế"})
    assert missing.status_code == 422 and "khởi hành" in missing.json()["detail"]
    assert "Huế" in client.post("/api/ui/start-text", json={"text": "đi Bangkok 3 ngày, 2 người lớn, 5 triệu"}).json()["detail"]


def test_verify_corrects_wrong_price(client):
    login(client, "u-minh")
    out = client.post("/api/ui/verify", json={"text": "Đại Nội Huế giá vé 300.000đ."}).json()
    assert "200.000" in out["text"] and "300.000" not in out["text"]

    lines = client.post("/api/ui/verify", json={"text": "Lăng Tự Đức giá vé 150.000đ. Lăng Khải Định giá vé 150.000đ. Huế rất đẹp."}).json()["lines"]
    assert [len(x["claims"]) for x in lines] == [1, 1, 0]  # cùng con số vẫn nằm đúng câu của nó


def test_by_line_keeps_claims_when_text_was_replaced():
    from fullstack.api import by_line

    claim = {"claim_text": "9h", "corrected_text": "08:30"}
    assert by_line("Thông tin đã bị chặn.", [claim])[0]["claims"] == [claim]


def test_route_uses_osrm_geometry_and_falls_back_when_offline(client, monkeypatch):
    import httpx

    from fullstack import api as ui

    login(client, "u-ha")
    ui._osrm_route.cache_clear()
    sent = []

    def fake_get(url, **kw):
        sent.append(url)
        geometry = {"coordinates": [[107.5446, 16.4535], [107.56, 16.46], [107.5778, 16.4695]]}
        return httpx.Response(200, json={"routes": [{"geometry": geometry, "distance": 4321.4, "duration": 600}]},
                              request=httpx.Request("GET", url))  # fmt: skip

    monkeypatch.setattr(ui.httpx, "get", fake_get)
    r = client.get("/api/ui/route", params={"pois": "hue-chua-thien-mu,hue-dai-noi"}).json()
    assert r["source"] == "osrm" and r["coordinates"][1] == [16.46, 107.56] and r["duration_min"] == 10
    assert sent[0].startswith(ui.OSRM_URLS[0]) and "107.54461,16.45355;" in sent[0]  # chỉ toạ độ POI, lon trước lat

    def first_down(url, **kw):  # máy chủ chính chết → dùng máy chủ dự phòng
        if url.startswith(ui.OSRM_URLS[0]):
            raise httpx.ConnectTimeout("timed out")
        return fake_get(url, **kw)

    monkeypatch.setattr(ui.httpx, "get", first_down)
    r = client.get("/api/ui/route", params={"pois": "hue-dai-noi,hue-chua-thien-mu"}).json()
    assert r["source"] == "osrm" and sent[-1].startswith(ui.OSRM_URLS[1])

    def offline(url, **kw):
        raise httpx.ConnectError("mất mạng")

    monkeypatch.setattr(ui.httpx, "get", offline)
    assert client.get("/api/ui/route", params={"pois": "hue-dai-noi,hue-lang-tu-duc"}).json() == {"coordinates": None, "source": None}
    assert client.get("/api/ui/route", params={"pois": "hue-dai-noi"}).status_code == 422
    assert client.get("/api/ui/route", params={"pois": "hue-dai-noi,khong-co"}).status_code == 404
