"""Plug-in UC-01: gold chỉ ở evaluator, tuyệt đối không truyền vào node/LLM."""

import json
import time
import unicodedata
from pathlib import Path

from agent.db import repo
from agent.schemas import TripProfile
from agent.src.graph.loop import make_client, ms
from agent.src.nodes.intake import intake

ROOT = Path(__file__).resolve().parents[1]
HARD_FIELDS = {"start_date", "end_date", "adults", "children", "budget_total_vnd", "hard_constraints",
               "mobility_notes", "pace", "budget_includes"}


def expand_case(case):
    if "source_request_id" not in case:
        return case
    sources = [json.loads(line) for line in (ROOT / "trip_requests.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    source = next(item for item in sources if item["request_id"] == case["source_request_id"])
    return {**source, "turns": [source["text"]], **case}


def run_case(case) -> str:
    """Adapter node nhiều lượt khi API/resume P1 chưa có; không phải benchmark persistence."""
    case = expand_case(case)
    trip = repo.create_trip("u-ha")
    run = repo.create_run("UC-01", trip, "u-ha", case["case_id"])
    usage, started = {"in": 0, "out": 0, "cost": 0.0}, time.perf_counter()
    try:
        client = make_client()
        for index, text in enumerate(case["turns"]):
            repo.add_message(trip, "u-ha", "user", text, run_id=run)
            result = intake({"trip_id": trip, "user_id": "u-ha", "run_id": run}, client, usage)
            if result["route"] != "ask_user":
                if index != len(case["turns"]) - 1:
                    raise ValueError("Intake dừng trước câu trả lời được chuẩn bị; không bỏ qua turn để làm đẹp điểm.")
                break
            repo.add_message(trip, "u-ha", "assistant", json.dumps(
                {"questions": result["questions"], "conflicts": result["conflicts"]}, ensure_ascii=False), run_id=run)
    except Exception as error:  # noqa: BLE001 — giữ lỗi thật của từng case trong trace
        repo.log_event(run, "intake", "error", error=f"{type(error).__name__}: {error}")
        repo.finish_run(run, "failed", usage["in"], usage["out"], usage["cost"], ms(started))
    else:
        repo.finish_run(run, "succeeded", usage["in"], usage["out"], usage["cost"], ms(started))
    return run


def _canonical(value):
    if isinstance(value, str):
        return " ".join(unicodedata.normalize("NFC", value).casefold().split())
    if isinstance(value, list):
        return sorted((_canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    return value


def score(case, conn, run_id) -> dict:
    """Chỉ SELECT; so field chuẩn hoá, không dùng LLM chấm hoặc sửa gold."""
    case = expand_case(case)
    rows = conn.execute(
        "SELECT result FROM trace_events WHERE run_id=? AND name='intake_result' ORDER BY seq", (run_id,),
    ).fetchall()
    run = conn.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
    reasons, results, schemas = [], [], []
    for row in rows:
        try:
            result = json.loads(row[0])
            TripProfile.model_validate(result["profile"])
            assert result["route"] == result["profile"]["route"]
            assert len(result["questions"]) <= 3
            assert all(q.get("field") and q.get("text") for q in result["questions"])
            results.append(result)
            schemas.append(True)
        except (ValueError, KeyError, TypeError, AssertionError):
            schemas.append(False)
    schema_ok = bool(schemas) and all(schemas) and len(results) == len(case["turns"])
    if not schema_ok:
        reasons.append("Thiếu turn hoặc output/questions không hợp schema")
    if run is None or run[0] != "succeeded":
        reasons.append("Run không succeeded")
    final = results[-1] if results else {"profile": {}, "questions": [], "route": None, "conflicts": []}
    gold = TripProfile.model_validate(case["gold_profile"]).model_dump(mode="json")
    fields = case["checked_fields"]
    matched = {field: schema_ok and _canonical(final["profile"].get(field)) == _canonical(gold.get(field))
               for field in fields}
    reasons.extend(f"Sai trường {field}" for field, ok in matched.items() if not ok)
    expect = case.get("expect", {})
    asked = {question["field"] for question in final["questions"]}
    if not set(expect.get("must_ask", [])) <= asked:
        reasons.append("Không hỏi đủ field được yêu cầu")
    conflict = final["route"] == "ask_user" and bool(final["conflicts"])
    if expect.get("conflict") and not conflict:
        reasons.append("Không phát hiện mâu thuẫn")
    if expect.get("first_route") and (not results or results[0]["route"] != expect["first_route"]):
        reasons.append("Sai route lượt đầu")
    if expect.get("first_conflict") and (not results or not results[0]["conflicts"]):
        reasons.append("Không phát hiện mâu thuẫn lượt đầu")
    first_asked = {q["field"] for q in results[0]["questions"]} if results else set()
    if not set(expect.get("first_must_ask", [])) <= first_asked:
        reasons.append("Lượt đầu không hỏi đúng field")
    hard = [ok for field, ok in matched.items() if field in HARD_FIELDS]
    return {"passed": not reasons, "reasons": reasons, "metrics": {
        "schema_valid": schema_ok, "hard_correct": sum(hard), "hard_total": len(hard),
        "hard_accuracy": sum(hard) / len(hard) if hard else None,
        "conflict_expected": bool(expect.get("conflict") or expect.get("first_conflict")),
        "conflict_detected": conflict or bool(results and results[0]["conflicts"]),
        "unsupported_expected": gold["route"] == "unsupported",
        "unsupported_correct": final["route"] == gold["route"] if gold["route"] == "unsupported" else None,
    }}
