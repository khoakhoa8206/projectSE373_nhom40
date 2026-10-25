"""Kiểm bundle thật, routing lỗi và API/graph với LLM giả; không dùng đáp án eval."""

import csv
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletion

from agent.db import repo
from agent.db.init import init_db
from agent.schemas import Itinerary, Slot, TripProfile, Violation
from agent.src.api import server
from agent.src.graph import app
from agent.src.tools import weather
from scripts import load_destination
from scripts.build_travel_matrix import build, fetch_table
from scripts.check_destination import POI_PATH, check_matrix, check_pois, check_zones


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bundle.db"))
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    init_db()
    pois = check_pois(POI_PATH)
    zones = check_zones(POI_PATH.with_name("restricted_zones.geojson"))
    matrix = check_matrix(POI_PATH.with_name("travel_matrix.csv"), pois)
    repo.save_hue_destination(pois, zones, matrix)
    return pois, zones, matrix


def test_real_bundle_counts_and_repeat_load(bundle):
    pois, zones, matrix = bundle
    assert {c: sum(p.category == c for p in pois) for c in ("attraction", "food", "lodging")} == {
        "attraction": 15, "food": 10, "lodging": 5}
    assert len(zones) == 5 and len(matrix) == 900
    assert {r["mode"] for r in matrix} == {"drive"}
    assert len({(r["from_poi_id"], r["to_poi_id"]) for r in matrix}) == 900
    repo.save_hue_destination(pois, zones, matrix)
    assert repo.query("SELECT COUNT(*) AS n FROM pois")[0]["n"] == 30
    assert repo.query("SELECT COUNT(*) AS n FROM restricted_zones")[0]["n"] == 5
    assert repo.query("SELECT COUNT(*) AS n FROM travel_matrix")[0]["n"] == 900
    assert repo.query("SELECT COUNT(*) AS n FROM pois WHERE ticket_price_vnd IS NULL")[0]["n"] == 27  # 3 vé có nguồn báo chí


def test_cli_complete(bundle, monkeypatch):
    monkeypatch.setattr("sys.argv", ["load_destination.py", "hue", "--complete"])
    load_destination.main()


def test_matrix_rejects_bad_reference_and_negative(tmp_path):
    pois = check_pois(POI_PATH)
    path = tmp_path / "matrix.csv"
    with POI_PATH.with_name("travel_matrix.csv").open(encoding="utf-8", newline="") as file:
        original = next(csv.DictReader(file))
    for changes in ({"from_poi_id": "missing"}, {"minutes": "-1"}, {"mode": "teleport"}):
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(original))
            writer.writeheader()
            writer.writerow(original | changes)
        with pytest.raises(ValueError):
            check_matrix(path, pois)


def test_geojson_requires_source_and_closed_geometry(tmp_path):
    original = json.loads(POI_PATH.with_name("restricted_zones.geojson").read_text(encoding="utf-8"))
    original["features"][0]["properties"]["source_url"] = ""
    path = tmp_path / "zones.geojson"
    path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError):
        check_zones(path)


def test_bundle_rolls_back_all_tables(bundle):
    pois, zones, matrix = bundle
    modified = pois[0].model_copy(update={"name_vi": "Không được ghi khi lỗi"})
    bad = dict(matrix[0], to_poi_id="missing-id")
    with pytest.raises(Exception, match="FOREIGN KEY"):
        repo.save_hue_destination([modified], zones, [bad])
    assert repo.query("SELECT name_vi FROM pois WHERE poi_id=?", (pois[0].poi_id,))[0]["name_vi"] == pois[0].name_vi


def test_routing_timeout_retries_two_times():
    calls = []

    def fail(request):
        calls.append(request.url)
        raise httpx.ReadTimeout("test timeout", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as client, pytest.raises(httpx.ReadTimeout):
        fetch_table(check_pois(POI_PATH)[:1], client=client)
    assert len(calls) == 3  # một lần đầu + tối đa hai retry


def test_routing_allowlist_and_null_route():
    pois = check_pois(POI_PATH)[:1]
    with pytest.raises(ValueError):
        fetch_table(pois, "https://untrusted.example.org")
    rows, missing = build(pois, {"durations": [[None]], "distances": [[None]]})
    assert rows == [] and len(missing) == 1


class DemoLLM:
    """LLM giả chỉ kiểm pipeline, không dùng để báo chất lượng reasoning hay latency LLM thật."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if kwargs["messages"][-1]["role"] == "user":
            name, args = "get_opening_hours", {"poi_id": "hue-dai-noi", "date": "2026-11-27"}
        else:
            ids = ["hue-dai-noi", "hue-chua-thien-mu", "hue-lang-tu-duc"]
            name = "submit_result"
            args = {"slots": [{"day_index": index + 1, "slot_date": f"2026-11-{27 + index}",
                               "start_time": "09:00", "end_time": "10:00", "poi_id": pid,
                               "activity": "Tham quan dự kiến", "cost_vnd": None, "cost_source": "unverified",
                               "hours_status": "unverified", "note": "Chưa có giá; chưa xác minh điều kiện đi bộ."}
                              for index, pid in enumerate(ids)]}
        return ChatCompletion.model_validate({
            "id": "demo", "object": "chat.completion", "created": 0, "model": "fake-p2",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                         "tool_calls": [{"id": f"call-{name}", "type": "function", "function": {
                             "name": name, "arguments": json.dumps(args)}}]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        })


@pytest.mark.parametrize("condition", ["clear", "heavy_rain", "timeout"])
def test_api_three_days_with_real_tools(bundle, monkeypatch, condition):
    def respond(request):
        if condition == "timeout":
            raise httpx.ReadTimeout("test", request=request)
        return httpx.Response(200, json={"condition": condition, "temp_min_c": 23, "temp_max_c": 29, "precip_mm": 10})

    monkeypatch.setattr(weather, "_client", lambda: httpx.Client(
        base_url="http://127.0.0.1:8081", transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(app, "make_client", DemoLLM)
    client = TestClient(server.app)
    assert client.post("/api/session", json={"user_id": "u-ha"}).status_code == 200
    profile = {"start_date": "2026-11-27", "end_date": "2026-11-29", "adults": 1,
               "budget_total_vnd": 1000000, "pace": "relaxed", "interests": ["history"]}
    trip_id = client.post("/api/trips", json=profile).json()["trip_id"]
    result = client.post(f"/api/trips/{trip_id}/plan").json()
    assert result["status"] == "validated" and result["error"] is None
    itinerary = client.get(f"/api/trips/{trip_id}/itinerary").json()
    assert len(itinerary["slots"]) == 3 and itinerary["has_unpriced_item"] == 1
    # code điền giá từ dữ liệu (Đại Nội 200k + lăng Tự Đức 150k), Thiên Mụ chưa có giá -> has_unpriced_item
    assert itinerary["total_cost_vnd"] == 350000
    if condition == "timeout":
        assert all("không có dự báo" in s["note"] for s in itinerary["slots"])
    events = repo.query("SELECT name FROM trace_events WHERE run_id=? AND kind='tool_call'", (result["run_id"],))
    assert {"search_poi", "get_opening_hours", "get_weather_forecast"} <= {e["name"] for e in events}


def test_graph_keeps_best_not_last(db, monkeypatch):
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(start_date="2026-11-27", end_date="2026-11-27", adults=1))

    def plan(state, *args):
        round_ = state["round"] + 1
        slot = Slot(slot_id=f"{state['itinerary_id']}:d1-s1", day_index=1, slot_date="2026-11-27",
                    start_time="09:00", end_time="10:00", poi_id="hue-dai-noi", activity=f"Round {round_}",
                    cost_source="unverified", hours_status="unverified")
        it = Itinerary(itinerary_id=state["itinerary_id"], trip_id=state["trip_id"], profile_id=state["profile_id"],
                       run_id=state["run_id"], planner_rounds=round_, slots=[slot])
        return {"itinerary": it, "round": round_}

    monkeypatch.setattr(app, "plan", plan)
    monkeypatch.setattr(app, "validate", lambda it, *args: [
        Violation(rule="weather", severity="high", message=f"lỗi {i}") for i in range(it.planner_rounds)])
    monkeypatch.setattr(app, "check_fabrication", lambda it: [])
    result = app.run_uc02(trip_id, "u-ha", client=object(), tools=[])
    assert result["status"] == "failed_validation"
    stored = repo.itinerary_for_trip(trip_id)
    assert stored["planner_rounds"] == 4 and stored["slots"][0]["activity"] == "Round 1"
    assert len(stored["violations"]) == 1


def test_unknown_poi_does_not_crash_finalize(db, monkeypatch):
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile(start_date="2026-11-27", end_date="2026-11-27", adults=1))

    def plan(state, *args):
        round_ = state["round"] + 1
        slot = Slot(slot_id=f"{state['itinerary_id']}:d1-s1", day_index=1, slot_date="2026-11-27",
                    start_time="09:00", end_time="10:00", poi_id="unknown-fabricated-poi", activity="POI sai",
                    cost_source="unverified", hours_status="unverified")
        it = Itinerary(itinerary_id=state["itinerary_id"], trip_id=state["trip_id"], profile_id=state["profile_id"],
                       run_id=state["run_id"], planner_rounds=round_, slots=[slot])
        return {"itinerary": it, "round": round_}

    monkeypatch.setattr(app, "plan", plan)
    result = app.run_uc02(trip_id, "u-ha", client=object(), tools=[])
    assert result["error"] is None and result["status"] == "failed_validation"
    stored = repo.itinerary_for_trip(trip_id)
    assert stored["slots"][0]["poi_id"] is None
    assert "unknown-fabricated-poi" in stored["slots"][0]["note"]
    assert any(v["rule"] == "fabricated_value" for v in stored["violations"])
