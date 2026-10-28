"""Hình học chỉ dùng cho POI công khai, không lưu vị trí người dùng."""

import json
import math
from itertools import pairwise


def _in_ring(lon, lat, ring):
    inside = False
    for a, b in pairwise(ring):
        cross = (lon - a[0]) * (b[1] - a[1]) - (lat - a[1]) * (b[0] - a[0])
        if abs(cross) < 1e-10 and min(a[0], b[0]) <= lon <= max(a[0], b[0]) and min(a[1], b[1]) <= lat <= max(a[1], b[1]):
            return True
        if (a[1] > lat) != (b[1] > lat) and lon < (b[0] - a[0]) * (lat - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def contains(geometry, lon, lat):
    """Point-in-polygon (kể biên), holes, MultiPolygon hoặc Circle đã có nguồn."""
    geo = json.loads(geometry) if isinstance(geometry, str) else geometry
    if geo["type"] == "Polygon":
        rings = geo["coordinates"]
        return _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, r) for r in rings[1:])
    if geo["type"] == "MultiPolygon":
        return any(contains({"type": "Polygon", "coordinates": c}, lon, lat) for c in geo["coordinates"])
    if geo["type"] == "Circle":
        x, y = geo["center"]
        dlat, dlon = math.radians(lat - y), math.radians(lon - x)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(y)) * math.cos(math.radians(lat)) * math.sin(dlon / 2) ** 2
        return 6371000 * 2 * math.asin(min(1, math.sqrt(a))) <= geo["radius_m"]
    raise ValueError("Hình học vùng không được hỗ trợ.")


def active(zone, day):
    return (not zone.get("active_from") or zone["active_from"] <= day) and (
        not zone.get("active_to") or zone["active_to"] >= day)
