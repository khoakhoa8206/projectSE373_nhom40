"""UC-06: reviewer chỉ đọc (permissions.yaml), ReviewReport, slot_ref phải có thật, vòng planner ↔ reviewer."""

import json
from types import SimpleNamespace as NS

from openai.types.chat import ChatCompletion
from pydantic import BaseModel

from agent.db import repo
from agent.schemas import Itinerary
from agent.src.graph import app
from agent.src.graph.loop import SUBMIT, agent_loop, permitted
from agent.src.nodes.review import ROLES, review
from tests.test_uc02 import TOOLS, FakeLLM, call, graph_source_facts, new_trip  # noqa: F401 (fixture autouse)

APPROVE = {"verdict": "approve", "findings": []}


class ReviewerLLM:
    """LLM giả cho 3 reviewer chạy song song: nhận ra vai qua system prompt, nộp ngay report[vai]({slot_ids})."""

    def __init__(self, reports):
        self.reports, self.calls = reports, []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        name = next(n for n, role in ROLES.items() if role in kw["messages"][0]["content"])
        self.calls.append(name)
        slot_ids = [s["slot_id"] for s in json.loads(kw["messages"][1]["content"])["slots"]]
        report = self.reports.get(name, APPROVE)
        message = {"content": None, "tool_calls": [call("s", SUBMIT, report(slot_ids) if callable(report) else report)]}
        return ChatCompletion.model_validate({
            "id": "x", "object": "chat.completion", "created": 0, "model": "fake-reviewer",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", **message}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0},
        })  # fmt: skip


def validated_state():
    """Lịch trình UC-02 thật (LLM giả) đã lưu DB, làm đầu vào cho review."""
    trip_id = new_trip()
    res = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS)
    row = repo.itinerary_for_trip(trip_id)
    _, profile = repo.latest_profile(trip_id)
    return {"run_id": res["run_id"], "trip_id": trip_id, "itinerary": Itinerary.model_validate(row), "profile": profile}


def safety_rejects(slot_ids):
    return {"verdict": "request_changes", "findings": [
        {"slot_ref": slot_ids[0], "severity": "high", "rule": "restricted_area", "message": "trong khu cấm"},
        {"slot_ref": "it-bia:d9-s9", "severity": "high", "rule": "child_safety", "message": "slot bịa"},
        {"slot_ref": None, "severity": "low", "rule": "note", "message": "ghi chú cả chuyến"},
    ]}  # fmt: skip


def test_review_round_saves_three_reports_and_drops_fake_slot_ref(db):
    state = validated_state()
    usage = {"in": 0, "out": 0, "cost": 0.0}
    out = review(state, ReviewerLLM({"safety": safety_rejects}), TOOLS, usage)

    it_id = state["itinerary"].itinerary_id
    reports = repo.reviews_for_itinerary(it_id)
    assert sorted(r["reviewer"] for r in reports) == ["budget", "local_expert", "safety"]
    safety = next(r for r in reports if r["reviewer"] == "safety")
    assert safety["verdict"] == "request_changes" and len(safety["findings"]) == 2  # slot bịa bị bỏ
    assert {f["slot_ref"] for f in safety["findings"]} == {state["itinerary"].slots[0].slot_id, None}
    # chỉ finding medium/high về planner; còn vòng 2 nên chưa chốt reviewed
    assert [f["rule"] for f in out["review_findings"]] == ["restricted_area"] and out["review_again"]
    assert out["itinerary"].status == "validated" and usage["in"] == 30

    trace = repo.query("SELECT node, kind, name FROM trace_events WHERE run_id = ? AND node LIKE 'reviewer.%'",
                       (state["run_id"],))  # fmt: skip
    assert {"node": "reviewer.safety", "kind": "guardrail", "name": "unknown_slot_ref"} in trace
    for name in ROLES:  # coordination trace: orchestrator → reviewer → orchestrator
        kinds = [e["kind"] for e in trace if e["node"] == f"reviewer.{name}"]
        assert kinds[0] == "node_start" and "node_end" in kinds


def test_last_round_marks_reviewed_and_reviewer_error_does_not_block(db):
    state = validated_state() | {"review_round": 1}

    def broken(_slot_ids):
        return {"verdict": "không hợp lệ"}  # LLM nộp sai schema mãi → hết lượt → lỗi reviewer

    out = review(state, ReviewerLLM({"budget": broken, "safety": safety_rejects}), TOOLS, {"in": 0, "out": 0, "cost": 0.0})
    assert out["review_round"] == 2 and not out["review_again"]
    row = repo.query("SELECT status, review_rounds FROM itineraries WHERE itinerary_id = ?",
                     (state["itinerary"].itinerary_id,))[0]  # fmt: skip
    assert row == {"status": "reviewed", "review_rounds": 2}
    assert sorted(r["reviewer"] for r in repo.reviews_for_itinerary(state["itinerary"].itinerary_id)) == ["local_expert", "safety"]
    errors = repo.query("SELECT node FROM trace_events WHERE run_id = ? AND kind = 'error'", (state["run_id"],))
    assert errors == [{"node": "reviewer.budget"}]


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


class TeamLLM:
    """Planner dùng FakeLLM của UC-02, reviewer dùng ReviewerLLM; ghi lại input của planner để kiểm findings."""

    def __init__(self, reports):
        self.planner, self.reviewers, self.planner_inputs = FakeLLM(), ReviewerLLM(reports), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        if any(role in kw["messages"][0]["content"] for role in ROLES.values()):
            return self.reviewers.create(**kw)
        self.planner_inputs.append(kw["messages"][1]["content"])
        return self.planner.create(**kw)


def run_reviewed(reports):
    trip_id = new_trip()
    llm = TeamLLM(reports)
    res = app.run_uc02(trip_id, "u-ha", client=llm, tools=TOOLS, review=True)
    its = repo.query("SELECT itinerary_id, status, review_rounds FROM itineraries WHERE trip_id = ? ORDER BY version",
                     (trip_id,))  # fmt: skip
    return res, its, llm


def test_findings_go_back_to_planner_then_second_round_approves(db):
    answers = iter([safety_rejects, lambda _ids: APPROVE])  # vòng 1 safety chặn, vòng 2 duyệt
    res, its, llm = run_reviewed({"safety": lambda ids: next(answers)(ids)})
    assert res["error"] is None and res["status"] == "reviewed"
    assert [(i["status"], i["review_rounds"]) for i in its] == [("superseded", 1), ("reviewed", 2)]
    assert [r["round"] for r in repo.reviews_for_itinerary(its[0]["itinerary_id"])] == [1, 1, 1]
    assert [r["round"] for r in repo.reviews_for_itinerary(its[1]["itinerary_id"])] == [2, 2, 2]
    assert "restricted_area" in llm.planner_inputs[-1] and "restricted_area" not in llm.planner_inputs[0]


def test_review_stops_after_two_rounds_even_if_still_rejected(db):
    res, its, llm = run_reviewed({"safety": safety_rejects})
    assert res["status"] == "reviewed" and [i["review_rounds"] for i in its] == [1, 2]
    assert llm.reviewers.calls.count("safety") == 2


def test_without_review_flag_graph_skips_reviewers(db):
    res = app.run_uc02(new_trip(), "u-ha", client=TeamLLM({}), tools=TOOLS)
    assert res["status"] == "validated"
    assert not repo.query("SELECT 1 FROM trace_events WHERE run_id = ? AND node LIKE 'reviewer.%'", (res["run_id"],))


def test_ui_review_shows_both_rounds_and_coordination(db, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)  # import lần đầu: fullstack.api chọn planner giả như test_fullstack
    from fullstack.api import _review

    answers = iter([safety_rejects, lambda _ids: APPROVE])
    res, its, _ = run_reviewed({"safety": lambda ids: next(answers)(ids)})
    trip_id = repo.query("SELECT trip_id FROM runs WHERE run_id = ?", (res["run_id"],))[0]["trip_id"]
    out = _review(repo.itinerary_for_trip(trip_id))

    assert [r["round"] for r in out["reports"]] == [1, 1, 1, 2, 2, 2]  # vòng 1 ở bản lịch đã superseded vẫn hiện
    first = next(r for r in out["reports"] if r["reviewer"] == "safety" and r["round"] == 1)
    assert first["findings"][0]["name_vi"]  # finding gắn tên POI của slot, kể cả slot của bản cũ
    talk = [(m["from"], m["to"]) for m in out["coordination"]]
    assert ("orchestrator", "safety") in talk and ("safety", "orchestrator") in talk
    assert talk.count(("orchestrator", "planner")) == 1 and talk[-1] == ("orchestrator", "người dùng")
