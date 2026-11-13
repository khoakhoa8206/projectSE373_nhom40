"""Kiểm evaluator/transport giả, không phải số đo trích xuất LLM thật."""

import json
from contextlib import closing
from pathlib import Path

import pytest

from agent.db import repo
from agent.schemas import TripProfile
from evals.uc01 import scorer
from evals.uc01.report import summarize

CASES = [json.loads(line) for line in (Path(__file__).resolve().parents[1] / "evals/uc01/cases.jsonl")
         .read_text(encoding="utf-8").splitlines() if line.strip()]


def test_case_coverage_and_original_source_are_preserved():
    assert len(CASES) >= 21
    assert len({case["case_id"] for case in CASES}) == len(CASES)
    assert {case.get("source_request_id") for case in CASES if "source_request_id" in case} == {
        f"R{index:02d}" for index in range(1, 16)}
    assert sum(len(case.get("turns", [])) > 1 for case in CASES) >= 2


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_cases_expand_to_valid_gold_and_user_turns(case):
    expanded = scorer.expand_case(case)
    TripProfile.model_validate(expanded["gold_profile"])
    assert expanded["turns"] and all(isinstance(turn, str) for turn in expanded["turns"])
    assert set(expanded["checked_fields"]) <= set(TripProfile.model_fields)


def record(run, profile, questions=None, conflicts=None):
    result = {"profile": profile.model_dump(mode="json"), "route": profile.route,
              "questions": questions or [], "conflicts": conflicts or [], "message": ""}
    repo.log_event(run, "intake", "guardrail", name="intake_result", result=result)


@pytest.fixture
def evaluation(db):
    trip = repo.create_trip("u-ha")
    run = repo.create_run("UC-01", trip, "u-ha", "test")
    repo.finish_run(run, "succeeded", 0, 0, 0.0, 0)
    case = {"case_id": "test", "turns": ["Huế 28/11/2026, 1 người, 1 triệu"],
            "gold_profile": {"start_date": "2026-11-28", "end_date": "2026-11-28", "adults": 1,
                             "budget_total_vnd": 1000000, "route": "plan"},
            "checked_fields": ["route", "start_date", "adults", "budget_total_vnd"]}
    return run, case


def test_scorer_is_select_only_and_counts_hard_fields(evaluation):
    run, case = evaluation
    record(run, TripProfile.model_validate(case["gold_profile"]))
    with closing(repo.get_conn()) as conn:
        conn.execute("PRAGMA query_only=ON")
        result = scorer.score(case, conn, run)
    assert result["passed"]
    assert result["metrics"]["schema_valid"]
    assert result["metrics"]["hard_correct"] == result["metrics"]["hard_total"] == 3


def test_wrong_field_is_not_reported_as_success(evaluation):
    run, case = evaluation
    record(run, TripProfile.model_validate({**case["gold_profile"], "adults": 4}))
    with closing(repo.get_conn()) as conn:
        result = scorer.score(case, conn, run)
    assert not result["passed"] and "Sai trường adults" in result["reasons"]


def test_missing_output_failed_run_and_conflict_are_not_hidden(evaluation):
    run, case = evaluation
    case["expect"] = {"conflict": "test"}
    repo.finish_run(run, "failed", 0, 0, 0.0, 0)
    with closing(repo.get_conn()) as conn:
        result = scorer.score(case, conn, run)
    assert not result["passed"]
    assert not result["metrics"]["schema_valid"] and not result["metrics"]["conflict_detected"]


def test_multiturn_transport_never_passes_gold_to_intake(db, monkeypatch):
    seen = []
    case = next(case for case in CASES if case["case_id"] == "I22")
    monkeypatch.setattr(scorer, "make_client", object)

    def fake_intake(state, client, usage):
        messages = repo.query("SELECT role, content FROM messages WHERE trip_id=? ORDER BY rowid", (state["trip_id"],))
        seen.append(messages)
        first = len(seen) == 1
        profile = TripProfile(start_date="2026-11-27", end_date="2026-11-28", adults=None if first else 2,
                              budget_total_vnd=4000000, route="ask_user" if first else "plan")
        questions = [{"field": "adults", "text": "Có bao nhiêu người lớn?"}] if first else []
        record(state["run_id"], profile, questions)
        return {"profile": profile, "route": profile.route, "questions": questions, "conflicts": []}

    monkeypatch.setattr(scorer, "intake", fake_intake)
    run = scorer.run_case(case)
    assert len(seen) == 2
    assert [message["content"] for message in seen[-1] if message["role"] == "user"] == case["turns"]
    assert all("gold_profile" not in message["content"] for message in seen[-1])
    with closing(repo.get_conn()) as conn:
        assert scorer.score(case, conn, run)["passed"]


def test_report_uses_weighted_fields_and_keeps_missing_metrics_visible():
    report = summarize([{"passed": True, "metrics": {"schema_valid": True, "hard_correct": 1, "hard_total": 1}},
                        {"passed": False, "metrics": {"schema_valid": True, "hard_correct": 0, "hard_total": 9}},
                        {"passed": False}])
    assert report["hard_accuracy_pct"] == 10
    assert report["cases_missing_metrics"] == 1
    assert report["conflict_detection_pct"] is None
