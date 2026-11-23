"""W10-P4-1: verifier đứng trước API/PWA. Lịch trình có giờ/giá/di chuyển sai đi qua graph UC-02 thật (planner giả)
→ API chỉ trả bản đã sửa + nhãn "chưa xác minh", trace có guardrail của node verify. Câu thuyết minh UC-03 được sửa
trước khi lưu. Giờ, giá, quãng đường là dữ liệu TEST hư cấu của fixture `db`, không phải dữ liệu Huế thật."""

import pytest
from fastapi.testclient import TestClient

from agent.db import repo
from agent.schemas import Itinerary, Slot, TripProfile
from agent.src.api import server
from agent.src.graph import app
from agent.src.nodes import narrate
from agent.src.nodes.verify import SAFE_FALLBACK, present_itinerary

PROFILE = {"start_date": "2026-11-27", "end_date": "2026-11-27", "adults": 2, "interests": ["history", "food"]}


@pytest.fixture
def facts(db):
    repo.query("UPDATE pois SET ticket_price_vnd = 200000, opening_hours = 'Mo-Su 08:00-17:00' WHERE poi_id = 'hue-dai-noi'")
    repo.query("""INSERT INTO travel_matrix VALUES ('hue-dai-noi', 'hue-cho-dong-ba', 'drive', 8, 2500, 'osrm', '2026-10-24'),
                                                  ('hue-dai-noi', 'hue-cho-dong-ba', 'walk', 30, 2300, 'osrm', '2026-10-24')""")
    return db


def wrong_itinerary(state, *args):
    """Planner giả: Đại Nội 18h (đã đóng cửa), giá 300.000đ cho 2 người (đúng: 2 × 200.000đ), đi xe 15 phút (đúng: 8)."""
    slots = [
        Slot(slot_id=f"{state['itinerary_id']}:d1-s1", day_index=1, slot_date="2026-11-27", start_time="18:00",
             end_time="19:00", poi_id="hue-dai-noi", activity="Tham quan Đại Nội", cost_vnd=300000, cost_source="tool",
             hours_status="verified"),
        Slot(slot_id=f"{state['itinerary_id']}:d1-s2", day_index=1, slot_date="2026-11-27", start_time="19:30",
             end_time="20:30", poi_id="hue-cho-dong-ba", activity="Ăn tối ở Chợ Đông Ba", travel_minutes_from_prev=15,
             cost_source="unverified", hours_status="unverified"),
    ]  # fmt: skip
    itinerary = Itinerary(itinerary_id=state["itinerary_id"], trip_id=state["trip_id"], profile_id=state["profile_id"],
                          planner_rounds=state["round"] + 1, run_id=state["run_id"], slots=slots)  # fmt: skip
    return {"itinerary": itinerary, "round": state["round"] + 1}


@pytest.fixture
def client(facts, monkeypatch):
    monkeypatch.setattr(app, "plan", wrong_itinerary)
    monkeypatch.setattr(app, "validate", lambda *a: [])  # để lịch sai đi tới finalize, chỉ còn verifier chặn
    monkeypatch.setattr(app, "check_fabrication", lambda *a: [])
    monkeypatch.setattr(app, "make_client", lambda: object())
    monkeypatch.setattr(app, "default_tools", list)
    c = TestClient(server.app)
    assert c.post("/api/session", json={"user_id": "u-ha"}).status_code == 200
    return c


def test_api_only_returns_corrected_itinerary(client):
    trip_id = client.post("/api/trips", json=PROFILE).json()["trip_id"]
    plan = client.post(f"/api/trips/{trip_id}/plan").json()
    assert plan["interrupt"]["kind"] == "itinerary_approval"  # verify chạy xong trước khi dừng chờ người dùng duyệt

    first, second = client.get(f"/api/trips/{trip_id}/itinerary").json()["slots"]
    assert first["cost_vnd"] == 400000 and first["hours_status"] == "unverified"
    assert "Giờ chưa xác minh, giờ mở cửa ngày 2026-11-27: 08:00–17:00" in first["note"]
    assert "Giá đã sửa theo nguồn: 200.000đ × 2 người" in first["note"]
    assert second["travel_minutes_from_prev"] == 8
    total = repo.query("SELECT total_cost_vnd FROM itineraries WHERE itinerary_id = ?", (plan["itinerary_id"],))
    assert total[0]["total_cost_vnd"] == 400000

    claims = repo.query("SELECT claim_text, status, corrected_text FROM claims WHERE run_id = ?", (plan["run_id"],))
    assert {c["claim_text"] for c in claims if c["status"] == "contradicted"} == {
        "18:00–19:00", "cost_vnd=300000", "travel_minutes_from_prev=15"}  # fmt: skip
    trace = client.get(f"/api/runs/{plan['run_id']}/trace").json()
    fix = next(e for e in trace if e["node"] == "verify" and e["name"] == "verify_fix")
    assert fix["kind"] == "guardrail" and fix["result"]["claims"]["contradicted"] == 3
    nodes = [e["node"] for e in trace if e["kind"] == "node_start"]
    assert nodes.index("finalize") < nodes.index("verify") < nodes.index("approve")


def test_rerun_does_not_duplicate_claims(facts):
    trip_id = repo.create_trip("u-ha")
    profile_id = repo.save_profile(trip_id, TripProfile.model_validate(PROFILE))
    run_id = repo.create_run("UC-02", trip_id, "u-ha")
    state = {"itinerary_id": repo.new_id("it"), "trip_id": trip_id, "profile_id": profile_id, "round": 0, "run_id": run_id}
    itinerary = wrong_itinerary(state)["itinerary"]
    repo.save_itinerary(itinerary, [])
    count = lambda: repo.query("SELECT COUNT(*) AS n FROM claims WHERE target_id LIKE ?",
                               (f"{itinerary.itinerary_id}:%",))[0]["n"]  # fmt: skip
    present_itinerary(itinerary, run_id)
    first = count()
    present_itinerary(itinerary, run_id)  # backend chết rồi chạy lại node verify
    assert first == count() == 4  # slot 1: giờ + giá; slot 2: giờ (chưa có nguồn) + di chuyển


def narration_state(text):
    trip_id = repo.create_trip("u-ha")
    point = {"text": text, "doc_id": "hue-dai-noi-vi-01", "section": "Lịch sử", "source_url": "https://example.org",
             "quote": "q", "is_fictional": False}  # fmt: skip
    return {"run_id": repo.create_run("UC-03", trip_id, "u-ha"), "trip_id": trip_id, "user_id": "u-ha", "lang": "vi",
            "question": "Đại Nội có gì?", "points": [point], "checked": []}  # fmt: skip


def test_narration_corrected_before_saving(facts):
    out = narrate.finalize(narration_state("Đại Nội là hoàng cung nhà Nguyễn, vé người lớn 150.000đ."))
    assert "200.000đ" in out["text"] and "150.000đ" not in out["text"] and out["citations"]
    saved = repo.query("SELECT content FROM messages WHERE message_id = ?", (out["message_id"],))[0]["content"]
    assert saved == out["text"]


def test_narration_blocked_drops_citations(facts, monkeypatch):
    monkeypatch.setattr("agent.src.nodes.verify.corrected_text", lambda c, e, lang="vi": "180.000đ")  # bug ở bước sửa
    out = narrate.finalize(narration_state("Vé Đại Nội 150.000đ."))
    assert out["text"] == SAFE_FALLBACK["vi"] and out["citations"] == []
