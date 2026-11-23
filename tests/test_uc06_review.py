"""UC-06: reviewer chỉ đọc (permissions.yaml), ReviewReport, slot_ref phải có thật, vòng planner ↔ reviewer."""

from pydantic import BaseModel

from agent.db import repo
from agent.src.graph.loop import SUBMIT, agent_loop, permitted
from tests.test_uc02 import FakeLLM, call


def get_poi(poi_id: str) -> dict:
    """POI (giả)."""
    return {"poi_id": poi_id}


def get_weather_forecast(destination_id: str, date: str, run_id: str) -> dict:
    """Thời tiết (giả) — tool có ghi DB, reviewer không được dùng."""
    raise AssertionError("reviewer không được chạy tool ghi DB")


class Out(BaseModel):
    ok: bool


def test_permissions_give_reviewers_read_only_tools():
    names = {f.__name__ for f in permitted("reviewer.safety", [get_poi, get_weather_forecast])}
    assert names == {"get_poi"}
    assert permitted("agent.khong-co", [get_poi]) == []


def test_tool_outside_permissions_is_blocked_and_traced(db):
    run_id = repo.create_run("UC-06", repo.create_trip("u-ha"), "u-ha")
    script = [
        {"content": None, "tool_calls": [call("c1", "get_weather_forecast", {"destination_id": "hue", "date": "2026-11-27"})]},
        {"content": None, "tool_calls": [call("c2", SUBMIT, {"ok": True})]},
    ]  # fmt: skip
    tools = permitted("reviewer.safety", [get_poi, get_weather_forecast])
    usage = {"in": 0, "out": 0, "cost": 0.0}
    assert agent_loop(FakeLLM(script), "sys", "user", tools, Out, run_id, "reviewer.safety", usage).ok
    ev = repo.query("SELECT node, kind, name FROM trace_events WHERE run_id = ? AND kind != 'llm_call'", (run_id,))
    assert ev == [{"node": "reviewer.safety", "kind": "guardrail", "name": "tool_denied"}]
