"""Chặn vòng tra cứu vô hạn, tái dùng facts và giữ bản đã kiểm khi sửa hết lượt; không LLM thật."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import InternalServerError, RateLimitError
from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from agent.db import repo
from agent.schemas import Itinerary, Slot, TripProfile, Violation
from agent.src.graph import app, loop
from agent.src.nodes.plan import previous_facts


class Result(BaseModel):
    ok: bool


def response(name, args):
    return ChatCompletion.model_validate({
        "id": "test", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                     "tool_calls": [{"id": "test-call", "type": "function", "function": {
                         "name": name, "arguments": json.dumps(args)}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    })


def lookup() -> dict:
    """Tool giả đã có đủ facts; gọi lại không cho thông tin mới."""
    return {"status": "unverified"}


class BudgetLLM:
    def __init__(self, obey=True, invalid_once=False):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.calls = []
        self.obey = obey
        self.invalid_once = invalid_once

    def create(self, **kwargs):
        self.calls.append(kwargs.get("tool_choice"))
        if self.obey and kwargs.get("tool_choice"):
            if self.invalid_once:
                self.invalid_once = False
                return response("submit_result", {"wrong_field": True})
            return response("submit_result", {"ok": True})
        return response("lookup", {})


def test_force_submission_before_budget_is_used_up(db):
    run_id = repo.create_run("UC-02", None, "u-ha")
    client = BudgetLLM()
    result = loop.agent_loop(client, "test", "test", [lookup], Result, run_id, "plan",
                             {"in": 0, "out": 0, "cost": 0.0}, max_turns=4)
    assert result.ok and len(client.calls) == 3
    assert client.calls[-1] == {"type": "function", "function": {"name": "submit_result"}}
    assert repo.query("SELECT COUNT(*) AS n FROM trace_events WHERE name='require_submission'")[0]["n"] == 1


def test_last_turn_can_repair_invalid_structured_submission(db):
    run_id = repo.create_run("UC-02", None, "u-ha")
    client = BudgetLLM(invalid_once=True)
    result = loop.agent_loop(client, "test", "test", [lookup], Result, run_id, "plan",
                             {"in": 0, "out": 0, "cost": 0.0}, max_turns=4)
    assert result.ok and len(client.calls) == 4
    assert client.calls[-1] and client.calls[-2]


def test_provider_ignoring_tool_choice_still_hits_hard_limit(db):
    run_id = repo.create_run("UC-02", None, "u-ha")
    client = BudgetLLM(obey=False)
    with pytest.raises(loop.AgentLoopLimitError):
        loop.agent_loop(client, "test", "test", [lookup], Result, run_id, "plan",
                        {"in": 0, "out": 0, "cost": 0.0}, max_turns=4)
    assert len(client.calls) == 4


def draft(state, round_):
    slot = Slot(slot_id=f"{state['itinerary_id']}:d1-s1", day_index=1, slot_date="2026-11-27",
                start_time="09:00", end_time="10:00", poi_id="hue-dai-noi", activity="Bản đầu có nguồn",
                cost_source="unverified", hours_status="unverified")
    return Itinerary(itinerary_id=state["itinerary_id"], trip_id=state["trip_id"], profile_id=state["profile_id"],
                     run_id=state["run_id"], planner_rounds=round_, slots=[slot])


def test_turn_limit_on_repair_returns_checked_best_with_remaining_errors(db, monkeypatch):
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(start_date="2026-11-27", end_date="2026-11-27", adults=1))

    def plan(state, *args):
        if state["round"]:
            raise loop.AgentLoopLimitError("test: sửa lịch hết lượt")
        return {"itinerary": draft(state, 1), "round": 1}

    monkeypatch.setattr(app, "plan", plan)
    monkeypatch.setattr(app, "validate", lambda *args: [Violation(rule="weather", severity="high", message="còn lỗi mưa")])
    result = app.run_uc02(trip_id, "u-ha", client=object(), tools=[])
    assert result["error"] is None and result["status"] == "failed_validation"
    stored = repo.itinerary_for_trip(trip_id)
    assert stored["planner_rounds"] == 2 and stored["slots"][0]["activity"] == "Bản đầu có nguồn"
    assert "hết lượt" in stored["slots"][0]["note"]
    assert len(stored["violations"]) == 1 and stored["violations"][0]["message"] == "còn lỗi mưa"
    assert repo.query("SELECT name FROM trace_events WHERE name='keep_best_on_turn_limit'")


def test_first_round_limit_does_not_create_fake_itinerary(db, monkeypatch):
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(start_date="2026-11-27", end_date="2026-11-27", adults=1))

    def plan(*args):
        raise loop.AgentLoopLimitError("test: chưa có draft")

    monkeypatch.setattr(app, "plan", plan)
    result = app.run_uc02(trip_id, "u-ha", client=object(), tools=[])
    assert result["status"] == "error" and "AgentLoopLimitError" in result["error"]
    assert repo.itinerary_for_trip(trip_id) is None


def test_other_runtime_errors_are_not_silenced(db, monkeypatch):
    state = {"best_itinerary": object()}

    def plan(*args):
        raise RuntimeError("test: lỗi code không phải hết lượt")

    monkeypatch.setattr(app, "plan", plan)
    with pytest.raises(RuntimeError, match="lỗi code"):
        app.plan_or_keep_best(state, object(), [], {})


@pytest.mark.parametrize("status,error_class", [(429, RateLimitError), (503, InternalServerError)])
def test_provider_error_on_repair_keeps_checked_best(db, monkeypatch, status, error_class):
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(start_date="2026-11-27", end_date="2026-11-27", adults=1))

    def plan(state, *args):
        if state["round"]:
            response = httpx.Response(status, request=httpx.Request("POST", "https://example.org/test"))
            raise error_class("test provider error", response=response, body=None)
        return {"itinerary": draft(state, 1), "round": 1}

    monkeypatch.setattr(app, "plan", plan)
    monkeypatch.setattr(app, "validate", lambda *args: [Violation(rule="weather", severity="high", message="còn lỗi mưa")])
    result = app.run_uc02(trip_id, "u-ha", client=object(), tools=[])
    assert result["error"] is None and result["status"] == "failed_validation"
    stored = repo.itinerary_for_trip(trip_id)
    assert len(stored["violations"]) == 1 and f"HTTP {status}" in stored["slots"][0]["note"]
    assert repo.query("SELECT name FROM trace_events WHERE name='keep_best_on_provider_error'")


def test_provider_error_before_any_draft_still_reports_failure(db, monkeypatch):
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(start_date="2026-11-27", end_date="2026-11-27", adults=1))

    def plan(*args):
        response = httpx.Response(503, request=httpx.Request("POST", "https://example.org/test"))
        raise InternalServerError("test overload", response=response, body=None)

    monkeypatch.setattr(app, "plan", plan)
    result = app.run_uc02(trip_id, "u-ha", client=object(), tools=[])
    assert result["status"] == "error" and "InternalServerError" in result["error"]
    assert repo.itinerary_for_trip(trip_id) is None


def test_previous_facts_reuse_observations_and_only_fetch_missing(db):
    run_id = repo.create_run("UC-02", None, "u-ha")
    first = Slot(day_index=1, slot_date="2026-11-27", start_time="09:00", end_time="10:00", poi_id="hue-dai-noi",
                 activity="A", cost_source="unverified", hours_status="unverified")
    second = first.model_copy(update={"poi_id": "hue-cho-dong-ba", "start_time": "11:00", "end_time": "12:00"})
    state = {"run_id": run_id, "itinerary": Itinerary(slots=[first, second])}
    args = {"date": "2026-11-27", "poi_id": "hue-dai-noi"}
    repo.log_event(run_id, "plan", "tool_call", name="get_opening_hours", args=args,
                   result={"hours_status": "unverified", "intervals": None})
    calls = []

    def get_opening_hours(poi_id: str, date: str):
        calls.append((poi_id, date))
        return {"hours_status": "unverified", "intervals": None}

    def get_travel_time(from_poi_id: str, to_poi_id: str, mode: str):
        calls.append((from_poi_id, to_poi_id, mode))
        return {"minutes": 6}

    tools = {"get_opening_hours": get_opening_hours, "get_travel_time": get_travel_time}
    facts = previous_facts(state, tools)
    assert len(facts) == 3 and len(calls) == 2
    assert facts[0]["cached_from_run"] and facts[0]["result"]["intervals"] is None
    assert len(previous_facts(state, tools)) == 3 and len(calls) == 2  # tool unknown cũng không hỏi lại
    assert previous_facts({"run_id": run_id}, tools) == []


def test_previous_facts_do_not_use_failed_or_other_run_results(db):
    run_id = repo.create_run("UC-02", None, "u-ha")
    other = repo.create_run("UC-02", None, "u-ha")
    state = {"run_id": run_id}
    state["itinerary"] = draft(dict(state, itinerary_id="it-test", trip_id="t-test", profile_id=1), 1)
    args = {"date": "2026-11-27", "poi_id": "hue-dai-noi"}
    repo.log_event(run_id, "plan", "tool_call", name="get_opening_hours", args=args, result=None, error="failed")
    repo.log_event(other, "plan", "tool_call", name="get_opening_hours", args=args, result={"fake_other_run": True})
    facts = previous_facts(state, {"get_opening_hours": lambda **kwargs: {"hours_status": "unverified"}})
    assert facts[0]["cached_from_run"] is False and "fake_other_run" not in facts[0]["result"]
