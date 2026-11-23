"""W10-P4-2: eval UC-11 ghi token + chi phí + độ trễ của verifier cho mỗi câu trả lời, và tổng hợp lại được từ kết quả của
runner. LLM giả (không key, không mạng); dữ liệu giá là dữ liệu TEST của fixture `db`."""

import importlib
import json
from contextlib import closing

from agent.db import repo
from agent.src.nodes import verify
from agent.src.nodes.verify import LlmClaims

scorer = importlib.import_module("evals.uc11.scorer")
report = importlib.import_module("evals.uc11.report")

CASE = {"case_id": "uc11-001", "group": "correct", "lang": "vi", "target_type": "message", "weather_mode": "normal",
        "context": {"destination_id": "hue", "trip_dates": ["2026-11-25", "2026-11-27"]},
        "text": "Vé vào Đại Nội cho người lớn là 200.000đ.", "poi_ids": ["hue-dai-noi"], "seeded": [],
        "expected": [{"claim_type": "price", "status": "verified", "span": "200.000đ"}]}  # fmt: skip


def test_llm_tokens_and_cost_recorded_per_answer(db, monkeypatch):
    repo.query("UPDATE pois SET ticket_price_vnd = 200000 WHERE poi_id = 'hue-dai-noi'")
    monkeypatch.setenv("UC11_EXTRACTOR", "llm")

    def loop(client, system, user, tools, output, run_id, node, usage, max_turns):
        usage["in"] += 900  # như agent_loop thật: cộng dồn vào usage của lượt chạy
        usage["out"] += 60
        usage["cost"] += 0.00012
        return LlmClaims(claims=[])  # LLM không tách được gì: lưới regex vẫn bắt "200.000đ"

    monkeypatch.setattr(verify, "agent_loop", loop)
    monkeypatch.setattr(verify, "make_client", lambda: None)
    run_id = scorer.run_case(CASE)
    run = repo.query("SELECT status, tokens_in, tokens_out, cost_usd, latency_ms FROM runs WHERE run_id = ?", (run_id,))[0]
    assert (run["status"], run["tokens_in"], run["tokens_out"], run["cost_usd"]) == ("succeeded", 900, 60, 0.00012)
    assert run["latency_ms"] is not None
    with closing(repo.get_conn()) as conn:
        res = scorer.score(CASE, conn, run_id)
    assert res["passed"]
    assert res["metrics"] | {"latency_ms": 0} == {
        "claims": 1, "leaked": 0, "passed": True, "abnormal_ok": None, "extractor": "llm", "wrong": 0, "wrong_caught": 0,
        "right": 1, "false_alarm": 0, "tokens_in": 900, "tokens_out": 60, "cost_usd": 0.00012, "latency_ms": 0}  # fmt: skip


def test_report_from_runner_results(tmp_path):
    """report đọc đúng cases.jsonl mà runner ghi (mỗi dòng có metrics), không chạy lại gì."""
    one = {"leaked": 0, "abnormal_ok": None, "extractor": "llm", "tokens_in": 1000, "tokens_out": 50, "cost_usd": 0.0002,
           "latency_ms": 1500}  # fmt: skip
    rows = [
        {"case_id": "a", "passed": True, "metrics": one | {"passed": True, "wrong": 2, "wrong_caught": 2, "right": 1, "false_alarm": 0}},
        {"case_id": "b", "passed": True, "metrics": one | {"passed": True, "wrong": 0, "wrong_caught": 0, "right": 3, "false_alarm": 0,
                                                           "abnormal_ok": True, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                                                           "latency_ms": 500}},
        {"case_id": "c", "passed": False, "reasons": ["runner: lỗi"]},  # case lỗi ở runner: không có metrics
    ]  # fmt: skip
    (tmp_path / "cases.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    m = report.main(str(tmp_path))
    assert (m["recall_wrong"], m["false_alarm"], m["leaked"], m["abnormal_flagged"]) == (1.0, 0.0, 0, 1.0)
    assert (m["cases_passed"], m["cases"], m["avg_tokens_in"], m["total_cost_usd"]) == (2, 3, 1000 / 3, 0.0002)
    assert m["avg_latency_ms"] == 1000 and json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8")) == m
    assert "| Phát hiện claim sai (recall) | 100% | ≥ 85 % · đạt |" in report.table(m)
