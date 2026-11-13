"""Ghép UC-01 (intake của P2) vào graph P1: hỏi lại qua interrupt → lập lịch UC-02 → duyệt (LLM, tool giả)."""

import json

from fastapi.testclient import TestClient

from agent.db import repo
from agent.schemas import TripProfile
from agent.src.api import server, stream
from agent.src.graph import app
from tests.test_stream import read_sse
from tests.test_uc02 import PROFILE, TOOLS, FakeLLM, graph_source_facts  # noqa: F401 (fixture autouse)

QUESTIONS = [{"field": "start_date", "text": "Bạn khởi hành ngày nào?"}]


def fake_intake(monkeypatch, routes):
    """Thay LLM của intake: lần lượt trả route trong `routes`; route=plan thì lưu hồ sơ như node thật."""
    seen = []

    def intake(state, client, usage):
        seen.append([m["content"] for m in repo.query(
            "SELECT content FROM messages WHERE trip_id = ? ORDER BY created_at, rowid", (state["trip_id"],))])
        route = routes.pop(0)
        result = {"route": route, "questions": QUESTIONS if route == "ask_user" else [], "conflicts": [],
                  "message": "Hiện chỉ hỗ trợ Huế" if route == "unsupported" else ""}  # fmt: skip
        if route == "plan":
            repo.save_profile(state["trip_id"], TripProfile(**PROFILE), state["run_id"])
        return result

    monkeypatch.setattr(app.uc01, "intake", intake)
    return seen


def test_chat_asks_then_plans_then_waits_for_approval(db, monkeypatch):
    seen = fake_intake(monkeypatch, ["ask_user", "plan"])
    trip_id = repo.create_trip("u-ha")
    repo.add_message(trip_id, "u-ha", "user", "Nhà mình đi Huế 1 ngày")
    res = app.run_uc01(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS)
    assert res["interrupt"]["kind"] == "ask_user" and res["interrupt"]["data"]["questions"] == QUESTIONS

    done = app.resume(trip_id, res["interrupt"]["approval_id"], "approved", {"start_date": "2026-11-27"},
                      client=FakeLLM(), tools=TOOLS)  # fmt: skip
    assert done["interrupt"]["kind"] == "itinerary_approval" and done["status"] == "validated"
    assert seen[1] == ["Nhà mình đi Huế 1 ngày", "Bạn khởi hành ngày nào?", "start_date: 2026-11-27"]
    assert done["run_id"] == res["run_id"]
    assert repo.query("SELECT uc FROM runs WHERE run_id = ?", (res["run_id"],)) == [{"uc": "UC-01"}]


def test_outside_hue_stops_with_message(db, monkeypatch):
    fake_intake(monkeypatch, ["unsupported"])
    trip_id = repo.create_trip("u-ha")
    repo.add_message(trip_id, "u-ha", "user", "Đi Đà Lạt 2 ngày")
    res = app.run_uc01(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS)
    assert res["status"] == "succeeded" and res["interrupt"] is None and res["itinerary_id"] is None
    last = repo.query("SELECT role, content FROM messages WHERE trip_id = ? ORDER BY rowid DESC LIMIT 1", (trip_id,))
    assert last == [{"role": "assistant", "content": "Hiện chỉ hỗ trợ Huế"}]


def test_messages_api_runs_in_background_and_answers_question(db, monkeypatch):
    fake_intake(monkeypatch, ["ask_user", "plan"])
    monkeypatch.setattr(app, "make_client", FakeLLM)
    monkeypatch.setattr(app, "default_tools", lambda: TOOLS)
    monkeypatch.setattr(stream, "POLL_S", 0.01)
    c = TestClient(server.app)
    c.post("/api/session", json={"user_id": "u-ha"})
    trip_id = c.post("/api/trips", json={}).json()["trip_id"]

    first = c.post(f"/api/trips/{trip_id}/messages", json={"text": "Đi Huế"}).json()
    events = read_sse(c, first["run_id"])
    assert events[-2][0] == "interrupt" and events[-2][1]["kind"] == "ask_user"

    second = c.post(f"/api/trips/{trip_id}/messages", json={"text": "27/11"}).json()  # tin nhắn = câu trả lời
    assert second["run_id"] == first["run_id"]
    events = read_sse(c, second["run_id"])
    assert events[-2][1]["kind"] == "itinerary_approval"
    texts = [m["content"] for m in repo.query("SELECT content FROM messages WHERE trip_id = ? AND role = 'user'"
                                              " ORDER BY rowid", (trip_id,))]  # fmt: skip
    assert texts == ["Đi Huế", "27/11"]  # câu trả lời lưu đúng 1 lần

    other = TestClient(server.app)
    other.post("/api/session", json={"user_id": "u-minh"})
    assert other.post(f"/api/trips/{trip_id}/messages", json={"text": "x"}).status_code == 404


def test_new_chat_run_cancels_stale_pending_requests(db, monkeypatch):
    fake_intake(monkeypatch, ["ask_user", "ask_user"])
    trip_id = repo.create_trip("u-ha")
    old = app.run_uc01(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS)
    app.run_uc01(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS)
    decisions = {r["approval_id"]: r["decision"] for r in repo.query("SELECT approval_id, decision FROM approvals")}
    assert decisions[old["interrupt"]["approval_id"]] == "rejected"
    assert len(app.pending_approvals(trip_id)) == 1
    assert json.loads(repo.query("SELECT payload FROM approvals WHERE decision = 'pending'")[0]["payload"])["kind"] == "ask_user"
