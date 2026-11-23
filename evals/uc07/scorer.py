"""Plug-in eval UC-07 (W11-P1-1): bộ nhớ sở thích qua nhiều chuyến. Không gọi LLM: chạy code thật của node memory,
store và API (TestClient, tài khoản đăng ký thật, session cookie) theo từng kịch bản trong cases.jsonl.

run_case(case) -> run_id   thực hiện kịch bản; mỗi quan sát ghi vào trace (node 'eval.uc07', kind guardrail, name = kịch bản)
score(case, conn, run_id)  chỉ đọc DB (memory_items, consents, trace_events)
metrics: leak (số lần lộ dữ liệu chéo user, phải = 0), recall (tỉ lệ mục đã lưu được nạp vào chuyến sau)."""

import json
import sqlite3
import time

from agent.db import repo
from agent.schemas import TripProfile
from agent.src.memory import store
from agent.src.nodes import memory
from scripts.scan_coords import scan_text

PROFILE = TripProfile(start_date="2026-12-01", end_date="2026-12-02", adults=2, interests=["history", "food"],
                      pace="relaxed", hard_constraints=["dị ứng đậu phộng"])  # fmt: skip
NODE = "eval.uc07"


def _account(name):
    """Tài khoản thật qua API (mật khẩu băm, cookie phiên) để kiểm phân quyền đúng như PWA."""
    from fastapi.testclient import TestClient

    from agent.src.api.server import app

    client = TestClient(app)
    r = client.post("/api/auth/register", json={"display_name": f"Eval {name}", "email": f"{repo.new_id(name)}@eval.example",
                                                "password": "eval-mat-khau-8", "preferred_lang": "vi"})  # fmt: skip
    r.raise_for_status()
    return client, r.json()["user_id"]


def run_case(case):
    t0 = time.perf_counter()
    client_a, a = _account("a")
    trip = repo.create_trip(a)
    repo.save_profile(trip, PROFILE)
    run_id = repo.create_run("UC-07", trip, a, eval_case_id=case["case_id"])

    items = memory.candidates(PROFILE, a, trip)
    picked = [i["key"] for i in items if i["kind"] in case["pick"]]
    saved = memory.save_selected(a, trip, items, None if case["scenario"] == "reject" else picked)
    repo.log_event(run_id, "remember", "guardrail", name="memory_write", result=saved)

    obs, scenario = {"user": a, "saved": saved["saved"]}, case["scenario"]
    if scenario == "next_trip":
        obs["context_kinds"] = sorted({m["kind"] for m in memory.memory_context(a, run_id)})  # trace: id + loại
    elif scenario == "cross_user":
        client_b, b = _account("b")
        target = saved["saved"][0]
        obs |= {
            "b_sees": len(client_b.get("/api/memory").json()["items"]),
            "b_sees_with_user_id": len(client_b.get(f"/api/memory?user_id={a}").json()["items"]),
            "b_patch": client_b.patch(f"/api/memory/{target}", json={"value": "bị sửa", "user_id": a}).status_code,
            "b_delete": client_b.delete(f"/api/memory/{target}").status_code,
            "b_trip_memory": len(memory.memory_context(b, run_id)),  # chuyến của B không nạp bộ nhớ của A
        }
    elif scenario == "revoke":
        obs["revoke"] = client_a.post("/api/memory/consent/revoke").status_code
    elif scenario == "expire":
        repo.query("UPDATE memory_items SET expires_at = '2000-01-01T00:00:00+07:00' WHERE memory_id = ?",
                   (saved["saved"][0],))  # fmt: skip
        obs["purged"] = store.expire_memory()
    elif scenario == "coords":
        try:
            store.memory_write(a, "other", "khách sạn ở 16.46981, 107.57863")
            obs["refused"] = False
        except store.MemoryRuleError:
            obs["refused"] = True
    repo.log_event(run_id, NODE, "guardrail", name=scenario, result=obs)
    repo.finish_run(run_id, "succeeded", 0, 0, 0.0, int((time.perf_counter() - t0) * 1000))
    return run_id


def _rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def score(case, conn, run_id):
    obs = json.loads(_rows(conn, "SELECT result FROM trace_events WHERE run_id = ? AND node = ? ORDER BY seq DESC LIMIT 1",
                           (run_id, NODE))[0]["result"])  # fmt: skip
    a = obs["user"]
    live = _rows(conn, "SELECT * FROM memory_items WHERE user_id = ? AND deleted_at IS NULL", (a,))
    reasons, leak, scenario = [], 0, case["scenario"]
    kinds = sorted({m["kind"] for m in live})

    if scenario in ("save_selected", "next_trip", "cross_user", "coords") and kinds != sorted(set(case["pick"])):
        reasons.append(f"mục đang lưu {kinds}, kỳ vọng đúng các loại đã tick {sorted(set(case['pick']))}")
    if any(m["sensitivity"] == "sensitive" and m["consent_id"] is None for m in live):
        reasons.append("mục nhạy cảm không có consent_id")
    if scenario == "reject" and live:
        reasons.append(f"người dùng từ chối mà vẫn lưu {len(live)} mục")

    recall = None
    if scenario == "next_trip":
        recall = len(set(obs["context_kinds"]) & set(kinds)) / max(len(kinds), 1)
        if recall < 1:
            reasons.append(f"chuyến sau chỉ nạp {obs['context_kinds']}, đã lưu {kinds}")
        trace = " ".join(r["result"] or "" for r in _rows(conn, "SELECT result FROM trace_events WHERE run_id = ? AND name = 'memory_read'", (run_id,)))
        if any(m["value"] in trace for m in live):
            reasons.append("trace memory_read chứa giá trị bộ nhớ (chỉ được ghi id + loại)")
    if scenario == "cross_user":
        leak = obs["b_sees"] + obs["b_sees_with_user_id"] + obs["b_trip_memory"] + (obs["b_patch"] < 400) + (obs["b_delete"] < 400)
        target = _rows(conn, "SELECT value, deleted_at FROM memory_items WHERE memory_id = ?", (obs["saved"][0],))
        leak += not target or target[0]["deleted_at"] is not None or target[0]["value"] == "bị sửa"
        if leak:
            reasons.append(f"lộ/sửa chéo dữ liệu user A từ user B: {obs}")
    if scenario == "revoke":
        sensitive = _rows(conn, "SELECT deleted_at FROM memory_items WHERE user_id = ? AND sensitivity = 'sensitive'", (a,))
        if any(m["sensitivity"] == "sensitive" for m in live) or not sensitive:
            reasons.append("thu hồi đồng ý mà mục nhạy cảm vẫn còn đọc được (hoặc chưa từng được lưu)")
        consent = _rows(conn, "SELECT revoked_at FROM consents WHERE user_id = ?", (a,))
        if not consent or any(c["revoked_at"] is None for c in consent):
            reasons.append("consent chưa có revoked_at")
    if scenario == "expire":
        if _rows(conn, "SELECT 1 FROM memory_items WHERE memory_id = ?", (obs["saved"][0],)):
            reasons.append("mục hết hạn chưa bị xoá cứng")
        if len(live) != len(obs["saved"]) - 1:
            reasons.append("job xoá nhầm mục còn hạn")
    if scenario == "coords":
        if not obs["refused"]:
            reasons.append("lưu được giá trị có toạ độ chính xác")
        texts = [m["value"] for m in _rows(conn, "SELECT value FROM memory_items")]
        texts += [r["args"] or "" for r in _rows(conn, "SELECT args FROM trace_events")]
        texts += [r["result"] or "" for r in _rows(conn, "SELECT result FROM trace_events")]
        if hits := [h for t in texts for h in scan_text(t)]:
            reasons.append(f"toạ độ chính xác trong DB/trace: {hits[:3]}")
    return {"passed": not reasons, "reasons": reasons, "metrics": {"leak": leak, "recall": recall}}

