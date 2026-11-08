"""Chạy eval UC-03 cục bộ theo đúng hợp đồng plug-in (run_case + score), dùng khi evals/run.py của lead chưa hỗ trợ
`--uc UC-03`. Cần model embedding thật và LLM_API_KEY trong .env:
    python -m evals.uc03.run_local                         # cả 44 case
    python -m evals.uc03.run_local --only uc03-qa-01,uc03-qa-17 --write-readme
OpenRouter free chỉ 50 request/ngày/key, mỗi case tốn 1–2 request. Hết hạn mức giữa chừng (2 case liên tiếp lỗi 429) thì
runner tự dừng; khi có hạn mức lại (hôm sau hoặc key khác) chạy tiếp case còn thiếu/lỗi, kết quả được gộp:
    python -m evals.uc03.run_local --resume results/uc03-<thời điểm> --write-readme
Mỗi case chạy trên DB mới (schema + POI Huế); kết quả ở results/uc03-<thời điểm>/."""

import argparse
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from agent.db import repo
from agent.db.init import init_db
from evals.uc03 import scorer

HERE = Path(__file__).resolve().parent
README = HERE / "README.md"
START, END = "<!-- eval:start -->", "<!-- eval:end -->"
METRICS = ("recall_at_5", "citations_valid", "language_ok", "out_of_kb_ok", "injection_ok", "keyword_hit")
QUOTA_STREAK = 2  # số case liên tiếp lỗi 429 thì dừng: hết hạn mức request/ngày, chạy tiếp bằng --resume


def mean(values):
    values = [float(v) for v in values if v is not None]
    return round(statistics.fmean(values), 4) if values else None


def summarize(rows) -> dict:
    """Trung bình từng metric trên các case có metric đó (None = không áp dụng) + tỉ lệ pass."""
    return {"cases": len(rows), "passed": sum(r["passed"] for r in rows),
            "pass_rate": mean(r["passed"] for r in rows),
            **{m: mean(r["metrics"].get(m) for r in rows) for m in METRICS},
            "tokens": sum(r.get("tokens") or 0 for r in rows),
            "latency_p50_ms": statistics.median([r["latency_ms"] for r in rows if r.get("latency_ms")] or [0])}


def readme_block(summary, rows, measured_at, total=None) -> str:
    fails = [f"- `{r['case_id']}`: {'; '.join(r['reasons'])}" for r in rows if not r["passed"]] or ["- (không có)"]
    metrics = ", ".join(f"{m} = {summary[m]}" for m in METRICS)
    partial = f", mới chạy {summary['cases']}/{total} case" if total and total != summary["cases"] else ""
    head = (f"Chạy lúc {measured_at}: {summary['passed']}/{summary['cases']} case pass "
            f"(pass_rate = {summary['pass_rate']}{partial}).")
    models = Counter(m for r in rows for m in r.get("models") or [])
    used = ", ".join(f"`{m}` ({n} case)" for m, n in models.most_common()) or "(không có lời gọi LLM)"
    cost = f"- Tổng token: {summary['tokens']}, độ trễ p50: {summary['latency_p50_ms']} ms; model trả lời: {used}"
    return "\n".join([START, head, "", f"- {metrics}", cost, "", "Case chưa đạt:", "", *fails, END])


def load_previous(folder) -> dict:
    """Case đã chạy xong ở lần trước (run `succeeded`), theo case_id. Case lỗi (429, timeout…) sẽ được chạy lại."""
    lines = (Path(folder) / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    return {r["case_id"]: r for r in map(json.loads, filter(None, lines)) if r.get("status") == "succeeded"}


def quota_error(row) -> bool:
    """Lỗi do hết hạn mức request (HTTP 429), không phải kết quả của agent: không tính vào số đo, chạy lại sau."""
    text = f"{row.get('error') or ''} {' '.join(row.get('reasons', []))}"
    return "429" in text or "RateLimit" in text


def run_one(case, template, out) -> dict:
    db = out / "db" / f"{case['case_id']}.db"
    shutil.copy(template, db)
    os.environ["DB_PATH"] = str(db)
    try:
        run_id = scorer.run_case(case)
        with closing(repo.get_conn()) as conn:
            result = scorer.score(case, conn, run_id)
        run = repo.query("SELECT status, tokens_in + tokens_out AS tokens, latency_ms FROM runs WHERE run_id = ?",
                         (run_id,))[0]  # fmt: skip
        error = repo.query("SELECT error FROM trace_events WHERE run_id = ? AND kind = 'error' ORDER BY seq LIMIT 1",
                           (run_id,))  # fmt: skip
        models = repo.query("SELECT DISTINCT name FROM trace_events WHERE run_id = ? AND kind = 'llm_call'", (run_id,))
        return {"case_id": case["case_id"], "run_id": run_id, **result, **run,
                "error": error[0]["error"] if error else None,
                "models": sorted(m["name"] for m in models if m["name"])}  # fmt: skip
    except Exception as e:  # noqa: BLE001 — 1 case lỗi không dừng cả bộ eval
        return {"case_id": case["case_id"], "passed": False, "reasons": [f"runner: {type(e).__name__}: {e}"],
                "status": "error", "error": f"{type(e).__name__}: {e}",
                "metrics": {"recall_at_5": 0.0 if case["gold"] else None}}  # fmt: skip


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Eval UC-03 cục bộ (plug-in run_case + score)")
    ap.add_argument("--only", help="danh sách case_id, cách nhau dấu phẩy")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", metavar="DIR", help="thư mục results/uc03-… của lần trước: giữ case đã chạy xong, "
                    "chỉ chạy case còn thiếu hoặc lỗi, rồi gộp kết quả")  # fmt: skip
    ap.add_argument("--write-readme", action="store_true", help="ghi kết quả vào evals/uc03/README.md")
    args = ap.parse_args()
    all_cases = [json.loads(line) for line in (HERE / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
    done = load_previous(args.resume) if args.resume else {}
    cases = [c for c in all_cases if c["case_id"] not in done]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["case_id"] in wanted]
    cases = cases[: args.limit] if args.limit else cases
    if args.resume:
        print(f"Giữ {len(done)} case đã chạy xong ở {args.resume}; chạy {len(cases)} case.", flush=True)

    out = Path("results") / f"uc03-{datetime.now():%Y%m%d-%H%M%S}"
    (out / "db").mkdir(parents=True)
    os.environ["TRACE_DIR"] = str(out / "traces")
    template = init_db(out / "db" / "_template.db")
    subprocess.run([sys.executable, "scripts/load_destination.py", "hue"], env=os.environ | {"DB_PATH": str(template)},
                   check=True)  # fmt: skip
    new, streak = [], 0
    for case in cases:
        row = run_one(case, template, out)
        new.append(row)
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['case_id']}  {'; '.join(row['reasons'])}", flush=True)
        streak = streak + 1 if quota_error(row) else 0
        if streak >= QUOTA_STREAK:
            print(f"\n{QUOTA_STREAK} case liên tiếp lỗi 429 (hết hạn mức request?): dừng. Khi có hạn mức lại, "
                  f"chạy tiếp:\n    python -m evals.uc03.run_local --resume {out} --write-readme", flush=True)
            break

    order = {c["case_id"]: i for i, c in enumerate(all_cases)}
    rows = sorted([*done.values(), *new], key=lambda r: order.get(r["case_id"], len(order)))
    with open(out / "cases.jsonl", "w", encoding="utf-8") as f:  # gồm cả case lỗi 429 để --resume biết chạy lại
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    scored = [r for r in rows if not quota_error(r)]
    summary = summarize(scored)
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "passed", *METRICS, "reasons"])
        writer.writerows([r["case_id"], r["passed"], *(r["metrics"].get(m) for m in METRICS), "; ".join(r["reasons"])]
                         for r in scored)  # fmt: skip
    block = readme_block(summary, scored, datetime.now().strftime("%Y-%m-%d %H:%M"), total=len(all_cases))
    skipped = len(rows) - len(scored)
    note = f"\n{skipped} case lỗi 429 chưa tính vào số đo; chạy lại bằng --resume {out}" if skipped else ""
    print("\n" + block.replace(START, "").replace(END, "").strip() + f"\n\nChi tiết: {out}{note}")
    if args.write_readme:
        text = README.read_text(encoding="utf-8")
        head, start, rest = text.partition(START)
        if not start:
            raise SystemExit(f"{README} thiếu dấu {START} … {END}")
        README.write_text(head + block + rest.partition(END)[2], encoding="utf-8")


if __name__ == "__main__":
    main()
