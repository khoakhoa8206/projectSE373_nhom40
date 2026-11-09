"""Tổng hợp metric từ kết quả thật đã có, không gọi provider hoặc tạo số đo giả."""

import argparse
import json
from pathlib import Path


def summarize(rows):
    metrics = [row.get("metrics", {}) for row in rows]
    total_hard = sum(m.get("hard_total", 0) for m in metrics)
    conflicts = [m for m in metrics if m.get("conflict_expected")]
    unsupported = [m for m in metrics if m.get("unsupported_expected")]
    return {
        "cases": len(rows), "passed": sum(bool(row.get("passed")) for row in rows),
        "schema_valid_pct": 100 * sum(bool(m.get("schema_valid")) for m in metrics) / len(rows) if rows else None,
        "hard_accuracy_pct": 100 * sum(m.get("hard_correct", 0) for m in metrics) / total_hard if total_hard else None,
        "conflict_detection_pct": 100 * sum(bool(m.get("conflict_detected")) for m in conflicts) / len(conflicts)
        if conflicts else None,
        "unsupported_accuracy_pct": 100 * sum(bool(m.get("unsupported_correct")) for m in unsupported) / len(unsupported)
        if unsupported else None,
        "cases_missing_metrics": sum(not m for m in metrics),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path, help="results/uc01-.../cases.jsonl")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
