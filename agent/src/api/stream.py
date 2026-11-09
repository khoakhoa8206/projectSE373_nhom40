"""SSE sự kiện node cho PWA (W8-P1-4): GET /api/runs/{run_id}/stream.

Nguồn = bảng trace_events (traced() / log_event đã ghi, toạ độ đã làm thô 2 chữ số thập phân), nên stream chạy được
cả khi graph ở thread/process khác. Mỗi dòng trace thành 1 event SSE:
    event: <kind>      node_start | node_end | llm_call | tool_call | skill_use | guardrail | approval | error
    data:  {"run_id", "seq", "ts", "node", "kind", "name", "args", "result", "duration_ms", "tokens", "error"}
Run dừng chờ người dùng → `event: interrupt` (data = payload {kind, approval_id, data}) cho mỗi yêu cầu đang chờ.
Cuối cùng luôn có `event: done` (data = {"run_id", "status"}) rồi đóng.
"""

import asyncio
import json

from agent.db import repo
from agent.src.graph import app as graph

POLL_S = 0.3
HEARTBEAT_EVERY = 50  # ~15 s không có gì mới thì gửi comment để proxy không cắt kết nối
MAX_POLLS = 4000  # ponytail: ~20 phút rồi đóng; run treo lâu hơn thì client mở lại stream (đọc tiếp từ ?after=)


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _new_rows(run_id, after):
    rows = repo.query("SELECT * FROM trace_events WHERE run_id = ? AND seq > ? ORDER BY seq", (run_id, after))
    return [r | {"args": json.loads(r["args"] or "null"), "result": json.loads(r["result"] or "null")} for r in rows]


async def run_events(run_id, after=0, is_disconnected=None):
    idle = 0
    for _ in range(MAX_POLLS):
        if is_disconnected and await is_disconnected():
            return
        status = repo.query("SELECT status FROM runs WHERE run_id = ?", (run_id,))[0]["status"]
        rows = _new_rows(run_id, after)  # đọc SAU status: run xong rồi thì lượt đọc này đã có trọn trace
        for row in rows:
            after = row["seq"]
            yield sse(row["kind"], row)
        if status != "running":
            if status == "interrupted":
                trip_id = repo.query("SELECT trip_id FROM runs WHERE run_id = ?", (run_id,))[0]["trip_id"]
                for payload in graph.pending_approvals(trip_id, run_id):
                    yield sse("interrupt", payload)
            yield sse("done", {"run_id": run_id, "status": status})
            return
        idle = 0 if rows else idle + 1
        if idle and idle % HEARTBEAT_EVERY == 0:
            yield ": ping\n\n"
        await asyncio.sleep(POLL_S)
    yield sse("done", {"run_id": run_id, "status": "running", "after": after})
