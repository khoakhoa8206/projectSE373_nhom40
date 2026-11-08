"""Nạp log sự kiện hư cấu (evals/uc09/fixtures/*.json) vào 1 chuyến đi để thử/demo UC-09 (P3). Chạy sau `make db`:
    python scripts/load_trip_events.py evals/uc09/fixtures/trip_3days.json [--user u-ha] [--trip <trip_id>]
event_id được gắn tiền tố trip_id để nạp cùng log vào nhiều chuyến không bị trùng khoá."""

import argparse
import json
import sys
from pathlib import Path

# Hỗ trợ cả python scripts/load_trip_events.py và python -m.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from agent.db import repo
from agent.schemas import TripEvent


def load_fixture(path, trip_id) -> list[str]:
    """Kiểm từng sự kiện bằng TripEvent rồi ghi vào trip_events của trip_id. Trả danh sách event_id đã ghi."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [repo.add_trip_event(TripEvent.model_validate(raw | {"trip_id": trip_id,
                                                                "event_id": f"{trip_id}:{raw['event_id']}"}))
            for raw in data["events"]]  # fmt: skip


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Nạp log sự kiện hư cấu cho UC-09.")
    parser.add_argument("fixture", help="file JSON trong evals/uc09/fixtures/")
    parser.add_argument("--user", default="u-ha", help="người dùng hư cấu sở hữu chuyến đi (mặc định u-ha)")
    parser.add_argument("--trip", help="chuyến đi có sẵn; bỏ trống thì tạo chuyến mới")
    args = parser.parse_args()
    trip_id = args.trip or repo.create_trip(args.user)
    ids = load_fixture(args.fixture, trip_id)
    print(f"Đã nạp {len(ids)} sự kiện vào chuyến {trip_id} (người dùng {args.user}).")


if __name__ == "__main__":
    main()
