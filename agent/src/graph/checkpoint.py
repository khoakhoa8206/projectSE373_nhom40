"""Checkpointer SQLite cho LangGraph (W8-P1-1). thread_id = trip_id.

Checkpoint nằm chung file DB_PATH (bảng `checkpoints`, `writes` do LangGraph tự tạo), nên DB tạm của test/eval
có checkpoint riêng, `agent.db.init` xoá DB thì xoá luôn checkpoint. Mỗi lần chạy/resume mở 1 kết nối riêng:
tắt backend rồi bật lại, graph đọc checkpoint cuối và chạy tiếp từ node đang dừng.
"""

import os
import sqlite3
from contextlib import contextmanager

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

# State graph chứa model Pydantic: khai báo rõ, LangGraph sẽ chặn type lạ khi đọc lại checkpoint.
STATE_MODELS = [("agent.schemas", name) for name in ("Child", "TripProfile", "Slot", "Itinerary", "Violation")]
SERDE = JsonPlusSerializer(allowed_msgpack_modules=STATE_MODELS)


def config(trip_id: str) -> dict:
    return {"configurable": {"thread_id": trip_id}}


@contextmanager
def open_checkpointer():
    conn = sqlite3.connect(os.environ.get("DB_PATH", "tourguide.db"), timeout=10, check_same_thread=False)
    try:
        yield SqliteSaver(conn, serde=SERDE)
    finally:
        conn.close()
