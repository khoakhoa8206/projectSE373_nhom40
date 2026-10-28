"""Tạo lại DB từ schema.sql (XOÁ DB cũ) và nạp 3 người dùng hư cấu. Chạy: python -m agent.db.init"""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from agent.db.repo import now

# Phase 1 chưa có đăng nhập: PWA chọn 1 trong 3 người dùng hư cấu này (không dùng người thật).
FICTIONAL_USERS = [
    ("u-ha", "Nguyễn Thu Hà (hư cấu)", "vi"),
    ("u-minh", "Trần Quang Minh (hư cấu)", "vi"),
    ("u-emma", "Emma Carter (fictional)", "en"),
]


def init_db(path=None):
    path = Path(path or os.environ.get("DB_PATH", "tourguide.db"))
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        conn.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", [(*u, now()) for u in FICTIONAL_USERS])
    return path


if __name__ == "__main__":
    print(f"Đã tạo {init_db()} (schema v0.1, {len(FICTIONAL_USERS)} người dùng hư cấu)")
