"""Graph UC-02 + API chạy với LLM giả và tool giả trả kết quả cố định (không cần API key)."""

import json
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletion

from agent.db import repo
from agent.schemas import TripProfile, Violation
from agent.src.api import server
from agent.src.graph import app
from agent.src.graph.loop import SUBMIT as SUBMIT_NAME

PROFILE = {"start_date": "2026-11-27", "end_date": "2026-11-27", "adults": 2, "interests": ["history", "food"]}
ITINERARY = {"slots": [
    {"day_index": 1, "slot_date": "2026-11-27", "start_time": "10:15", "end_time": "11:15", "poi_id": "hue-cho-dong-ba",
     "activity": "Ăn sáng ở chợ Đông Ba", "travel_minutes_from_prev": 6, "cost_vnd": 100000, "cost_source": "tool",
     "hours_status": "unverified"},
    {"day_index": 1, "slot_date": "2026-11-27", "start_time": "08:00", "end_time": "10:00", "poi_id": "hue-dai-noi",
     "activity": "Tham quan Đại Nội", "cost_source": "unverified", "hours_status": "unverified"},
]}  # fmt: skip


def get_opening_hours(poi_id: str, date: str) -> dict:
    """Giờ mở cửa (giả)."""
    return {"opening_hours": None, "status": "unverified"}


def get_travel_time(from_poi_id: str, to_poi_id: str, mode: str = "drive") -> dict:
    """Thời gian di chuyển (giả)."""
    return {"minutes": 6, "distance_m": 1400, "provider": "osrm"}


TOOLS = [get_opening_hours, get_travel_time]


def call(id, name, args):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


GET_DATA = {"content": None, "tool_calls": [
    call("c1", "get_opening_hours", {"poi_id": "hue-dai-noi", "date": "2026-11-27"}),
    call("c2", "get_travel_time", {"from_poi_id": "hue-dai-noi", "to_poi_id": "hue-cho-dong-ba"}),
]}  # fmt: skip
SUBMIT = {"content": None, "tool_calls": [call("c3", SUBMIT_NAME, ITINERARY)]}


class FakeLLM:
    """OpenRouter giả. Mặc định mỗi vòng plan: lượt 1 gọi 2 tool, lượt 2 nộp lịch trình cố định.
    Truyền `script` để trả lần lượt các message cho trước."""

    def __init__(self, script=None):
        self.script = iter(script) if script else None
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        message = next(self.script) if self.script else SUBMIT if kw["messages"][-1]["role"] == "tool" else GET_DATA
        return ChatCompletion.model_validate({
            "id": "x", "object": "chat.completion", "created": 0, "model": "fake",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if message["tool_calls"] else "stop",
                         "message": {"role": "assistant", **message}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost": 0},
        })  # fmt: skip


def new_trip():
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(**PROFILE))
    return trip_id


def test_graph_runs_with_fake_tools(db):
    res = app.run_uc02(new_trip(), "u-ha", client=FakeLLM(), tools=TOOLS)
    assert res["error"] is None and res["status"] == "validated"

    kinds = [e["kind"] for e in repo.query("SELECT kind FROM trace_events WHERE run_id = ?", (res["run_id"],))]
    assert len(kinds) >= 6 and {"node_start", "node_end", "llm_call", "tool_call", "skill_use"} <= set(kinds)
    run = repo.query("SELECT * FROM runs WHERE run_id = ?", (res["run_id"],))[0]
    assert (run["status"], run["tokens_in"], run["tokens_out"]) == ("succeeded", 200, 100)

    it = repo.query("SELECT * FROM itineraries WHERE itinerary_id = ?", (res["itinerary_id"],))[0]
    assert (it["planner_rounds"], it["total_cost_vnd"], it["has_unpriced_item"]) == (1, 100000, 1)
    slots = repo.query("SELECT slot_id, poi_id FROM itinerary_slots WHERE itinerary_id = ? ORDER BY slot_id",
                       (res["itinerary_id"],))  # fmt: skip
    assert slots == [{"slot_id": f"{res['itinerary_id']}:d1-s1", "poi_id": "hue-dai-noi"},
                     {"slot_id": f"{res['itinerary_id']}:d1-s2", "poi_id": "hue-cho-dong-ba"}]  # fmt: skip


def test_invalid_submit_is_repaired(db):
    bad = json.loads(json.dumps(ITINERARY))
    bad["slots"][1]["cost_vnd"] = 30000  # giá bịa cho POI chưa có giá → Pydantic từ chối, LLM phải nộp lại
    script = [GET_DATA, {"content": None, "tool_calls": [call("c3", SUBMIT_NAME, bad)]},
              {"content": f"```json\n{json.dumps(ITINERARY)}\n```", "tool_calls": None}]  # lần 2 nộp dạng text  # fmt: skip
    res = app.run_uc02(new_trip(), "u-ha", client=FakeLLM(script), tools=TOOLS)
    assert res["status"] == "validated"
    llm_calls = repo.query("SELECT 1 FROM trace_events WHERE run_id = ? AND kind = 'llm_call'", (res["run_id"],))
    assert len(llm_calls) == 3


def test_violation_loops_back_to_plan(db, monkeypatch):
    calls = []

    def validate_fails_until(n):
        def fake(itinerary, profile, weather):
            calls.append(1)
            if len(calls) >= n:
                return []
            return [Violation(rule="weather", severity="high", slot_id=itinerary.slots[0].slot_id, message="mưa")]

        return fake

    monkeypatch.setattr(app, "validate", validate_fails_until(2))
    res = app.run_uc02(new_trip(), "u-ha", client=FakeLLM(), tools=TOOLS)
    it = repo.query("SELECT status, planner_rounds FROM itineraries WHERE itinerary_id = ?", (res["itinerary_id"],))
    assert it == [{"status": "validated", "planner_rounds": 2}]
    v = repo.query("SELECT round, slot_id, resolved FROM validation_violations")
    assert v == [{"round": 1, "slot_id": f"{res['itinerary_id']}:d1-s1", "resolved": 1}]

    calls.clear()
    monkeypatch.setattr(app, "validate", validate_fails_until(99))
    res = app.run_uc02(new_trip(), "u-ha", client=FakeLLM(), tools=TOOLS)
    it = repo.query("SELECT status, planner_rounds FROM itineraries WHERE itinerary_id = ?", (res["itinerary_id"],))
    assert it == [{"status": "failed_validation", "planner_rounds": 4}]
    unresolved = repo.query("SELECT round FROM validation_violations WHERE itinerary_id = ? AND resolved = 0",
                            (res["itinerary_id"],))  # fmt: skip
    assert unresolved == [{"round": 4}]


def test_api_flow_and_ownership(db, monkeypatch):
    monkeypatch.setattr(app, "make_client", FakeLLM)
    monkeypatch.setattr(app, "default_tools", lambda: TOOLS)
    c = TestClient(server.app)

    assert c.post("/api/trips", json=PROFILE).status_code == 401
    assert c.post("/api/session", json={"user_id": "u-hacker"}).status_code == 400
    assert c.post("/api/session", json={"user_id": "u-ha"}).status_code == 200
    trip_id = c.post("/api/trips", json=PROFILE).json()["trip_id"]
    plan = c.post(f"/api/trips/{trip_id}/plan").json()
    assert plan["status"] == "validated"

    it = c.get(f"/api/trips/{trip_id}/itinerary").json()
    assert [(s["name_vi"], s["lat"]) for s in it["slots"]] == [("Đại Nội", 16.4698), ("Chợ Đông Ba", 16.4727)]
    trace = c.get(f"/api/runs/{plan['run_id']}/trace").json()
    assert any(e["kind"] == "skill_use" and e["name"] == "itinerary-planning" for e in trace)
    assert len(c.get("/api/pois").json()) == 2

    other = TestClient(server.app)
    other.post("/api/session", json={"user_id": "u-minh"})
    assert other.get(f"/api/trips/{trip_id}/itinerary").status_code == 404
    assert other.get(f"/api/runs/{plan['run_id']}/trace").status_code == 404
    assert other.post(f"/api/trips/{trip_id}/plan").status_code == 404
