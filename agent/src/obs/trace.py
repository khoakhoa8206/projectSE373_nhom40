"""Quan sát: làm thô toạ độ trước khi ghi log + ghi trace ra traces/<run_id>.jsonl (song song bảng trace_events)."""

import json
import os
from pathlib import Path

COORD_KEYS = {"lat", "lon", "lng", "latitude", "longitude"}
COORD_LISTS = {"coordinates", "center"}  # GeoJSON: [lon, lat]


def mask_coords(obj, _in_coords=False):
    """Làm thô mọi lat/lon còn 2 chữ số thập phân (~1 km). Chỉ dùng cho log/trace, không đổi dữ liệu gửi LLM."""
    if isinstance(obj, dict):
        return {
            k: round(v, 2) if k in COORD_KEYS and isinstance(v, float) else mask_coords(v, k in COORD_LISTS)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask_coords(v, _in_coords) for v in obj]
    if _in_coords and isinstance(obj, float):
        return round(obj, 2)
    return obj


def write_jsonl(run_id, event):
    trace_dir = Path(os.environ.get("TRACE_DIR", "traces"))
    trace_dir.mkdir(parents=True, exist_ok=True)
    with open(trace_dir / f"{run_id}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
