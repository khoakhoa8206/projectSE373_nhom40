"""P3-1: evals/trip_requests.jsonl – yêu cầu chuyến đi hư cấu + TripProfile chuẩn (agent/schemas)."""

import json
import re
from pathlib import Path

from agent.db.init import FICTIONAL_USERS
from agent.schemas import TripProfile

ROOT = Path(__file__).resolve().parents[1]
LINES = (ROOT / "evals" / "trip_requests.jsonl").read_text(encoding="utf-8").splitlines()
REQUESTS = [json.loads(x) for x in LINES if x.strip()]
PERSONAL = re.compile(r"(?:\+84|\b0)\d{9,10}\b|[\w.+-]+@[\w-]+\.\w+|\b\d{12}\b")  # SĐT, email, số CCCD


def strict_profile(profile):
    """TripProfile hợp lệ và không có trường lạ (Pydantic mặc định lặng lẽ bỏ trường lạ khi model_validate)."""
    extra = set(profile) - set(TripProfile.model_fields)
    assert not extra, f"trường không có trong TripProfile: {sorted(extra)}"
    return TripProfile.model_validate(profile)


def test_trip_requests_cover_required_types():
    assert len(REQUESTS) >= 15 and len({r["request_id"] for r in REQUESTS}) == len(REQUESTS)
    assert sum(r["lang"] == "en" for r in REQUESTS) >= 3
    need = {"complete", "missing_dates", "missing_budget", "duration_conflict", "unsupported_destination"}
    assert need <= {r["type"] for r in REQUESTS}


def test_trip_requests_gold_profiles():
    users = {u[0] for u in FICTIONAL_USERS}
    for r in REQUESTS:
        rid, p = r["request_id"], strict_profile(r["gold_profile"])
        assert r["user_id"] in users, rid  # chỉ người dùng hư cấu có sẵn sau init_db
        assert not PERSONAL.search(r["text"]), rid
        assert p.language == r["lang"], rid
        assert r["gold_destination_id"] in ("hue", None), rid
        assert (r["gold_destination_id"] is None) == (p.route == "unsupported"), rid
        assert set(r["checked_fields"]) <= set(TripProfile.model_fields), rid
        if p.route == "plan":
            assert p.start_date and p.end_date and p.adults and p.budget_total_vnd and not p.missing_info, rid
        if p.route == "ask_user":
            assert p.missing_info, rid
        if r["expect"].get("conflict"):
            assert p.start_date is None and p.end_date is None and p.route == "ask_user", rid
