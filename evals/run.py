"""Eval runner: python -m evals.run --uc UC-02 [--uc UC-03 ...] | python -m evals.run --all

Plug-in (W9-P1-3): mỗi UC là 1 thư mục evals/<uc>/ (vd evals/uc01/) có
    cases.jsonl   mỗi dòng 1 case, bắt buộc case_id; tuỳ chọn weather_mode (mặc định normal), fixture (.sql hư cấu)
    scorer.py     score(case, conn, run_id) -> {"passed": bool, "reasons": [str], "metrics"?: {...}}   (chỉ đọc DB)
                  run_case(case) -> run_id   tuỳ chọn; không có thì dùng runner UC-02 (profile của case → graph UC-02)
Mỗi case: DB mới (schema + dữ liệu Huế + fixture nếu có) đặt vào DB_PATH · mock-weather bật riêng theo weather_mode ·
run_case chạy graph (runs.eval_case_id = case_id) · score chấm.
Kết quả: results/<eval_run_id>/ gồm cases.jsonl, summary.csv, traces/, db/<case_id>.db; nhiều UC thì mỗi UC 1 thư mục con."""

import argparse
import csv
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from agent.db import repo
from agent.db.init import init_db
from agent.schemas import TripProfile
from agent.src.graph.app import run_uc02

MOCK_PORT = 8081
EVAL_USER = "u-ha"  # người dùng hư cấu có sẵn sau init_db


def port_open(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_mock(mode):
    """Bật mock-weather cho 1 case; chế độ bơm lỗi truyền qua biến môi trường MOCK_WEATHER_MODE."""
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "mocks.mock_weather.app:app", "--port", str(MOCK_PORT)],
        env=os.environ | {"MOCK_WEATHER_MODE": mode},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        if port_open(MOCK_PORT):
            return p
        if p.poll() is not None:
            break
        time.sleep(0.1)
    p.kill()
    raise RuntimeError("mock-weather không khởi động được")


def run_uc02_case(case):
    """Runner mặc định (UC-02): hồ sơ của case → graph UC-02, không dừng ở bước người dùng duyệt."""
    trip_id = repo.create_trip(EVAL_USER)
    repo.save_profile(trip_id, TripProfile.model_validate(case["profile"]))
    return run_uc02(trip_id, EVAL_USER, eval_case_id=case["case_id"])["run_id"]


def run_case(case, template, out, scorer):
    db = out / "db" / f"{case['case_id']}.db"
    shutil.copy(template, db)
    os.environ["DB_PATH"] = str(db)
    if case.get("fixture"):  # dữ liệu hư cấu riêng của case, vd evals/fixtures/closed_monday.sql
        with closing(repo.get_conn()) as conn:
            conn.executescript(Path(case["fixture"]).read_text(encoding="utf-8"))

    mock = start_mock(case.get("weather_mode", "normal"))
    try:
        run_id = getattr(scorer, "run_case", run_uc02_case)(case)
        with closing(repo.get_conn()) as conn:
            score = scorer.score(case, conn, run_id)
    finally:
        mock.terminate()
        mock.wait()

    run = repo.query(
        "SELECT run_id, status, tokens_in + tokens_out AS tokens, cost_usd AS cost, latency_ms FROM runs WHERE run_id = ?",
        (run_id,),
    )[0]
    it = repo.query("SELECT itinerary_id, status, planner_rounds FROM itineraries WHERE run_id = ?"
                    " ORDER BY version DESC LIMIT 1", (run_id,))  # fmt: skip
    errors = repo.query("SELECT error FROM trace_events WHERE run_id = ? AND kind = 'error' ORDER BY seq", (run_id,))
    return {"case_id": case["case_id"], "passed": bool(score["passed"]), "reasons": list(score["reasons"]),
            "metrics": score.get("metrics", {}), **run, "rounds": it[0]["planner_rounds"] if it else None,
            "itinerary_id": it[0]["itinerary_id"] if it else None, "status": it[0]["status"] if it else run["status"],
            "error": errors[0]["error"] if errors else None}  # fmt: skip


def run_uc(uc_dir, out):
    """Chạy mọi case của 1 UC vào thư mục out. Trả (số case pass, số case)."""
    lines = (Path("evals") / uc_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    scorer = importlib.import_module(f"evals.{uc_dir}.scorer")
    (out / "db").mkdir(parents=True)
    os.environ["TRACE_DIR"] = str(out / "traces")
    template = init_db(out / "db" / "_template.db")
    subprocess.run([sys.executable, "scripts/load_destination.py", "hue"], env=os.environ | {"DB_PATH": str(template)},
                   check=True)  # fmt: skip

    rows = []
    for case in cases:
        try:
            row = run_case(case, template, out, scorer)
        except Exception as e:  # noqa: BLE001 — 1 case lỗi không dừng cả bộ eval
            row = {"case_id": case["case_id"], "passed": False, "reasons": [f"runner: {type(e).__name__}: {e}"]}
        rows.append(row)
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {uc_dir} {row['case_id']}  {'; '.join(row['reasons'])}", flush=True)

    with open(out / "cases.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["case_id", "passed", "reasons", "status", "rounds", "tokens", "cost", "latency_ms"],
                           extrasaction="ignore")  # fmt: skip
        w.writeheader()
        w.writerows(r | {"reasons": "; ".join(r["reasons"])} for r in rows)
    passed = sum(r["passed"] for r in rows)
    print(f"{uc_dir}: {passed}/{len(rows)} case pass ({passed / max(len(rows), 1):.0%}) -> {out}\n", flush=True)
    return passed, len(rows)


def plugins():
    """Các UC đã có plug-in: evals/<uc>/ có cả cases.jsonl và scorer.py."""
    return sorted(d.name for d in Path("evals").iterdir() if (d / "cases.jsonl").exists() and (d / "scorer.py").exists())


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--uc", action="append", default=[], help="vd UC-02; lặp lại để chạy nhiều UC")
    ap.add_argument("--all", action="store_true", help="chạy mọi UC đã có plug-in trong evals/")
    args = ap.parse_args()
    ucs = plugins() if args.all else [uc.lower().replace("-", "") for uc in args.uc]  # UC-02 -> uc02
    if not ucs:
        ap.error("cần --uc <UC> hoặc --all")
    if missing := [uc for uc in ucs if uc not in plugins()]:
        sys.exit(f"Chưa có plug-in (evals/<uc>/cases.jsonl + scorer.py): {', '.join(missing)}")
    if port_open(MOCK_PORT):
        sys.exit(f"Cổng {MOCK_PORT} đang bận: tắt mock-weather đang chạy (make dev) rồi chạy lại.")

    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    if len(ucs) == 1:
        totals = {ucs[0]: run_uc(ucs[0], Path("results") / f"{ucs[0]}-{stamp}")}
    else:
        root = Path("results") / f"all-{stamp}"
        totals = {uc: run_uc(uc, root / uc) for uc in ucs}
    for uc, (passed, total) in totals.items():
        print(f"{uc}: {passed}/{total}")


if __name__ == "__main__":
    main()
