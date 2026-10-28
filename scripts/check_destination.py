"""Kiểm tra dữ liệu POI Huế trước khi nạp DB."""

import csv
import json
import math
import sys
from datetime import date
from pathlib import Path

# Hỗ trợ cả python scripts/check_destination.py và python -m.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.schemas import POI

ROOT = Path(__file__).resolve().parents[1]
POI_PATH = ROOT / "data" / "destinations" / "hue" / "poi.csv"


def check_pois(path: Path) -> list[POI]:
    """Kiểm tra cấu trúc, giá trị và mã POI trùng."""
    pois = []
    seen_ids = set()

    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames != list(POI.model_fields):
            raise ValueError("Tên hoặc thứ tự cột không khớp schema POI.")

        for line_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Dòng {line_number}: thừa hoặc thiếu cột.")

            # Ô rỗng thành None, không biến thành giá 0.
            data = {key: value.strip() or None for key, value in row.items()}
            if data["tags"] is None:
                data["tags"] = []

            try:
                poi = POI.model_validate(data)

                for field in ("poi_id", "destination_id", "name_vi", "source_url", "license", "verified_at"):
                    if not getattr(poi, field).strip():
                        raise ValueError(f"Thiếu {field}.")

                if poi.destination_id != "hue":
                    raise ValueError("destination_id phải là hue.")
                if not (-90 <= poi.lat <= 90 and -180 <= poi.lon <= 180):
                    raise ValueError("Toạ độ nằm ngoài phạm vi hợp lệ.")
                if not poi.source_url.startswith(("https://", "http://")):
                    raise ValueError("source_url phải là URL HTTP/HTTPS.")
                if date.fromisoformat(poi.verified_at) > date.today():
                    raise ValueError("Ngày xác minh không được ở tương lai.")
                if poi.poi_id in seen_ids:
                    raise ValueError(f"Trùng poi_id: {poi.poi_id}.")
                if poi.min_age is not None and not 0 <= poi.min_age <= 120:
                    raise ValueError("min_age nằm ngoài phạm vi 0..120.")
            except ValueError as error:
                raise ValueError(f"Dòng {line_number}: {error}") from error

            seen_ids.add(poi.poi_id)
            pois.append(poi)

    if not pois:
        raise ValueError("File chưa có POI.")

    return pois


def check_zones(path: Path) -> list[dict]:
    """Kiểm GeoJSON trước khi nạp; không tự tạo hình học hay phạm vi cấm."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("type") != "FeatureCollection" or not isinstance(document.get("features"), list):
        raise ValueError("Vùng hạn chế phải là FeatureCollection.")
    zones, seen = [], set()
    for feature in document["features"]:
        if feature.get("type") != "Feature":
            raise ValueError("Vùng phải là GeoJSON Feature.")
        props, geometry = feature["properties"].copy(), feature["geometry"]
        for field in ("zone_id", "destination_id", "name", "zone_type", "reason", "source_url", "license", "verified_at"):
            if not isinstance(props.get(field), str) or not props[field].strip():
                raise ValueError(f"Vùng thiếu {field}.")
        if props["destination_id"] != "hue" or props["zone_id"] in seen:
            raise ValueError("Mã vùng trùng hoặc destination_id sai.")
        if props["zone_type"] not in ("military", "beach_warning", "landslide", "restoration", "other"):
            raise ValueError("zone_type không hợp lệ.")
        if not props["source_url"].startswith(("https://", "http://")):
            raise ValueError("Vùng cần source_url HTTP/HTTPS.")
        if date.fromisoformat(props["verified_at"]) > date.today():
            raise ValueError("Ngày xác minh vùng ở tương lai.")
        for field in ("active_from", "active_to"):
            props.setdefault(field, None)
            if props[field] is not None:
                date.fromisoformat(props[field])
        if props["active_from"] and props["active_to"] and props["active_from"] > props["active_to"]:
            raise ValueError("Khoảng hiệu lực vùng bị đảo.")
        if geometry.get("type") != "Polygon" or not geometry.get("coordinates"):
            raise ValueError("Loader v1 chỉ nhận Polygon có nguồn.")
        for ring in geometry["coordinates"]:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon phải khép kín, ít nhất 4 điểm.")
            for point in ring:
                if (len(point) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point)
                        or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                    raise ValueError("Polygon có toạ độ không hợp lệ.")
        seen.add(props["zone_id"])
        props["geometry"] = json.dumps(geometry, ensure_ascii=False)
        zones.append(props)
    return zones


def check_matrix(path: Path, pois: list[POI]) -> list[dict]:
    """Kiểm ID, mode, số nguyên không âm, metadata và tính duy nhất của cặp có hướng."""
    from datetime import datetime

    ids, seen, rows = {p.poi_id for p in pois}, set(), []
    fields = {"from_poi_id", "to_poi_id", "mode", "minutes", "distance_m", "provider", "computed_at"}
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if set(reader.fieldnames or []) != fields:
            raise ValueError("Cột travel_matrix không hợp lệ.")
        for row in reader:
            if None in row or any(v is None or not v.strip() for v in row.values()):
                raise ValueError("Ma trận thiếu cột hoặc giá trị.")
            row = {k: v.strip() for k, v in row.items()}
            if row["from_poi_id"] not in ids or row["to_poi_id"] not in ids:
                raise ValueError("Ma trận tham chiếu POI không có trong CSV.")
            if row["mode"] not in ("walk", "drive", "bike") or row["provider"] not in ("osrm", "ors"):
                raise ValueError("Mode/provider ma trận không hợp lệ.")
            for field in ("minutes", "distance_m"):
                if not row[field].isdigit():
                    raise ValueError("Thời gian/khoảng cách phải là số nguyên không âm.")
                row[field] = int(row[field])
            datetime.fromisoformat(row["computed_at"])
            key = (row["from_poi_id"], row["to_poi_id"], row["mode"])
            if key in seen:
                raise ValueError("Trùng cặp có hướng/mode trong ma trận.")
            seen.add(key)
            rows.append(row)
    return rows


def main() -> None:
    pois = check_pois(POI_PATH)
    print(f"PASS: {len(pois)} POI hợp lệ về cấu trúc và giá trị cơ bản.")
    print(f"Chưa có giờ mở cửa: {sum(p.opening_hours is None for p in pois)}")
    print(f"Chưa có giá: {sum(p.ticket_price_vnd is None for p in pois)}")


if __name__ == "__main__":
    main()
