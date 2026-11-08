"""W8-P1-2: interrupt dùng chung + bước người dùng duyệt lịch trình + API resume (LLM, tool giả)."""

import json

from fastapi.testclient import TestClient

from agent.db import repo
from agent.src.api import server
from agent.src.graph import app
from tests.test_checkpoint import CountingLLM
from tests.test_uc02 import PROFILE, TOOLS, FakeLLM, graph_source_facts, new_trip  # noqa: F401 (fixture autouse)


def run_status(run_id):
    return repo.query("SELECT status FROM runs WHERE run_id = ?", (run_id,))[0]["status"]


def test_plan_stops_for_approval_then_resumes_without_replanning(db):
    trip_id = new_trip()
    res = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS, approval=True)
    assert res["status"] == "validated" and run_status(res["run_id"]) == "interrupted"
    payload = res["interrupt"]
    assert payload["kind"] == "itinerary_approval" and payload["data"]["itinerary_id"] == res["itinerary_id"]
    assert app.pending_approvals(trip_id) == [payload]

    llm = CountingLLM()  # backend restart: client/graph/kết nối checkpoint tạo mới
    done = app.resume(trip_id, payload["approval_id"], "approved", client=llm, tools=TOOLS)
    assert llm.calls == 0 and done["status"] == "approved" and done["interrupt"] is None
    assert run_status(res["run_id"]) == "succeeded"
    assert repo.query("SELECT status FROM itineraries WHERE itinerary_id = ?", (res["itinerary_id"],)) == [
        {"status": "approved"}]
    assert repo.query("SELECT status FROM trips WHERE trip_id = ?", (trip_id,)) == [{"status": "approved"}]
    row = repo.query("SELECT decision, decided_at FROM approvals WHERE approval_id = ?", (payload["approval_id"],))[0]
    assert row["decision"] == "approved" and row["decided_at"]
    assert app.resume(trip_id, payload["approval_id"], "approved", client=llm, tools=TOOLS) is None  # bấm lần 2
    approvals = repo.query("SELECT name FROM trace_events WHERE run_id = ? AND kind = 'approval'", (res["run_id"],))
    assert len(approvals) == 2  # lúc dừng + lúc người dùng trả lời


def test_edited_replans_with_user_feedback(db):
    trip_id = new_trip()
    first = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS, approval=True)
    seen = []
    llm = FakeLLM()
    create = llm.chat.completions.create

    def spy(**kw):
        seen.append(kw["messages"][1]["content"])
        return create(**kw)

    llm.chat.completions.create = spy
    again = app.resume(trip_id, first["interrupt"]["approval_id"], "edited", "Bỏ chợ, thêm chùa", client=llm, tools=TOOLS)
    assert json.loads(seen[0])["user_feedback"] == "Bỏ chợ, thêm chùa"
    assert again["itinerary_id"] != first["itinerary_id"] and again["interrupt"]["kind"] == "itinerary_approval"
    statuses = repo.query("SELECT itinerary_id, status FROM itineraries ORDER BY version")
    assert [s["status"] for s in statuses] == ["superseded", "validated"]


def test_rejected_returns_to_profile(db):
    trip_id = new_trip()
    res = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS, approval=True)
    done = app.resume(trip_id, res["interrupt"]["approval_id"], "rejected", client=FakeLLM(), tools=TOOLS)
    assert done["status"] == "validated" and run_status(res["run_id"]) == "succeeded"
    assert repo.query("SELECT status FROM trips WHERE trip_id = ?", (trip_id,)) == [{"status": "profiling"}]


def test_waiting_graph_is_not_continued_by_continue_run(db):
    trip_id = new_trip()
    app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS, approval=True)
    assert app.continue_run(trip_id, client=FakeLLM(), tools=TOOLS) is None  # phải đợi người dùng, không tự hỏi lại
    assert len(app.pending_approvals(trip_id)) == 1


def test_ask_human_rejects_unknown_kind():
    try:
        app.ask_human("pay_now", {})
    except ValueError:
        return
    raise AssertionError("kind lạ phải bị từ chối")


def test_api_resume_flow_and_ownership(db, monkeypatch):
    monkeypatch.setattr(app, "make_client", FakeLLM)
    monkeypatch.setattr(app, "default_tools", lambda: TOOLS)
    c = TestClient(server.app)
    c.post("/api/session", json={"user_id": "u-ha"})
    trip_id = c.post("/api/trips", json=PROFILE).json()["trip_id"]
    plan = c.post(f"/api/trips/{trip_id}/plan").json()
    approval_id = plan["interrupt"]["approval_id"]
    assert c.get(f"/api/trips/{trip_id}/approvals").json() == [plan["interrupt"]]

    other = TestClient(server.app)
    other.post("/api/session", json={"user_id": "u-minh"})
    body = {"approval_id": approval_id, "decision": "approved"}
    assert other.post(f"/api/trips/{trip_id}/resume", json=body).status_code == 404
    assert c.post(f"/api/trips/{trip_id}/resume", json=body | {"decision": "maybe"}).status_code == 422

    done = c.post(f"/api/trips/{trip_id}/resume", json=body).json()
    assert done["status"] == "approved"
    assert c.post(f"/api/trips/{trip_id}/resume", json=body).status_code == 409
    assert c.get(f"/api/trips/{trip_id}/approvals").json() == []
    assert c.post(f"/api/trips/{trip_id}/messages", json={"text": "xin chào"}).status_code == 501  # UC-01 chưa đăng ký
