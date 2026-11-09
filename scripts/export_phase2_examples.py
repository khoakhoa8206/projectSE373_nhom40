"""User chủ động chạy --live để tạo 3 lịch từ LLM thật; không có mẫu giả thay thế."""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from agent.db import repo
from agent.db.init import init_db
from agent.schemas import Itinerary, TripProfile
from agent.src.graph.app import run_uc02
from scripts.check_destination import POI_PATH, check_matrix, check_pois, check_zones

EXAMPLES = {
    "thu-ha-3-days": {"start_date": "2026-11-27", "end_date": "2026-11-29", "adults": 2,
                      "children": [{"age": 6}], "budget_total_vnd": 8000000, "interests": ["food", "history"]},
    "english-2-days": {"start_date": "2026-11-27", "end_date": "2026-11-28", "adults": 1,
                       "budget_total_vnd": 3000000, "language": "en", "interests": ["history"]},
    "low-budget": {"start_date": "2026-11-28", "end_date": "2026-11-28", "adults": 1,
                   "budget_total_vnd": 300000, "pace": "relaxed", "interests": ["history"]},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Cho phép gọi LLM thật, có thể tốn phí")
    parser.add_argument("--output", type=Path, default=Path("evals/fixtures/itineraries"))
    args = parser.parse_args()
    if not args.live:
        parser.error("Cần --live; không tạo fixture giả hoặc tự gọi provider.")
    load_dotenv()
    if not os.environ.get("LLM_API_KEY"):
        parser.error("Chưa có LLM_API_KEY trong môi trường/.env; không in hoặc gửi key vào chat.")
    args.output.mkdir(parents=True, exist_ok=True)
    targets = [args.output / f"{name}.json" for name in EXAMPLES]
    if any(path.exists() for path in targets):
        parser.error("Đã có file kết quả; chọn --output thư mục mới để không ghi đè.")
    folder = Path("results") / repo.new_id("phase2-examples")
    folder.mkdir(parents=True)
    os.environ["DB_PATH"] = str((folder / "examples.db").resolve())
    os.environ["TRACE_DIR"] = str((folder / "traces").resolve())
    init_db()
    pois = check_pois(POI_PATH)
    zones = check_zones(POI_PATH.with_name("restricted_zones.geojson"))
    matrix = check_matrix(POI_PATH.with_name("travel_matrix.csv"), pois)
    repo.save_hue_destination(pois, zones, matrix)
    evidence = []
    for name, profile in EXAMPLES.items():
        trip = repo.create_trip("u-ha")
        repo.save_profile(trip, TripProfile.model_validate(profile))
        result = run_uc02(trip, "u-ha")
        evidence.append({"example": name, **result})
        (folder / "runs.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        if result["error"]:
            raise RuntimeError(f"{name}: run lỗi; xem {folder}/runs.json, không tạo lịch giả.")
        stored = repo.itinerary_for_trip(trip)
        itinerary = Itinerary.model_validate(stored)
        (args.output / f"{name}.json").write_text(itinerary.model_dump_json(indent=2), encoding="utf-8")
        print(f"{name}: {itinerary.status}, run_id={result['run_id']}")
    print(f"Đã export 3 lịch từ LLM thật. Đây chưa phải lịch được người dùng duyệt. Evidence: {folder}")


if __name__ == "__main__":
    main()
