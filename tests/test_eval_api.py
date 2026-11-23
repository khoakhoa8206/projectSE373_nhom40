"""GET /api/evals: đọc results/run*/<uc>/cases.jsonl cho trang Eval (dashboard run1 so với run2)."""

import json

from fastapi.testclient import TestClient

from agent.src.api import server


def test_eval_results_groups_by_run_and_uc(tmp_path, monkeypatch):
    rows = [
        {"case_id": "A", "passed": True, "tokens": 100, "cost": 0.01, "latency_ms": 1000, "metrics": {"recall_at_5": 1.0, "ok": True}},
        {"case_id": "B", "passed": False, "tokens": 300, "cost": 0.03, "latency_ms": 3000, "metrics": {"recall_at_5": 0.5, "ok": False}},
        {"case_id": "C", "passed": False, "reasons": ["runner: lỗi"]},  # case lỗi runner: không có token/metrics
    ]  # fmt: skip
    uc = tmp_path / "run1" / "uc03"
    uc.mkdir(parents=True)
    (uc / "cases.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "uc02-20261028-220526").mkdir()  # run không tên: không hiện trên dashboard
    monkeypatch.setattr(server, "RESULTS", tmp_path)

    got = TestClient(server.app).get("/api/evals").json()
    assert list(got) == ["run1"]
    s = got["run1"]["uc03"]
    assert (s["cases"], s["passed"], s["tokens"], s["latency_ms"]) == (3, 1, 200, 2000)
    assert abs(s["pass_rate"] - 1 / 3) < 1e-9 and abs(s["cost_usd"] - 0.04) < 1e-9
    assert s["metrics"] == {"ok": 0.5, "recall_at_5": 0.75}
