"""W9-P1-3: eval runner plug-in. UC có run_case riêng thì runner gọi nó, không thì dùng runner UC-02."""

import os
from pathlib import Path
from types import SimpleNamespace as NS

from agent.db import repo
from evals import run as runner

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_run_case_and_metrics(db, tmp_path, monkeypatch):
    seen = {}

    def run_case(case):
        seen["db"] = os.environ["DB_PATH"]  # runner đã trỏ DB_PATH vào DB riêng của case
        trip_id = repo.create_trip(runner.EVAL_USER)
        run_id = repo.create_run("UC-01", trip_id, runner.EVAL_USER, case["case_id"])
        repo.log_event(run_id, "intake", "error", error="thiếu ngày")
        repo.finish_run(run_id, "succeeded", 10, 5, 0.0, 3)
        return run_id

    def score(case, conn, run_id):
        uc = conn.execute("SELECT uc FROM runs WHERE run_id = ?", (run_id,)).fetchone()[0]
        return {"passed": uc == "UC-01", "reasons": [], "metrics": {"constraint_recall": 0.9}}

    out = tmp_path / "out"
    (out / "db").mkdir(parents=True)
    monkeypatch.setattr(runner, "start_mock", lambda mode: NS(terminate=lambda: None, wait=lambda: None))
    row = runner.run_case({"case_id": "U01"}, Path(os.environ["DB_PATH"]), out, NS(run_case=run_case, score=score))
    assert seen["db"].endswith("U01.db")
    assert row["passed"] and row["metrics"] == {"constraint_recall": 0.9}
    assert (row["status"], row["tokens"], row["rounds"], row["error"]) == ("succeeded", 15, None, "thiếu ngày")


def test_plugins_found_by_folder(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert "uc02" in runner.plugins()
