"""P3-2: evals/uc02/cases.jsonl + evals/fixtures/*.sql khớp hợp đồng P3 → P1 trong AGENTS.md."""

import json
import re
from contextlib import closing
from pathlib import Path

from agent.db import repo
from agent.schemas import Itinerary, TripProfile

ROOT = Path(__file__).resolve().parents[1]
MODES = {"normal", "heavy_rain", "timeout", "abnormal"}  # hợp đồng P4
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
EXPECT_KEYS = {"status_in", "must_include_pois", "closed", "null_price_pois", "min_attractions_per_day", "n_days",
               "min_priced_slots", "min_unpriced_slots", "forbidden_tags", "max_walking_level", "budget_tight"}
SCENARIOS = ["Ngân sách thoải mái", "1,5 triệu cho 3 ngày", "Mưa lớn", "POI đóng cửa thứ Hai",
             "Bé 4 tuổi, nhịp relaxed", "Thời tiết timeout", "Nhiều POI thiếu giá", "Nhóm 6 người", "Chuyến 1 ngày",
             "48 °C bất thường"]


def jsonl(rel):
    return [json.loads(x) for x in (ROOT / rel).read_text(encoding="utf-8").splitlines() if x.strip()]


CASES = jsonl("evals/uc02/cases.jsonl")


def test_uc02_cases_follow_contract():
    assert [c["case_id"] for c in CASES] == [f"C{i:02d}" for i in range(1, 11)]
    assert [c["title"] for c in CASES] == SCENARIOS
    gold = {r["request_id"]: r["gold_profile"] for r in jsonl("evals/trip_requests.jsonl")}
    statuses = set(Itinerary.model_fields["status"].annotation.__args__)
    for c in CASES:
        cid = c["case_id"]
        assert {"case_id", "profile", "weather_mode", "start_weekday", "expect"} <= set(c), cid
        assert set(c["profile"]) <= set(TripProfile.model_fields), cid  # không trường lạ
        p = TripProfile.model_validate(c["profile"])
        assert p.route == "plan" and p.start_date and p.end_date and p.adults and p.budget_total_vnd, cid
        assert c["weather_mode"] in MODES, cid
        assert WEEKDAYS[p.start_date.weekday()] == c["start_weekday"], cid
        assert set(c["expect"]) <= EXPECT_KEYS and set(c["expect"].get("status_in", [])) <= statuses, cid
        if "fixture" in c:
            assert re.fullmatch(r"evals/fixtures/[a-z0-9_]+\.sql", c["fixture"]) and (ROOT / c["fixture"]).exists(), cid
        if "source_request_id" in c:
            assert c["profile"] == gold[c["source_request_id"]], cid
    by = {c["case_id"]: c for c in CASES}
    assert by["C02"]["profile"]["budget_total_vnd"] == 1_500_000
    assert by["C05"]["profile"]["pace"] == "relaxed" and by["C05"]["profile"]["children"] == [{"age": 4}]
    assert by["C04"]["start_weekday"] == "mon"
    assert by["C08"]["profile"]["adults"] + len(by["C08"]["profile"]["children"]) == 6
    assert by["C09"]["profile"]["start_date"] == by["C09"]["profile"]["end_date"]
    assert [by[k]["weather_mode"] for k in ("C03", "C06", "C10")] == ["heavy_rain", "timeout", "abnormal"]


def test_fixtures_run_after_destination_data(db):
    """Fixture chạy sau dữ liệu Huế như evals/run.py; chỉ sửa dòng có sẵn, không lỗi trên schema thật."""
    before = repo.query("SELECT COUNT(*) AS n FROM pois")[0]["n"]
    for c in CASES:
        if c.get("fixture"):
            with closing(repo.get_conn()) as conn:
                conn.executescript((ROOT / c["fixture"]).read_text(encoding="utf-8"))
    row = repo.query("SELECT opening_hours, ticket_price_vnd FROM pois WHERE poi_id = 'hue-dai-noi'")[0]
    assert row == {"opening_hours": "Tu-Su 07:00-17:30; Mo off", "ticket_price_vnd": None}
    assert repo.query("SELECT COUNT(*) AS n FROM pois")[0]["n"] == before  # không chèn POI mới
