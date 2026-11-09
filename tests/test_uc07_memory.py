"""W9-P1-1: UC-07 trích sở thích → đề xuất lưu → người dùng xác nhận → nạp vào plan chuyến sau."""

import json

from agent.db import repo
from agent.schemas import TripProfile
from agent.src.graph import app
from agent.src.memory import store
from agent.src.nodes import memory
from tests.test_uc02 import PROFILE, TOOLS, FakeLLM, graph_source_facts  # noqa: F401 (fixture autouse)

ALLERGY = "dị ứng hải sản"


def trip_with(**extra):
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(**PROFILE | extra))
    return trip_id


def plan_until_memory_card(trip_id):
    res = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS, approval=True)
    card = app.resume(trip_id, res["interrupt"]["approval_id"], "approved", client=FakeLLM(), tools=TOOLS)["interrupt"]
    assert card["kind"] == "memory_save"
    return res["run_id"], card


def test_only_selected_items_are_saved_and_sensitive_gets_consent(db):
    trip_id = trip_with(hard_constraints=[ALLERGY, "không ăn cay"], pace="relaxed")
    run_id, card = plan_until_memory_card(trip_id)
    items = {i["key"]: i for i in card["data"]["items"]}
    assert items[f"allergy:{ALLERGY}"]["sensitivity"] == "sensitive"
    assert items["other:không ăn cay"]["sensitivity"] == "normal"
    assert "visited_city:Huế" in items

    chosen = [f"allergy:{ALLERGY}", {"key": "pace:relaxed", "value": "relaxed"}, "interest:không-có"]
    done = app.resume(trip_id, card["approval_id"], "approved", chosen, client=FakeLLM(), tools=TOOLS)
    assert done["interrupt"] is None
    saved = {(m["kind"], m["value"], m["sensitivity"]) for m in store.memory_read("u-ha")}
    assert saved == {("allergy", ALLERGY, "sensitive"), ("pace", "relaxed", "normal")}
    assert store.active_consent("u-ha") is not None
    log = repo.query("SELECT result FROM trace_events WHERE run_id = ? AND name = 'memory_write'", (run_id,))
    assert "không nằm trong danh sách" in json.loads(log[0]["result"])["skipped"][0]


def test_rejected_saves_nothing(db):
    trip_id = trip_with()
    _, card = plan_until_memory_card(trip_id)
    app.resume(trip_id, card["approval_id"], "rejected", [i["key"] for i in card["data"]["items"]],
               client=FakeLLM(), tools=TOOLS)  # fmt: skip
    assert store.memory_read("u-ha") == []


def test_next_trip_plan_receives_memory_and_trace_hides_values(db):
    store.grant_sensitive_consent("u-ha")
    store.memory_write("u-ha", "allergy", ALLERGY, "sensitive")
    store.memory_write("u-minh", "interest", "của người khác")
    prompts = []
    llm = FakeLLM()
    create = llm.chat.completions.create

    def spy(**kw):
        prompts.append(json.loads(kw["messages"][1]["content"]))
        return create(**kw)

    llm.chat.completions.create = spy
    res = app.run_uc02(trip_with(), "u-ha", client=llm, tools=TOOLS)
    assert prompts[0]["user_memory"] == [{"kind": "allergy", "value": ALLERGY}]
    used = repo.query("SELECT result FROM trace_events WHERE run_id = ? AND name = 'memory_read'", (res["run_id"],))
    assert ALLERGY not in used[0]["result"] and "allergy" in used[0]["result"]


def test_candidates_skip_what_is_already_remembered(db):
    store.memory_write("u-ha", "interest", "history")
    trip_id = trip_with(mobility_notes="đi lại chậm")
    keys = [i["key"] for i in memory.candidates(repo.latest_profile(trip_id)[1], "u-ha", trip_id)]
    assert "interest:history" not in keys and "interest:food" in keys
    assert ("other:đi lại chậm", "sensitive") in [(i["key"], i["sensitivity"]) for i in
                                                  memory.candidates(repo.latest_profile(trip_id)[1], "u-ha", trip_id)]
