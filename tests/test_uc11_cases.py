"""Eval UC-11 trên dữ liệu Huế thật (DB tạm) + mock-weather trong tiến trình: không mạng, không LLM, chạy lại ra cùng kết quả.
Mỗi case của evals/uc11/cases.jsonl: scorer.run_case → scorer.score; cả bộ phải đạt ngưỡng docs/uc-11.md mục 12.3."""

import importlib
import json
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

from agent.db import repo
from agent.db.init import init_db
from agent.src.tools import weather
from mocks.mock_weather import app as mock
from scripts import load_destination

scorer = importlib.import_module("evals.uc11.scorer")
LINES = (Path(__file__).resolve().parents[1] / "evals" / "uc11" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
CASES = [json.loads(x) for x in LINES if x.strip()]


def test_case_format():
    """Định dạng đề W9-P4-2: mọi claim cài lỗi có giá trị đúng + nguồn; trộn đủ nhóm lỗi và câu đúng hoàn toàn."""
    assert len(CASES) >= 20 and len({c["case_id"] for c in CASES}) == len(CASES)
    for c in CASES:
        assert {"case_id", "text", "poi_ids", "seeded", "expected"} <= c.keys()
        assert {s["wrong"] for s in c["seeded"]} == {e["span"] for e in c["expected"] if e["status"] != "verified"}
        assert all(s["source"] and "correct" in s for s in c["seeded"])
    groups = {c["group"] for c in CASES}
    assert {"correct", "wrong_hours", "wrong_price", "wrong_distance", "wrong_festival_date", "price_not_in_data"} <= groups
    assert {e["status"] for c in CASES for e in c["expected"]} == {"verified", "unverified", "contradicted"}


def test_uc11_cases(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "uc11.db"))
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.delenv("WEATHER_SECOND_SOURCE", raising=False)
    monkeypatch.delenv("UC11_EXTRACTOR", raising=False)
    init_db()
    monkeypatch.setattr("sys.argv", ["load_destination.py", "hue", "--complete"])
    load_destination.main()

    results = []
    for case in CASES:  # runner bật mock-weather riêng theo weather_mode; ở đây chạy mock trong tiến trình
        monkeypatch.setattr(weather, "_client", lambda m=case["weather_mode"]: TestClient(
            mock.app, base_url="http://localhost:8081", headers={"X-Mock-Mode": m}))  # fmt: skip
        run_id = scorer.run_case(case)
        with closing(repo.get_conn()) as conn:
            results.append((case, scorer.score(case, conn, run_id)))

    assert {c["case_id"]: r["reasons"] for c, r in results if not r["passed"]} == {}
    m = scorer.metrics(results)
    assert m["recall_wrong"] >= 0.85 and m["false_alarm"] <= 0.10
    assert m["leaked"] == 0 and m["abnormal_flagged"] == 1.0


def test_scorer_fails_on_leak_and_wrong_label(db):
    """Scorer phải trượt khi nhãn sai và khi claim contradicted còn trong văn bản cuối."""
    run_id = repo.create_run("UC-11", repo.create_trip("u-ha"), "u-ha")
    repo.query("""INSERT INTO claims (run_id, target_type, target_id, claim_type, claim_text, status, corrected_text)
                  VALUES (?, 'message', 'x', 'price', '150.000đ', 'contradicted', '200.000đ')""", (run_id,))
    repo.log_event(run_id, "verify", "guardrail", name="verify_gate", result={"text": "Vé 150.000đ."})
    case = {"weather_mode": "normal", "expected": [{"span": "150.000đ", "claim_type": "price", "status": "verified"}]}
    with closing(repo.get_conn()) as conn:
        res = scorer.score(case, conn, run_id)
    assert not res["passed"] and res["leaked"] == ["150.000đ"] and len(res["reasons"]) == 2
