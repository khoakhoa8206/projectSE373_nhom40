"""Dashboard vận hành (5 chỉ số Buổi 11) dạng bảng markdown, để dán vào báo cáo / commit cạnh kết quả eval.
  python scripts/dashboard.py                          # DB của app (DB_PATH, mặc định .runtime/tourguide.db)
  python scripts/dashboard.py results/run1 --md results/run1/dashboard.md   # gộp mọi DB case của lượt eval
Đọc mọi người dùng (chỉ dùng trên máy nhóm); API GET /api/dashboard thì chỉ trả lượt chạy của người đang đăng nhập."""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.src.obs.dashboard import dashboard


def fmt(x, digits=0):
    return "–" if x is None else f"{x:,.{digits}f}"


def to_markdown(d, title):
    rows = [("Tổng", d["total"])] + list(d["by_uc"].items())
    out = [f"## Dashboard vận hành · {title}", "",
           "| UC | Lượt | Thành công | Lỗi | Chờ người dùng | Tỷ lệ thành công | Token TB/lượt | Token max | Chi phí USD | p95 (s) |",
           "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for name, s in rows:
        rate = "–" if s["success_rate"] is None else f"{s['success_rate']:.0%}"
        p95 = None if s["latency_p95_ms"] is None else s["latency_p95_ms"] / 1000
        out.append(
            f"| {name} | {s['runs']} | {s['succeeded']} | {s['failed']} | {s['interrupted']} | {rate} | "
            f"{fmt(s['avg_tokens'])} | {fmt(s['max_tokens'])} | {fmt(s['cost_usd'], 4)} | {fmt(p95, 1)} |"
        )
    out += ["", "**Tool lỗi nhiều nhất**", "", "| Tool | Lượt gọi | Lỗi | Tỷ lệ lỗi |", "|---|---|---|---|"]
    out += [f"| {t['name']} | {t['calls']} | {t['errors']} | {t['error_rate']:.0%} |" for t in d["tools"]]
    out += ["", f"**Lớp kiểm soát** · đang chờ duyệt: {d['approvals']['pending']}", ""]
    out += [f"- duyệt `{k}`: {v}" for k, v in d["approvals"]["by_kind"].items()]
    out += [f"- guardrail `{k}`: {v}" for k, v in d["guardrails"].items()]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="file .db hoặc thư mục (lấy mọi *.db bên trong)")
    ap.add_argument("--md", help="ghi bảng ra file markdown")
    args = ap.parse_args()
    paths = args.paths or [os.environ.get("DB_PATH", ".runtime/tourguide.db")]
    dbs = [f for p in map(Path, paths) for f in (sorted(p.rglob("*.db")) if p.is_dir() else [p])
           if f.exists() and f.name != "_template.db"]  # fmt: skip
    if not dbs:
        sys.exit(f"Không tìm thấy DB trong {', '.join(paths)}")
    conns = [sqlite3.connect(f) for f in dbs]
    try:
        text = to_markdown(dashboard(conns), f"{', '.join(paths)} ({len(dbs)} DB)")
    finally:
        for c in conns:
            c.close()
    if args.md:
        Path(args.md).write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
