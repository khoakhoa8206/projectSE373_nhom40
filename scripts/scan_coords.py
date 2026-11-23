"""Quét toạ độ chính xác (≥ 3 chữ số thập phân, ~100 m) bị lọt ra ngoài chỗ được phép.
Được phép: bảng pois, restricted_zones (toạ độ công khai của địa điểm) và dữ liệu nguồn trong data/.
Quét: file trace/log/kết quả eval/bằng chứng trong repo + mọi bảng khác của DB ở DB_PATH (nếu file tồn tại).
python scripts/scan_coords.py  → in từng phát hiện, exit 1 nếu có (CI chặn)."""

import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

KEY = re.compile(r'"(lat|lon|lng|latitude|longitude)"\s*:\s*(-?\d+\.\d{3,})')
PAIR = re.compile(r"(-?\d{1,3}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})")  # "16.4698, 107.5786", GeoJSON [107.5786, 16.4698]
FILES = ("traces/**/*.jsonl", "results/**/*.jsonl", "results/**/*.csv", "docs/evidence/**/*.json", "**/*.log")
SKIP_DIRS = {".venv", "node_modules", ".git", "data"}
ALLOWED_TABLES = {"pois", "restricted_zones"}
COORD_COLUMNS = {"lat", "lon", "lng", "latitude", "longitude"}


def scan_text(text):
    found = [m.group(0) for m in KEY.finditer(text)]
    # cặp số < 1 (điểm số, xác suất) không phải toạ độ
    return found + [m.group(0) for m in PAIR.finditer(text) if min(abs(float(m[1])), abs(float(m[2]))) >= 1]


def scan_files(root="."):
    hits = []
    for pattern in FILES:
        for f in Path(root).glob(pattern):
            if SKIP_DIRS.isdisjoint(f.relative_to(root).parts):
                hits += [f"{f}: {h}" for h in scan_text(f.read_text(encoding="utf-8", errors="replace"))]
    return sorted(set(hits))


def scan_db(path):
    hits = []
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in set(tables) - ALLOWED_TABLES:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                for col, v in zip(cols, row, strict=True):
                    if isinstance(v, float) and col in COORD_COLUMNS and round(v, 2) != v:
                        hits.append(f"{path}:{table}.{col} = {v}")
                    elif isinstance(v, str):
                        hits += [f"{path}:{table}.{col}: {h}" for h in scan_text(v)]
    return hits


def main():
    hits = scan_files()
    db = os.environ.get("DB_PATH", ".runtime/tourguide.db")
    if Path(db).exists():
        hits += scan_db(db)
    for h in hits:
        print(h)
    print(f"{len(hits)} phát hiện toạ độ chính xác")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
