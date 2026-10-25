"""Nạp POI đã kiểm tra vào DB ở DB_PATH."""

import argparse
import sys
from pathlib import Path

# Hỗ trợ cả python scripts/load_destination.py và python -m.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.db import repo
from scripts.check_destination import POI_PATH, check_matrix, check_pois, check_zones


def main() -> None:
    parser = argparse.ArgumentParser(description="Nạp dữ liệu điểm đến.")
    parser.add_argument("destination", choices=["hue"])
    parser.add_argument("--complete", action="store_true", help="Yêu cầu đủ bộ dữ liệu bàn giao.")
    args = parser.parse_args()

    # Kiểm tra toàn bộ CSV trước khi ghi DB.
    pois = check_pois(POI_PATH)
    zone_path = POI_PATH.with_name("restricted_zones.geojson")
    matrix_path = POI_PATH.with_name("travel_matrix.csv")
    # Cho phép fixture POI-only; bundle thật phải kiểm đủ bằng --complete.
    zones = check_zones(zone_path) if zone_path.exists() else []
    matrix = check_matrix(matrix_path, pois) if matrix_path.exists() else []
    if args.complete:
        counts = {category: sum(p.category == category for p in pois) for category in ("attraction", "food", "lodging")}
        if any(counts[k] < n for k, n in (("attraction", 15), ("food", 10), ("lodging", 5))) or len(zones) < 5:
            raise ValueError("Bundle chưa đủ 15 tham quan, 10 ăn uống, 5 lưu trú và 5 vùng.")
        if len({(r["from_poi_id"], r["to_poi_id"]) for r in matrix}) < len(pois) ** 2:
            raise ValueError("Bundle chưa có cache cho toàn bộ cặp POI có hướng.")
    result = repo.save_hue_destination(pois, zones, matrix)
    print(f"Đã nạp/cập nhật: {result}")


if __name__ == "__main__":
    main()
