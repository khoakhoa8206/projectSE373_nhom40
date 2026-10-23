"""Eval runner: python -m evals.run --uc UC-02
Mỗi case: DB mới (schema + dữ liệu Huế + fixture nếu có) · mock-weather bật riêng theo weather_mode ·
chạy graph (runs.eval_case_id = case_id) · gọi evals/<uc>/scorer.py: score(case, conn, run_id) -> {passed, reasons}.
Kết quả: results/<eval_run_id>/ gồm cases.jsonl, summary.csv, traces/, db/<case_id>.db."""

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


def run_case(case, template, out, scorer):
    db = out / "db" / f"{case['case_id']}.db"
    shutil.copy(template, db)
    os.environ["DB_PATH"] = str(db)
    if case.get("fixture"):  # dữ liệu hư cấu riêng của case, vd evals/fixtures/closed_monday.sql
        with closing(repo.get_conn()) as conn:
            conn.executescript(Path(case["fixture"]).read_text(encoding="utf-8"))

    mock = start_mock(case.get("weather_mode", "normal"))
    try:
        trip_id = repo.create_trip(EVAL_USER)
        repo.save_profile(trip_id, TripProfile.model_validate(case["profile"]))
        res = run_uc02(trip_id, EVAL_USER, eval_case_id=case["case_id"])
        with closing(repo.get_conn()) as conn:
            score = scorer.score(case, conn, res["run_id"])
    finally:
        mock.terminate()
        mock.wait()

    run = repo.query(
        "SELECT tokens_in + tokens_out AS tokens, cost_usd AS cost, latency_ms FROM runs WHERE run_id = ?",
        (res["run_id"],),
    )[0]
    rounds = repo.query("SELECT planner_rounds FROM itineraries WHERE run_id = ?", (res["run_id"],))
    return {"case_id": case["case_id"], "passed": bool(score["passed"]), "reasons": list(score["reasons"]),
            "rounds": rounds[0]["planner_rounds"] if rounds else None, **run} | res  # fmt: skip


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--uc", required=True, help="vd UC-02")
    uc_dir = ap.parse_args().uc.lower().replace("-", "")  # UC-02 -> uc02
    lines = (Path("evals") / uc_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    scorer = importlib.import_module(f"evals.{uc_dir}.scorer")
    if port_open(MOCK_PORT):
        sys.exit(f"Cổng {MOCK_PORT} đang bận: tắt mock-weather đang chạy (make dev) rồi chạy lại.")

    out = Path("results") / f"{uc_dir}-{datetime.now():%Y%m%d-%H%M%S}"
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
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['case_id']}  {'; '.join(row['reasons'])}", flush=True)

    with open(out / "cases.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["case_id", "passed", "reasons", "rounds", "tokens", "cost", "latency_ms"],
                           extrasaction="ignore")  # fmt: skip
        w.writeheader()
        w.writerows(r | {"reasons": "; ".join(r["reasons"])} for r in rows)
    passed = sum(r["passed"] for r in rows)
    print(f"\n{passed}/{len(rows)} case pass ({passed / len(rows):.0%}) -> {out}")


if __name__ == "__main__":
    main()
