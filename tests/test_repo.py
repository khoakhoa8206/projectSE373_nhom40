import json

import pytest
from pydantic import ValidationError

from agent.db import repo
from agent.schemas import Slot, TripProfile


def test_log_event_keeps_order_and_masks_coords(db):
    run_id = repo.create_run("UC-02", None, "u-ha")
    for i in range(3):
        repo.log_event(run_id, "plan", "tool_call", name=f"t{i}", args={"lat": 16.469812, "lon": 107.578634},
                       result={"poi": {"lat": 16.4698}, "center": [107.5786, 16.4698]})  # fmt: skip

    rows = repo.query("SELECT seq, name, args, result FROM trace_events WHERE run_id = ? ORDER BY seq", (run_id,))
    assert [(r["seq"], r["name"]) for r in rows] == [(1, "t0"), (2, "t1"), (3, "t2")]
    assert json.loads(rows[0]["args"]) == {"lat": 16.47, "lon": 107.58}
    assert json.loads(rows[0]["result"]) == {"poi": {"lat": 16.47}, "center": [107.58, 16.47]}

    lines = (db / "traces" / f"{run_id}.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["seq"] for line in lines] == [1, 2, 3]
    assert json.loads(lines[0])["args"] == {"lat": 16.47, "lon": 107.58}


def test_save_profile_bumps_version(db):
    trip_id = repo.create_trip("u-ha")
    profile = TripProfile(start_date="2026-11-27", end_date="2026-11-29", adults=2, children=[{"age": 6}])
    repo.save_profile(trip_id, profile)
    second = repo.save_profile(trip_id, profile)
    versions = repo.query("SELECT version FROM trip_profiles WHERE trip_id = ? ORDER BY version", (trip_id,))
    assert [v["version"] for v in versions] == [1, 2]
    assert repo.latest_profile(trip_id) == (second, profile)


def test_schema_rules():
    for bad in ({"start_date": "2026-11-29", "end_date": "2026-11-27"},  # về trước ngày đi
                {"start_date": "2026-11-01", "end_date": "2026-11-06"},  # 6 ngày
                {"pace": "fast"}):  # fmt: skip
        with pytest.raises(ValidationError):
            TripProfile(**bad)

    ok = {"day_index": 1, "slot_date": "2026-11-27", "start_time": "08:00", "end_time": "09:00", "activity": "x",
          "cost_source": "unverified", "hours_status": "unverified"}  # fmt: skip
    Slot(**ok)
    for bad in ({"end_time": "08:00"}, {"start_time": "8:00"}, {"cost_source": "tool"}, {"cost_vnd": 50000}):
        with pytest.raises(ValidationError):
            Slot(**ok | bad)
