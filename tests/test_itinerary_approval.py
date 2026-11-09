"""Interrupt/resume trong RAM, không phải bằng chứng khởi động lại backend."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.db import repo
from agent.schemas import Itinerary, Slot, TripProfile
from agent.src.graph import app
from agent.src.nodes.plan import fill_facts


@pytest.fixture
def review(db, monkeypatch):
    trip = repo.create_trip("u-ha")
    repo.save_profile(trip, TripProfile(start_date="2026-11-27", end_date="2026-11-27", adults=1))
    run = repo.create_run("UC-02", trip, "u-ha")

    def plan(state, *args):
        round_ = state["round"] + 1
        itinerary = Itinerary(itinerary_id=state["itinerary_id"], trip_id=trip, profile_id=state["profile_id"],
                              planner_rounds=round_, run_id=run, slots=[Slot(
                                  slot_id=repo.new_id("s"), day_index=1, slot_date="2026-11-27",
                                  start_time="09:00", end_time="10:00", poi_id="hue-dai-noi",
                                  activity=state.get("feedback") or "Bản đầu", cost_source="unverified",
                                  hours_status="unverified")])
        return {"itinerary": itinerary, "round": round_}

    monkeypatch.setattr(app, "plan", plan)
    monkeypatch.setattr(app, "validate", lambda *args: [])
    monkeypatch.setattr(app, "check_fabrication", lambda *args: [])
    graph = app.build_approval_graph(object(), [], {}, InMemorySaver())
    config = {"configurable": {"thread_id": trip}}
    result = graph.invoke({"trip_id": trip, "user_id": "u-ha", "run_id": run,
                           "itinerary_id": repo.new_id("it")}, config)
    return graph, config, result, trip


def answer(result, decision, response=None):
    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "itinerary_approval"
    return Command(resume={"approval_id": payload["approval_id"], "decision": decision, "response": response})


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_decisions_are_persisted_and_stop(review, decision):
    graph, config, result, trip = review
    graph.invoke(answer(result, decision), config)
    assert not graph.get_state(config).next
    assert repo.query("SELECT decision FROM approvals")[0]["decision"] == decision
    assert repo.itinerary_for_trip(trip)["status"] == ("approved" if decision == "approved" else "validated")


def test_edit_replans_with_feedback_and_total_four_rounds(review):
    graph, config, result, trip = review
    for round_ in (2, 3, 4):
        result = graph.invoke(answer(result, "edited", f"Sửa vòng {round_}"), config)
        assert result["round"] == round_
        assert repo.itinerary_for_trip(trip)["slots"][0]["activity"] == f"Sửa vòng {round_}"
    result = graph.invoke(answer(result, "edited", "Không được chạy vòng 5"), config)
    assert result["round"] == 4 and not graph.get_state(config).next
    assert "chưa áp dụng" in result["planning_warning"]


def test_approval_replay_does_not_create_duplicate_rows(review):
    graph, config, result, _trip = review
    graph.invoke(answer(result, "approved"), config)
    assert len(repo.query("SELECT * FROM approvals")) == 1


def test_wrong_approval_id_cannot_resume(review):
    graph, config, _result, _trip = review
    with pytest.raises(ValueError, match="approval_id"):
        graph.invoke(Command(resume={"approval_id": "wrong", "decision": "approved"}), config)
    assert repo.query("SELECT decision FROM approvals")[0]["decision"] == "pending"


def test_owner_and_stale_approval_guards(review):
    graph, config, result, trip = review
    approval_id = result["__interrupt__"][0].value["approval_id"]
    with pytest.raises(ValueError, match="người dùng"):
        repo.decide_itinerary_approval(approval_id, trip, "u-emma", "approved")
    graph.invoke(answer(result, "edited", "Bản mới"), config)
    with pytest.raises(ValueError, match="lịch trình cũ"):
        repo.decide_itinerary_approval(approval_id, trip, "u-ha", "approved")


def test_edit_requires_nonempty_feedback(review):
    graph, config, result, _trip = review
    with pytest.raises(ValueError, match="nội dung"):
        graph.invoke(answer(result, "edited", "  "), config)


def test_missing_route_clears_unverified_llm_number():
    first = Slot(day_index=1, slot_date="2026-11-27", start_time="09:00", end_time="10:00",
                 poi_id="a", activity="A", cost_source="unverified", hours_status="unverified")
    second = first.model_copy(update={"poi_id": "b", "start_time": "11:00", "end_time": "12:00",
                                      "travel_minutes_from_prev": 17})
    facts = {"matrix": [], "pois": {key: {"opening_hours": None, "ticket_price_vnd": None} for key in ("a", "b")}}
    fill_facts([first, second], 1, facts)
    assert second.travel_minutes_from_prev is None
    assert "chưa có thời gian di chuyển" in second.note
