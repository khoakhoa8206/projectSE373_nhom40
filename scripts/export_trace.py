"""Xuất 1 trace làm mẫu để commit: python scripts/export_trace.py <run_id> --uc UC-11
Tìm <run_id>.jsonl trong .runtime/traces/ (app chạy bằng run.py), traces/, results/**/traces/ (eval); không có thì
đọc bảng trace_events trong DB_PATH (mặc định .runtime/tourguide.db). Che toạ độ lại lần nữa (mask_coords) rồi ghi
traces/samples/uc-11/<run_id>.jsonl."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.src.obs.trace import mask_coords

ROOTS = (".runtime/traces", "traces", "results")


def load_events(run_id, roots=ROOTS):
    for root in roots:
        for f in sorted(Path(root).glob(f"**/{run_id}.jsonl")):
            if "samples" not in f.parts:
                return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    db = os.environ.setdefault("DB_PATH", ".runtime/tourguide.db")
    if not Path(db).exists():  # sqlite3.connect sẽ tạo file rỗng nếu chưa có
        return []
    from agent.db import repo

    rows = repo.query("SELECT * FROM trace_events WHERE run_id = ? ORDER BY seq", (run_id,))
    return [r | {k: json.loads(r[k]) if r.get(k) else r.get(k) for k in ("args", "result")} for r in rows]


def export(run_id, uc, out_root="traces/samples", roots=ROOTS):
    events = load_events(run_id, roots)
    if not events:
        sys.exit(f"Không tìm thấy trace của {run_id} ({', '.join(roots)}, trace_events trong {os.environ['DB_PATH']})")
    out = Path(out_root) / uc.lower() / f"{run_id}.jsonl"  # UC-11 -> uc-11
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(mask_coords(e), ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    return out, len(events)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252, không in được tiếng Việt
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--uc", required=True, help="vd UC-11")
    a = ap.parse_args()
    path, n = export(a.run_id, a.uc)
    print(f"{n} sự kiện -> {path}")
