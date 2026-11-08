"""Plug-in eval UC-11 (P4), theo hợp đồng runner:

    run_case(case) -> run_id                        # chạy verifier trên case["text"]
    score(case, conn, run_id) -> {"passed": bool, "reasons": [str], "metrics": {...}, "gold": [...], "leaked": [...]}

- run_case: runner đã tạo DB mới (dữ liệu Huế) và bật mock-weather theo case["weather_mode"]. UC-11 không chạy graph
  UC-02: đầu vào là câu trả lời nháp có lỗi cài sẵn. Tách claim bằng regex cho tất định; UC11_EXTRACTOR=llm để đo bản
  LLM + lưới regex (cần key).
- score chỉ đọc DB: bảng claims (nhãn từng claim), trace_events (văn bản cuối ở sự kiện verify/verify_gate),
  weather_snapshots (case thời tiết phi lý). Mọi phép kiểm là code, không gọi LLM.
- Claim mong đợi khớp claim trong DB khi claim_text == span và cùng claim_type.
- metrics(): tổng hợp các chỉ số docs/uc-11.md mục 12.3 trên nhiều case.
"""

import json
import os
import re
from contextlib import contextmanager

from agent.db import repo
from agent.src.nodes import verify

EVAL_USER = "u-ha"


def run_case(case):
    trip_id = repo.create_trip(EVAL_USER)
    run_id = repo.create_run("UC-11", trip_id, EVAL_USER, eval_case_id=case["case_id"])
    extractor = verify.extract_llm if os.environ.get("UC11_EXTRACTOR") == "llm" else verify.extract_regex
    verify.verify_and_fix(case["text"], run_id, case["case_id"], ctx=case["context"] | {"lang": case["lang"]},
                          extractor=extractor, target_type=case["target_type"])  # fmt: skip
    return run_id


@contextmanager
def read_only(conn):
    conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.execute("PRAGMA query_only = OFF")


def score(case, conn, run_id):
    reasons = []
    with read_only(conn):
        claims = conn.execute("SELECT claim_type, claim_text, status, corrected_text FROM claims WHERE run_id = ?",
                              (run_id,)).fetchall()  # fmt: skip
        gate = conn.execute("SELECT result FROM trace_events WHERE run_id = ? AND node = 'verify' AND name = 'verify_gate'"
                            " ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()  # fmt: skip
        snaps = conn.execute("SELECT is_anomalous FROM weather_snapshots WHERE run_id = ?", (run_id,)).fetchall()

    by_key = {(c["claim_type"], c["claim_text"]): c for c in claims}
    gold = []
    for g in case["expected"]:
        got = by_key.get((g["claim_type"], g["span"]))
        gold.append(g | {"got": got["status"] if got else None})
        if got is None:
            reasons.append(f"không tách được claim {g['span']!r} ({g['claim_type']})")
        elif got["status"] != g["status"]:
            reasons.append(f"{g['span']!r}: {got['status']}, cần {g['status']}")

    if gate is None:
        reasons.append("không có sự kiện verify_gate (verifier chưa chạy xong)")
        final = ""
    else:
        final = json.loads(gate["result"])["text"]
    # theo ranh giới số: "5 mm" không tính là lọt khi văn bản cuối ghi "47,5 mm"
    leaked = [c["claim_text"] for c in claims if c["status"] == "contradicted"
              and re.search(rf"(?<![\d.,]){re.escape(c['claim_text'])}(?!\d)", final)]  # fmt: skip
    if leaked:
        reasons.append(f"claim sai còn trong văn bản cuối: {leaked}")

    abnormal_ok = None
    if case.get("weather_mode") == "abnormal":
        flagged = any(s["is_anomalous"] for s in snaps)
        trusted = any(c["claim_type"] == "weather" and c["status"] == "verified" for c in claims)
        abnormal_ok = flagged and not trusted
        if not flagged:
            reasons.append("thời tiết phi lý không bị đánh dấu (weather_snapshots.is_anomalous = 0)")
        if trusted:
            reasons.append("claim thời tiết được verified dù dữ liệu phi lý")

    return {"passed": not reasons, "reasons": reasons, "metrics": {"claims": len(claims), "leaked": len(leaked)},
            "gold": gold, "leaked": leaked, "abnormal_ok": abnormal_ok}  # fmt: skip


def metrics(results):
    """Chỉ số mục 12.3 trên nhiều case: results = [(case, score(...))]."""
    gold = [g for _, r in results for g in r["gold"]]
    wrong = [g for g in gold if g["status"] != "verified"]  # claim cài lỗi hoặc không có nguồn
    right = [g for g in gold if g["status"] == "verified"]
    abnormal = [r["abnormal_ok"] for _, r in results if r["abnormal_ok"] is not None]
    return {
        "recall_wrong": sum(g["got"] in ("contradicted", "unverified") for g in wrong) / len(wrong) if wrong else None,
        "false_alarm": sum(g["got"] == "contradicted" for g in right) / len(right) if right else None,
        "leaked": sum(len(r["leaked"]) for _, r in results),
        "abnormal_flagged": sum(abnormal) / len(abnormal) if abnormal else None,
        "cases_passed": sum(r["passed"] for _, r in results),
        "cases": len(results),
    }
