"""UC-01 dùng LLM giả, không mạng hoặc key."""

import copy
import json
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from agent.db import repo
from agent.src.nodes.intake import IntakeResult, extract_intake, intake, route_intake


def payload(**changes):
    profile = {"start_date": "2026-11-27", "end_date": "2026-11-29", "adults": 2,
               "budget_total_vnd": 8000000, **changes}
    return {"profile": profile, "destination_text": "Huế", "conflicts": []}


class IntakeLLM:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return ChatCompletion.model_validate({
            "id": "test", "object": "chat.completion", "created": 0, "model": "fake-intake",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant",
                         "tool_calls": [{"id": "submit", "type": "function", "function": {
                             "name": "submit_result", "arguments": json.dumps(next(self.outputs))}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })


@pytest.fixture
def run(db):
    trip_id = repo.create_trip("u-ha")
    return {"trip_id": trip_id, "user_id": "u-ha", "run_id": repo.create_run("UC-01", trip_id, "u-ha")}


def usage():
    return {"in": 0, "out": 0, "cost": 0.0}


def test_complete_saves_new_profile_versions(run):
    repo.add_message(run["trip_id"], "u-ha", "user", "Huế 27–29/11/2026, 2 người, 8 triệu")
    for _ in range(2):
        result = intake(run, IntakeLLM([payload()]), usage())
        assert result["route"] == "plan" and result["questions"] == []
    assert [r["version"] for r in repo.query("SELECT version FROM trip_profiles ORDER BY version")] == [1, 2]


@pytest.mark.parametrize("changes,field", [
    ({"start_date": None}, "start_date"), ({"adults": None}, "adults"),
    ({"budget_total_vnd": None}, "budget_total_vnd"),
])
def test_missing_information_is_asked_not_invented(run, changes, field):
    result = extract_intake([], IntakeLLM([payload(**changes)]), run["run_id"], usage())
    assert result["route"] == "ask_user"
    assert field in result["profile"].missing_info
    assert getattr(result["profile"], field) is None
    assert not repo.query("SELECT * FROM trip_profiles")


@pytest.mark.parametrize("changes,field", [
    ({"end_date": "2026-11-26"}, "end_date"), ({"end_date": "2026-12-05"}, "end_date"),
    ({"children": [{"age": 18}]}, "children"), ({"budget_total_vnd": 0}, "budget_total_vnd"),
    ({"adults": 0}, "adults"),
])
def test_business_conflicts_are_not_silently_repaired(run, changes, field):
    result = extract_intake([], IntakeLLM([payload(**changes)]), run["run_id"], usage())
    assert result["route"] == "ask_user" and result["conflicts"]
    assert field in result["profile"].missing_info
    assert not repo.query("SELECT * FROM trip_profiles")


def test_unconfirmed_conflicting_adult_counts_are_cleared():
    data = payload()
    data["conflicts"] = ["adults: 2 hay 4?"]
    result = route_intake(IntakeResult.model_validate(data))
    assert result["route"] == "ask_user" and result["profile"].adults is None


def test_english_questions_and_three_question_limit():
    result = route_intake(IntakeResult.model_validate(payload(
        start_date=None, end_date=None, adults=None, budget_total_vnd=None, language="en")))
    assert len(result["questions"]) == 3
    assert result["questions"][0]["text"].startswith("What")
    assert result["profile"].budget_total_vnd is None


@pytest.mark.parametrize("destination", ["Đà Lạt", "Bangkok", "Hội An"])
def test_outside_hue_is_unsupported(destination):
    data = payload()
    data["destination_text"] = destination
    result = route_intake(IntakeResult.model_validate(data))
    assert result["route"] == "unsupported" and result["message"] == "Hiện chỉ hỗ trợ Huế"
    assert result["questions"] == []


def test_schema_repair_receives_validation_error(run):
    llm = IntakeLLM([{}, payload()])
    assert extract_intake([], llm, run["run_id"], usage())["route"] == "plan"
    assert len(llm.requests) == 2
    assert any("không hợp lệ" in str(m.get("content")) for m in llm.requests[1]["messages"])


def test_three_invalid_schemas_stop_without_profile(run):
    llm = IntakeLLM([{}, {}, {}])
    with pytest.raises(ValueError, match="schema vẫn sai sau 3"):
        extract_intake([], llm, run["run_id"], usage())
    assert len(llm.requests) == 3 and not repo.query("SELECT * FROM trip_profiles")


def test_node_checks_trip_owner_before_reading_messages(run):
    with pytest.raises(ValueError, match="người dùng"):
        intake({**run, "user_id": "u-emma"}, IntakeLLM([]), usage())


def test_pure_route_does_not_mutate_result():
    parsed = IntakeResult.model_validate(payload())
    before = parsed.model_dump()
    route_intake(parsed)
    assert parsed.model_dump() == before


@pytest.mark.parametrize("field", ["start_date", "end_date"])
@pytest.mark.parametrize("detail", [
    "khoảng ngày là 4 ngày, nhưng người dùng nói 2 ngày",
    "date range is 4 days, stated duration is 2 days",
])
def test_duration_conflict_requires_confirmation_of_both_dates(field, detail):
    data = payload()
    data["conflicts"] = [f"{field}: {detail}"]
    parsed = IntakeResult.model_validate(data)
    before = parsed.model_dump()
    result = route_intake(parsed)
    assert result["route"] == "ask_user"
    assert result["profile"].start_date is None and result["profile"].end_date is None
    assert {q["field"] for q in result["questions"]} == {"start_date", "end_date"}
    assert parsed.model_dump() == before


def test_isolated_end_date_conflict_keeps_uncontested_start():
    data = payload()
    data["conflicts"] = ["end_date: người dùng chưa chốt ngày về"]
    result = route_intake(IntakeResult.model_validate(data))
    assert result["profile"].start_date == IntakeResult.model_validate(payload()).profile.start_date
    assert result["profile"].end_date is None
    assert result["profile"].missing_info == ["end_date"]


@pytest.mark.parametrize("language", ["vi", "en"])
def test_explicit_one_day_output_routes_to_plan_without_extending_trip(run, language):
    constraints = ["không leo bậc", "ăn chay"]
    result = extract_intake([], IntakeLLM([payload(
        start_date="2027-02-14", end_date="2027-02-14", language=language,
        hard_constraints=constraints,
    )]), run["run_id"], usage())
    assert result["route"] == "plan" and result["questions"] == []
    assert result["profile"].start_date == result["profile"].end_date
    assert result["profile"].hard_constraints == constraints


def test_missing_end_date_is_not_filled_from_start_date(run):
    llm = IntakeLLM([payload(end_date=None)])
    messages = [{"role": "user", "content": "Khởi hành đi Huế 27/11/2026, chưa chốt ngày về."}]
    result = extract_intake(messages, llm, run["run_id"], usage())
    assert result["route"] == "ask_user" and result["profile"].end_date is None
    assert [q["field"] for q in result["questions"]] == ["end_date"]
    system = llm.requests[0]["messages"][0]["content"]
    assert "start_date=end_date" in system and "departing/starting on D" in system
