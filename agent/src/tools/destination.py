"""Bốn tool chỉ đọc dữ liệu đã nạp; không mạng, không ghi DB, không đoán dữ kiện."""

from datetime import date as Date
from typing import Literal

from agent.db import repo
from agent.schemas import POI
from agent.src.tools.opening_hours import opening_intervals

LEVELS = {"low": 0, "medium": 1, "high": 2}
Mode = Literal["walk", "drive", "bike"]


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError(f"{field} phải là mã không rỗng, tối đa 160 ký tự.")
    return value


def _public(row):
    if not all(isinstance(row.get(k), str) and row[k].strip() for k in ("source_url", "license", "verified_at")):
        return None
    return POI.model_validate(row).model_dump(mode="json")


def get_poi(poi_id: str) -> dict:
    """Chi tiết một POI có source_url, license, verified_at; thiếu nguồn hoặc mã không tồn tại thì báo lỗi.
    Giá/giờ null nghĩa là chưa xác minh, không phải miễn phí hoặc luôn mở cửa.
    """
    rows = repo.query("SELECT * FROM pois WHERE poi_id = ?", (_identifier(poi_id, "poi_id"),))
    result = _public(rows[0]) if rows else None
    if result is None:
        raise ValueError(f"POI không tồn tại hoặc thiếu nguồn: {poi_id}")
    return result


def search_poi(
    destination_id: str,
    category: Literal["attraction", "food", "lodging"] | None = None,
    tags: list[str] | None = None,
    max_walking_level: Literal["low", "medium", "high"] | None = None,
    child_age: int | None = None,
    outdoor: bool | None = None,
    limit: int = 20,
) -> list[dict]:
    """Tìm POI có nguồn; tags khớp TẤT CẢ; limit 1..100. Mức đi bộ/tuổi/outdoor chưa biết
    bị loại nếu yêu cầu lọc tương ứng. Không xem metadata còn thiếu là phù hợp với trẻ hoặc ít đi bộ.
    Kết quả có giá/giờ null phải được trình bày là chưa xác minh.
    """
    _identifier(destination_id, "destination_id")
    if category is not None and category not in ("attraction", "food", "lodging"):
        raise ValueError("category không hợp lệ.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit phải là số nguyên 1..100.")
    if max_walking_level is not None and max_walking_level not in LEVELS:
        raise ValueError("max_walking_level không hợp lệ.")
    if child_age is not None and (type(child_age) is not int or not 0 <= child_age <= 17):
        raise ValueError("child_age phải là số nguyên 0..17.")
    if outdoor is not None and type(outdoor) is not bool:
        raise ValueError("outdoor phải là boolean.")
    if tags is not None and (not isinstance(tags, list) or len(tags) > 20 or
                             any(not isinstance(t, str) or not t.strip() or len(t) > 80 for t in tags)):
        raise ValueError("tags phải là list tối đa 20 chuỗi không rỗng.")
    rows = repo.query("SELECT * FROM pois WHERE destination_id = ? ORDER BY poi_id", (destination_id,))
    matches = []
    for row in rows:
        poi = _public(row)
        if poi is None or (category is not None and poi["category"] != category):
            continue
        if tags and not set(tags) <= set(poi["tags"]):
            continue
        if max_walking_level is not None and (poi["walking_level"] is None or
                                              LEVELS[poi["walking_level"]] > LEVELS[max_walking_level]):
            continue
        if child_age is not None and (poi["min_age"] is None or poi["min_age"] > child_age):
            continue
        if outdoor is not None and poi["is_outdoor"] != outdoor:
            continue
        matches.append(poi)
        if len(matches) == limit:
            break
    return matches


def get_opening_hours(poi_id: str, date: str) -> dict:
    """Giờ mở cửa cho ngày ISO YYYY-MM-DD: intervals là các cặp phút trong ngày.
    [] = đóng cửa; null = chưa xác minh hoặc cú pháp chưa hỗ trợ, không mặc định mở.
    Trả nguồn/ngày xác minh và opening_hours gốc; không suy đoán ngày lễ.
    """
    on_date = Date.fromisoformat(date)
    if on_date.isoformat() != date:
        raise ValueError("date phải là YYYY-MM-DD.")
    poi = get_poi(poi_id)
    intervals = opening_intervals(poi["opening_hours"], on_date)
    return {"poi_id": poi_id, "date": date, "opening_hours": poi["opening_hours"], "intervals": intervals,
            "hours_status": "unverified" if intervals is None else "verified",
            "closed": None if intervals is None else not intervals,
            **{k: poi[k] for k in ("source_url", "license", "verified_at")}}


def get_travel_time(from_poi_id: str, to_poi_id: str, mode: Mode) -> dict:
    """Đọc ma trận routing có hướng đã cache. mode walk/drive/bike phải đúng mode có dữ liệu.
    status=unavailable, minutes=null nếu chưa có tuyến; không quy đổi driving sang walking,
    không đảo A→B thành B→A, không gán 0 khi thiếu. Đây là ước tính routing, không traffic realtime.
    """
    get_poi(from_poi_id)
    get_poi(to_poi_id)
    if mode not in ("walk", "drive", "bike"):
        raise ValueError("mode phải là walk, drive hoặc bike.")
    rows = repo.query("SELECT * FROM travel_matrix WHERE from_poi_id = ? AND to_poi_id = ? AND mode = ?",
                      (from_poi_id, to_poi_id, mode))
    if not rows:
        return {"from_poi_id": from_poi_id, "to_poi_id": to_poi_id, "mode": mode, "status": "unavailable",
                "minutes": None, "distance_m": None, "message": "chưa có tuyến được xác minh trong cache"}
    row = rows[0]
    return row | {"status": "ok", "cached": True, "license": "ODbL-1.0 (OSM-derived)",
                  "source_url": "https://router.project-osrm.org/" if row["provider"] == "osrm" else
                  "https://openrouteservice.org/", "verified_at": row["computed_at"],
                  "attribution": "OpenStreetMap contributors"}
