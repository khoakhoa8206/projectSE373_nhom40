"""Sửa lịch trình SAU khi đã duyệt: lập lại theo ghi chú, duyệt lại; từ chối bản mới thì giữ bản đã duyệt cũ."""

import json

from agent.db import repo
from agent.schemas import Itinerary
from agent.src.graph import app
from tests.test_uc02 import TOOLS, FakeLLM, graph_source_facts, new_trip  # noqa: F401 (fixture autouse)


def approved_trip():
    trip_id = new_trip()
    first = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS, approval=True)
    done = app.resume(trip_id, first["interrupt"]["approval_id"], "approved", client=FakeLLM(), tools=TOOLS)
    app.resume(trip_id, done["interrupt"]["approval_id"], "rejected", client=FakeLLM(), tools=TOOLS)  # không lưu bộ nhớ
    it = repo.itinerary_for_trip(trip_id)
    return trip_id, Itinerary.model_validate(it | {"has_unpriced_item": bool(it["has_unpriced_item"])})


def spy_llm(seen):
    llm = FakeLLM()
    create = llm.chat.completions.create
    llm.chat.completions.create = lambda **kw: (seen.append(kw["messages"][1]["content"]), create(**kw))[1]
    return llm


def test_revise_after_approval_replans_with_note_and_previous_itinerary(db):
    trip_id, approved = approved_trip()
    seen = []
    res = app.run_uc02(trip_id, "u-ha", client=spy_llm(seen), tools=TOOLS, approval=True,
                       revise=(approved, "Bỏ chợ, thêm nghỉ trưa"))  # fmt: skip
    sent = json.loads(seen[0])
    assert sent["user_feedback"] == "Bỏ chợ, thêm nghỉ trưa" and sent["previous_itinerary"]
    assert res["interrupt"]["kind"] == "itinerary_approval" and res["itinerary_id"] != approved.itinerary_id

    app.resume(trip_id, res["interrupt"]["approval_id"], "approved", client=FakeLLM(), tools=TOOLS)
    assert repo.itinerary_for_trip(trip_id)["itinerary_id"] == res["itinerary_id"]
    assert repo.query("SELECT status FROM trips WHERE trip_id = ?", (trip_id,)) == [{"status": "approved"}]


def test_rejecting_revision_keeps_previously_approved_itinerary(db):
    trip_id, approved = approved_trip()
    res = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS, approval=True, revise=(approved, "Thêm chùa"))
    app.resume(trip_id, res["interrupt"]["approval_id"], "rejected", client=FakeLLM(), tools=TOOLS)

    current = repo.itinerary_for_trip(trip_id)
    assert current["status"] == "approved" and current["itinerary_id"] not in (approved.itinerary_id, res["itinerary_id"])
    assert [(s["poi_id"], s["start_time"]) for s in current["slots"]] == [(s.poi_id, s.start_time) for s in approved.slots]
    assert repo.query("SELECT status FROM trips WHERE trip_id = ?", (trip_id,)) == [{"status": "approved"}]


def test_revise_api_only_for_approved_itinerary(db, monkeypatch):
    from fastapi.testclient import TestClient

    from agent.src.api import server

    started = []
    monkeypatch.setattr(server, "start", lambda fn, *args, **kw: started.append(args))  # không chạy graph thật ở test API
    client = TestClient(server.app)
    client.post("/api/session", json={"user_id": "u-ha"})
    assert client.post(f"/api/trips/{new_trip()}/revise", json={"note": "Thêm chùa"}).status_code == 409  # chưa có lịch

    trip_id, _ = approved_trip()
    r = client.post(f"/api/trips/{trip_id}/revise", json={"note": " Thêm chùa "})
    assert r.status_code == 200 and started[0][-1] == "Thêm chùa"
    assert repo.query("SELECT status FROM trips WHERE trip_id = ?", (trip_id,)) == [{"status": "planning"}]


def test_recover_runs_after_backend_restart(db, monkeypatch):
    """Backend tắt giữa chừng: UC-01/02 chạy tiếp từ checkpoint, lượt không có checkpoint thành failed (không kẹt)."""
    from agent.src.api import server

    trip_id = new_trip()
    plan_run = repo.create_run("UC-02", trip_id, "u-ha")
    journal_run = repo.create_run("UC-09", trip_id, "u-ha")
    continued = []
    monkeypatch.setattr(server, "start", lambda fn, *args: fn(*args))  # chạy đồng bộ trong test
    monkeypatch.setattr(server.graph, "continue_run", lambda t: continued.append(t) or {"status": "validated"})
    server.recover_runs()
    assert continued == [trip_id]
    status = {r["run_id"]: r["status"] for r in repo.query("SELECT run_id, status FROM runs")}
    assert status[plan_run] == "running" and status[journal_run] == "failed"

    monkeypatch.setattr(server.graph, "continue_run", lambda t: None)  # checkpoint không còn gì để chạy tiếp
    server.recover_runs()
    assert repo.query("SELECT status FROM runs WHERE run_id = ?", (plan_run,)) == [{"status": "failed"}]
