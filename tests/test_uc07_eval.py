"""Eval UC-07 chạy qua runner thật (DB riêng mỗi case, không LLM): 7/7 case pass, 0 rò rỉ chéo user."""

import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

from evals import run as runner
from evals.uc07 import scorer

CASES = Path(__file__).resolve().parents[1] / "evals" / "uc07" / "cases.jsonl"


def test_uc07_eval_cases_all_pass(db, tmp_path, monkeypatch):
    from agent.db import repo

    repo.query("UPDATE destinations SET name_vi = 'Huế' WHERE destination_id = 'hue'")
    monkeypatch.setattr(runner, "start_mock", lambda mode: NS(terminate=lambda: None, wait=lambda: None))
    (tmp_path / "out" / "db").mkdir(parents=True)
    template = Path(os.environ["DB_PATH"])
    rows = [runner.run_case(json.loads(line), template, tmp_path / "out", scorer) for line in CASES.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 5
    assert [r["case_id"] for r in rows if not r["passed"]] == [], [r["reasons"] for r in rows]
    assert sum(r["metrics"]["leak"] for r in rows) == 0
    assert next(r for r in rows if r["case_id"] == "M03")["metrics"]["recall"] == 1
