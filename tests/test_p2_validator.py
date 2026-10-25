"""Rule và fabrication checker dùng dữ liệu hư cấu, không gọi LLM/mạng."""

import copy
from datetime import date

import pytest

from agent.schemas import Itinerary, Slot, TripProfile
from agent.src.tools.opening_hours import opening_intervals
from agent.src.validation.validator import fabrication_with_facts, validate_with_facts


@pytest.fixture
def facts():
    base = {"destination_id": "hue", "ticket_price_vnd": 100, "opening_hours": "Mo-Su 08:00-12:00,13:00-17:00",
            "lat": 16.45, "lon": 107.58, "is_outdoor": 1,
            "source_url": "https://example.org/test", "license": "test-only", "verified_at": "2026-10-25"}
    return {"pois": {"a": base.copy(), "b": base.copy()}, "zones": [], "matrix": [
        {"from_poi_id": "a", "to_poi_id": "b", "mode": "drive", "minutes": 30, "distance_m": 2000}]}


@pytest.fixture
def profile():
    return TripProfile(start_date="2026-10-26", end_date="2026-10-26", adults=1, budget_total_vnd=1000, pace="moderate")


def slot(poi="a", start="09:00", end="10:00", **changes):
    data = {"slot_id": f"test-{poi}", "day_index": 1, "slot_date": "2026-10-26", "poi_id": poi,
            "start_time": start, "end_time": end, "activity": "Hoạt động kiểm thử",
            "cost_vnd": 100, "cost_source": "tool", "hours_status": "verified"}
    return Slot(**(data | changes))


def rules(itinerary, profile, facts, weather=None):
    return {v.rule for v in validate_with_facts(itinerary, profile, weather or {}, facts)}


def test_valid_plan(profile, facts):
    it = Itinerary(slots=[slot(), slot("b", "10:30", "11:30", travel_minutes_from_prev=30)])
    assert validate_with_facts(it, profile, {}, facts) == []
    assert fabrication_with_facts(it, facts) == []


@pytest.mark.parametrize("start", ["09:45", "10:15"])
def test_overlap_includes_travel(profile, facts, start):
    it = Itinerary(slots=[slot(), slot("b", start, "11:30", travel_minutes_from_prev=30)])
    assert "overlap" in rules(it, profile, facts)


@pytest.mark.parametrize("start,end", [("07:30", "08:30"), ("11:30", "13:30"), ("16:30", "17:30")])
def test_opening_hours_and_lunch(profile, facts, start, end):
    assert "opening_hours" in rules(Itinerary(slots=[slot(start=start, end=end)]), profile, facts)


def test_closed_monday(profile, facts):
    facts["pois"]["a"]["opening_hours"] = "Tu-Su 08:00-17:00; Mo off"
    assert "opening_hours" in rules(Itinerary(slots=[slot()]), profile, facts)


def test_budget_boundary_and_unknown_price(profile, facts):
    profile.budget_total_vnd = 100
    assert "budget" not in rules(Itinerary(slots=[slot()]), profile, facts)
    profile.budget_total_vnd = 99
    assert "budget" in rules(Itinerary(slots=[slot()]), profile, facts)
    facts["pois"]["a"]["ticket_price_vnd"] = None
    unknown = Itinerary(slots=[slot(cost_vnd=None, cost_source="unverified")])
    assert fabrication_with_facts(unknown, facts) == []


@pytest.mark.parametrize("end,violates", [("11:00", False), ("11:01", True)])
def test_rain_two_hour_boundary(profile, facts, end, violates):
    it = Itinerary(slots=[slot(end=end)])
    weather = {"2026-10-26": {"condition": "heavy_rain", "is_anomalous": 0}}
    assert ("weather" in rules(it, profile, facts, weather)) is violates


def test_rain_uses_daily_sum_and_unknown_outdoor(profile, facts):
    facts["pois"]["b"]["is_outdoor"] = None
    it = Itinerary(slots=[slot(end="10:15"), slot("b", "10:45", "11:45", travel_minutes_from_prev=30)])
    rain = {"2026-10-26": {"condition": "heavy_rain"}}
    assert "weather" in rules(it, profile, facts, rain)
    rain["2026-10-26"]["is_anomalous"] = 1
    assert "weather" not in rules(it, profile, facts, rain)


def test_pace_and_wrong_day(profile, facts):
    profile.pace = "relaxed"
    it = Itinerary(slots=[slot(start="08:00", end="13:00")])
    assert "overload" in rules(it, profile, facts)
    it.slots[0].slot_date = date(2026, 10, 27)
    assert "overlap" in rules(it, profile, facts)


def test_restricted_area_is_date_aware(profile, facts):
    facts["zones"] = [{"destination_id": "hue", "name": "Vùng hư cấu", "source_url": "https://example.org",
                       "active_from": "2026-10-26", "active_to": "2026-10-26",
                       "geometry": {"type": "Polygon", "coordinates": [
                           [[107.5, 16.4], [107.6, 16.4], [107.6, 16.5], [107.5, 16.5], [107.5, 16.4]]]}}]
    assert "restricted_area" in rules(Itinerary(slots=[slot()]), profile, facts)
    facts["zones"][0]["active_to"] = "2026-10-25"
    assert "restricted_area" not in rules(Itinerary(slots=[slot()]), profile, facts)


@pytest.mark.parametrize("change", [
    {"poi_id": "missing"}, {"cost_vnd": 99}, {"cost_vnd": 0, "cost_source": "free"},
    {"hours_status": "not_applicable"}, {"travel_minutes_from_prev": 1},
])
def test_fabricated_values(facts, change):
    assert fabrication_with_facts(Itinerary(slots=[slot(**change)]), facts)


def test_unknown_hours_cannot_be_verified(facts):
    facts["pois"]["a"]["opening_hours"] = None
    assert fabrication_with_facts(Itinerary(slots=[slot()]), facts)
    assert fabrication_with_facts(Itinerary(slots=[slot(hours_status="unverified")]), facts) == []


def test_fabricated_travel_and_missing_route(facts):
    it = Itinerary(slots=[slot(), slot("b", "10:30", "11:30", travel_minutes_from_prev=1)])
    assert fabrication_with_facts(it, facts)
    facts["matrix"] = []
    it.slots[1].travel_minutes_from_prev = 30
    assert fabrication_with_facts(it, facts)


@pytest.mark.parametrize("raw", [None, "PH off; Mo-Su 08:00-17:00", "sunrise-sunset", "Mo 25:00-26:00", "nonsense"])
def test_unsupported_hours_are_unknown(raw):
    assert opening_intervals(raw, date(2026, 10, 26)) is None


def test_hours_overnight_and_boundary():
    assert opening_intervals("Mo 22:00-02:00", date(2026, 10, 26)) == [(1320, 1440)]
    assert opening_intervals("Mo 22:00-02:00", date(2026, 10, 27)) == [(0, 120)]
    assert opening_intervals("24/7", date(2026, 10, 26)) == [(0, 1440)]


def test_pure_core_does_not_mutate_inputs(profile, facts):
    it = Itinerary(slots=[slot()])
    before = copy.deepcopy((it, profile, facts))
    validate_with_facts(it, profile, {}, facts)
    fabrication_with_facts(it, facts)
    assert (it, profile, facts) == before


def test_child_and_mobility_unknown_cannot_be_approved(profile, facts):
    from agent.schemas import Child

    profile.children = [Child(age=4)]
    profile.mobility_notes = "Cần ít đi bộ"
    it = Itinerary(slots=[slot()])
    assert "overload" in rules(it, profile, facts)
    facts["pois"]["a"].update(min_age=0, walking_level="low")
    assert "overload" not in rules(it, profile, facts)
    facts["pois"]["a"]["min_age"] = 6
    assert "overload" in rules(it, profile, facts)


def test_repair_feedback_contains_exact_facts(profile, facts):
    it = Itinerary(slots=[slot(), slot("b", "10:15", "11:30", travel_minutes_from_prev=30)])
    messages = [v.message for v in validate_with_facts(it, profile, {}, facts)]
    assert any("10:30" in text and "30 phút" in text for text in messages)
    it.slots[1].travel_minutes_from_prev = 5
    assert any("a → b" in v.message and "drive=30 phút" in v.message for v in fabrication_with_facts(it, facts))
    it = Itinerary(slots=[slot(start="11:30", end="13:30")])
    messages = [v.message for v in validate_with_facts(it, profile, {}, facts)]
    assert any("08:00-12:00" in text and "13:00-17:00" in text for text in messages)
