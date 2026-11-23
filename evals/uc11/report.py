"""Tổng hợp chỉ số UC-11 từ kết quả của runner (W10-P4-2), không chạy lại gì:

    python -m evals.uc11.report results/uc11-<thời gian>      # hoặc results/all-<thời gian>/uc11

Đọc <thư mục>/cases.jsonl (mỗi dòng có "metrics" do scorer.score ghi), in bảng Markdown để dán vào README và ghi
<thư mục>/metrics.json. Ngưỡng của đề: recall ≥ 85 %, báo nhầm ≤ 10 %, 0 lọt, thời tiết bất thường 100 %."""

import json
import sys
from pathlib import Path

from evals.uc11.scorer import summarize

TARGETS = {"recall_wrong": (">=", 0.85), "false_alarm": ("<=", 0.10), "leaked": ("<=", 0), "abnormal_flagged": (">=", 1.0)}


def pct(x):
    return "—" if x is None else f"{x:.0%}"


def table(m: dict) -> str:
    def mark(k):
        op, limit = TARGETS[k]
        ok = m[k] is not None and (m[k] >= limit if op == ">=" else m[k] <= limit)
        return "đạt" if ok else "**chưa đạt**"

    cost = "—" if m["avg_cost_usd"] is None else f"{m['avg_cost_usd']:.6f}"
    tokens = "—" if m["avg_tokens_in"] is None else f"{m['avg_tokens_in']:.0f} vào / {m['avg_tokens_out']:.0f} ra"
    latency = "—" if m["avg_latency_ms"] is None else f"{m['avg_latency_ms']:.0f} ms"
    rows = [
        ("Tách claim", m["extractor"], ""),
        ("Case pass", f"{m['cases_passed']}/{m['cases']}", ""),
        ("Phát hiện claim sai (recall)", pct(m["recall_wrong"]), f"≥ 85 % · {mark('recall_wrong')}"),
        ("Báo nhầm", pct(m["false_alarm"]), f"≤ 10 % · {mark('false_alarm')}"),
        ("Claim sai lọt ra văn bản cuối", str(m["leaked"]), f"0 · {mark('leaked')}"),
        ("Thời tiết bất thường bị đánh dấu", pct(m["abnormal_flagged"]), f"100 % · {mark('abnormal_flagged')}"),
        ("Token verifier / câu trả lời", tokens, ""),
        ("Chi phí verifier / câu trả lời (USD)", cost, f"tổng {m['total_cost_usd']:.6f}"),
        ("Độ trễ verifier / câu trả lời", latency, ""),
    ]
    return "\n".join(["| Chỉ số | Kết quả | Ngưỡng |", "|---|---|---|", *(f"| {a} | {b} | {c} |" for a, b, c in rows)])


def main(folder: str):
    path = Path(folder)
    rows = [json.loads(line) for line in (path / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    m = summarize([r.get("metrics") or {"passed": False} for r in rows])
    (path / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(table(m))
    return m


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1])
