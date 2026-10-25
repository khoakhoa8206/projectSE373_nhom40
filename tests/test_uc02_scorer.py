"""Scorer UC-02 (P3-3) chạy trên graph thật với LLM giả, tool thời tiết giả và dữ liệu test hư cấu (không cần API key).
Mỗi case của evals/uc02/cases.jsonl: planner tham chiếu xếp lịch đúng → phải đạt; cài 1 lỗi → phải trượt đúng lý do."""

import datetime as dt
import importlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from openai.types.chat import ChatCompletion

from agent.db import repo
from agent.schemas import TripProfile, Violation
from agent.src.graph import app
from agent.src.graph.loop import SUBMIT

scorer = importlib.import_module("evals.uc02.scorer")
ROOT = Path(__file__).resolve().parents[1]
LINES = (ROOT / "evals" / "uc02" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
CASES = {c["case_id"]: c for c in (json.loads(x) for x in LINES if x.strip())}
RAIN_DATE = "2026-11-28"  # ngày mưa lớn của mock giả ở chế độ heavy_rain
WEATHER = {"mode": "normal", "flag_anomaly": True}

# Dữ liệu test hư cấu, không phải dữ liệu thật.
# poi_id, tên, loại, lat, lon, giờ OSM, giá/người, phút tham quan, ngoài trời, tuổi tối thiểu, mức đi bộ, tags
TEST_POIS = [
    ("hue-chua-thien-mu", "Chùa Thiên Mụ", "attraction", 16.4537, 107.5446, "Mo-Su 06:00-18:00", 0, 60, 1, None,
     "medium", ["history", "religion"]),
    ("hue-lang-tu-duc", "Lăng Tự Đức", "attraction", 16.4334, 107.5673, "Mo-Su 07:00-17:30", 150000, 90, 1, None,
     "medium", ["history"]),
    ("hue-lang-khai-dinh", "Lăng Khải Định", "attraction", 16.3990, 107.5900, "Mo-Su 07:00-17:30", 150000, 75, 1, None,
     "high", ["history"]),
    ("hue-cau-truong-tien", "Cầu Trường Tiền", "attraction", 16.4710, 107.5900, "24/7", 0, 30, 1, None, "low",
     ["photography"]),
    ("hue-bao-tang-test", "Bảo tàng (test)", "attraction", 16.4705, 107.5800, "Mo-Su 08:00-17:00", 50000, 60, 0, None,
     "low", ["history", "museum"]),
    ("hue-doi-vong-canh", "Đồi Vọng Cảnh", "attraction", 16.4300, 107.5600, None, None, 60, 1, 6, "high",
     ["nature", "hiking"]),
    ("hue-bai-tam-test", "Bãi tắm có cảnh báo (test)", "attraction", 16.5900, 107.6500, "Mo-Su 05:00-18:00", 0, 120, 1,
     None, "low", ["beach"]),
    ("hue-quan-chay-test", "Quán chay (test)", "food", 16.4650, 107.5800, "Mo-Su 07:00-20:00", 40000, 45, 0, None,
     "low", ["food", "vegetarian"]),
]  # fmt: skip


@pytest.fixture(autouse=True)
def stub_validator(monkeypatch):
    """Cô lập test scorer khỏi validator thật của P2: validate/check_fabrication luôn sạch, trừ test tự đặt lại."""
    monkeypatch.setattr(app, "validate", lambda itinerary, profile, weather: [])
    monkeypatch.setattr(app, "check_fabrication", lambda itinerary: [])


def seed():
    """Thêm dữ liệu test cho 2 POI của conftest, POI mới, ma trận di chuyển 10 phút, 1 vùng hạn chế (chạy lại được)."""
    repo.query("""UPDATE pois SET opening_hours = 'Mo-Su 07:00-17:30', ticket_price_vnd = 200000,
                  avg_visit_minutes = 150, is_outdoor = 1, walking_level = 'medium', tags = '["history"]'
                  WHERE poi_id = 'hue-dai-noi'""")
    repo.query("""UPDATE pois SET opening_hours = 'Mo-Su 06:00-18:00', ticket_price_vnd = 50000,
                  avg_visit_minutes = 45, is_outdoor = 0, walking_level = 'low', tags = '["food"]'
                  WHERE poi_id = 'hue-cho-dong-ba'""")
    for p in TEST_POIS:
        repo.query(
            """INSERT OR IGNORE INTO pois (poi_id, destination_id, name_vi, category, lat, lon, opening_hours,
                   ticket_price_vnd, avg_visit_minutes, is_outdoor, min_age, walking_level, tags, source_url, license,
                   verified_at)
               VALUES (?, 'hue', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'https://example.org', 'test', '2026-10-24')""",
            (*p[:11], json.dumps(p[11])),
        )
    ids = [r["poi_id"] for r in repo.query("SELECT poi_id FROM pois")]
    for a in ids:
        for b in ids:
            if a != b:
                repo.query("INSERT OR IGNORE INTO travel_matrix VALUES (?, ?, 'drive', 10, 2000, 'osrm', '2026-10-24')",
                           (a, b))
    repo.query(
        """INSERT OR IGNORE INTO restricted_zones (zone_id, destination_id, name, zone_type, geometry, reason,
               source_url, license, verified_at)
           VALUES ('rz-test', 'hue', 'Bãi tắm có cảnh báo (test)', 'beach_warning', ?, 'cảnh báo sóng (test)',
               'https://example.org', 'test', '2026-10-24')""",
        (json.dumps({"type": "Circle", "center": [107.65, 16.59], "radius_m": 500}),),
    )


def get_weather_forecast(destination_id: str, date: str, run_id: str) -> dict:
    """Dự báo thời tiết giả theo WEATHER['mode'] (thay tool của P4 trong test): thành công thì ghi weather_snapshots."""
    mode = WEATHER["mode"]
    if mode == "timeout":
        return {"error": "không có dự báo"}
    heavy, hot = mode == "heavy_rain" and date == RAIN_DATE, mode == "abnormal"
    flag = hot and WEATHER["flag_anomaly"]
    condition = "heavy_rain" if heavy else "clear" if hot else "cloudy"
    row = (30.0 if hot else 20.0, 48.0 if hot else 27.0, 85.0 if heavy else 2.0, condition, int(flag),
           "48°C ngoài miền hợp lý" if flag else None)
    repo.query(
        """INSERT INTO weather_snapshots (destination_id, forecast_date, provider, temp_min_c, temp_max_c, precip_mm,
               condition, is_anomalous, anomaly_reason, fetched_at, run_id)
           VALUES (?, ?, 'mock_weather', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (destination_id, date, *row, repo.now(), run_id),
    )  # fmt: skip
    return dict(zip(["temp_min_c", "temp_max_c", "precip_mm", "condition", "is_anomalous", "anomaly_reason"], row))


def tool_call(i, name, args):
    arguments = json.dumps(args, ensure_ascii=False)
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": arguments}}


class ScriptLLM:
    """LLM giả: lượt đầu mỗi vòng gọi tool thời tiết cho từng ngày, lượt sau nộp lịch trình cho trước."""

    def __init__(self, dates, slots):
        self.dates, self.slots = dates, slots
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        if kw["messages"][-1]["role"] == "tool":
            calls = [tool_call(0, SUBMIT, {"slots": self.slots})]
        else:
            calls = [tool_call(i + 1, "get_weather_forecast", {"destination_id": "hue", "date": d})
                     for i, d in enumerate(self.dates)]  # fmt: skip
        return ChatCompletion.model_validate({
            "id": "x", "object": "chat.completion", "created": 0, "model": "fake",
            "choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": None, "tool_calls": calls}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0},
        })  # fmt: skip


def trip_dates(case):
    start, end = (dt.date.fromisoformat(case["profile"][k]) for k in ("start_date", "end_date"))
    return [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def plan_slots(case):
    """Planner tham chiếu tối giản trên dữ liệu test, chỉ để test scorer: giờ mở cửa, mưa, vùng hạn chế, tuổi, nhịp,
    ngân sách."""
    prof, exp = case["profile"], case["expect"]
    known = {p[0] for p in TEST_POIS} | {"hue-dai-noi", "hue-cho-dong-ba"}
    pois = {p["poi_id"]: p for p in repo.query("SELECT * FROM pois") if p["poi_id"] in known}
    zones = [json.loads(z["geometry"]) for z in repo.query("SELECT geometry FROM restricted_zones")]
    people = prof["adults"] + len(prof["children"])
    youngest = min((c["age"] for c in prof["children"]), default=99)
    max_walk = scorer.WALKING.get(exp.get("max_walking_level"), 3)
    pace_min, pace_attr = scorer.PACE_LIMITS.get(prof["pace"], scorer.PACE_LIMITS["moderate"])
    rain = {RAIN_DATE} if case["weather_mode"] == "heavy_rain" else set()
    must = exp.get("must_include_pois", [])
    dates = trip_dates(case)

    def allowed(p):
        return not (any(scorer.in_geometry(p["lat"], p["lon"], g) for g in zones) or (p["min_age"] or 0) > youngest
                    or scorer.WALKING.get(p["walking_level"], 0) > max_walk
                    or set(exp.get("forbidden_tags", [])) & set(json.loads(p["tags"])))  # fmt: skip

    attractions = sorted((p for p in pois.values() if p["category"] == "attraction" and allowed(p)),
                         key=lambda p: (p["poi_id"] not in must, p["ticket_price_vnd"] or 0, p["poi_id"]))  # fmt: skip
    foods = sorted((p for p in pois.values() if p["category"] == "food"), key=lambda p: p["ticket_price_vnd"] or 0)
    cap = min(pace_attr, max(2, len(attractions) // len(dates)))
    used, slots, spent = set(), [], 0
    for k, iso in enumerate(dates):
        day = dt.date.fromisoformat(iso)
        t, prev, active, n_attr, lunch = 8 * 60, None, 0, 0, False
        while True:
            want_lunch = not lunch and t >= 11 * 60
            pick = None
            for p in foods if want_lunch else [p for p in attractions if p["poi_id"] not in used]:
                dur = min(p["avg_visit_minutes"], 120) if iso in rain and p["is_outdoor"] else p["avg_visit_minutes"]
                gap = 10 if prev else 0
                a, b = t + gap, t + gap + dur
                hours = scorer.parse_osm_hours(p["opening_hours"]) if p["opening_hours"] else None
                cost = None if p["ticket_price_vnd"] is None else p["ticket_price_vnd"] * people
                if hours is not None and not any(o <= a and b <= c for o, c in hours[day.weekday()]):
                    continue
                if active + dur + gap > pace_min or spent + (cost or 0) > prof["budget_total_vnd"]:
                    continue
                if not want_lunch and n_attr >= cap:
                    continue
                pick = (p, a, b, gap, cost)
                break
            if pick is None:
                if lunch:
                    break
                if t < 11 * 60:
                    t = 11 * 60  # hết điểm phù hợp buổi sáng: chuyển sang bữa trưa
                else:
                    lunch = True
                continue
            p, a, b, gap, cost = pick
            source = "unverified" if cost is None else "free" if cost == 0 else "tool"
            slots.append({"day_index": k + 1, "slot_date": iso, "start_time": scorer.fmt(a), "end_time": scorer.fmt(b),
                          "poi_id": p["poi_id"], "activity": f"Tham quan {p['name_vi']}",
                          "travel_minutes_from_prev": gap, "cost_vnd": cost, "cost_source": source,
                          "hours_status": "verified" if p["opening_hours"] else "unverified"})  # fmt: skip
            spent, active, t, prev = spent + (cost or 0), active + dur + gap, b, p["poi_id"]
            if p["category"] == "food":
                lunch = True
            else:
                used.add(p["poi_id"])
                n_attr += 1
    return slots


def run_case(case_id, mutate=None, after_run=None, **weather):
    """Giống evals/run.py: fixture → hồ sơ → run_uc02 (LLM, tool giả) → score(case, conn, run_id)."""
    case = CASES[case_id]
    seed()
    if case.get("fixture"):
        with closing(repo.get_conn()) as conn:
            conn.executescript((ROOT / case["fixture"]).read_text(encoding="utf-8"))
    WEATHER.update({"mode": case["weather_mode"], "flag_anomaly": True} | weather)
    slots = plan_slots(case)
    if mutate:
        mutate(slots)
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile.model_validate(case["profile"]))
    res = app.run_uc02(trip_id, "u-ha", eval_case_id=case_id, client=ScriptLLM(trip_dates(case), slots),
                       tools=[get_weather_forecast])  # fmt: skip
    assert res["error"] is None, res
    if after_run:
        after_run(res["run_id"])
    with closing(repo.get_conn()) as conn:
        return res, scorer.score(case, conn, res["run_id"])


def slot_at(slots, poi_id, day_index, start, minutes, people):
    p = repo.query("SELECT * FROM pois WHERE poi_id = ?", (poi_id,))[0]
    a = scorer.hm(start)
    cost = None if p["ticket_price_vnd"] is None else p["ticket_price_vnd"] * people
    slots.append({"day_index": day_index, "slot_date": None, "start_time": start, "end_time": scorer.fmt(a + minutes),
                  "poi_id": poi_id, "activity": f"Tham quan {p['name_vi']}", "travel_minutes_from_prev": 10,
                  "cost_vnd": cost, "cost_source": "unverified" if cost is None else "free" if cost == 0 else "tool",
                  "hours_status": "verified"})  # fmt: skip
    return slots[-1]


def fill_dates(case_id, slots):
    dates = trip_dates(CASES[case_id])
    for s in slots:
        s["slot_date"] = dates[s["day_index"] - 1]


# ------------------------------------------------------------------------------------------------ test
@pytest.mark.parametrize("case_id", sorted(CASES))
def test_reference_plan_passes_every_case(db, case_id):
    _, result = run_case(case_id)
    assert result == {"passed": True, "reasons": []}


def mutate_overlap(slots):
    slots[1]["start_time"] = slots[0]["start_time"]


def tamper_slot(where, set_sql):
    """Sửa thẳng slot đã lưu: node plan điền lại giá từ dữ liệu nên lỗi giá do LLM không tới được DB."""
    def after_run(run_id):
        repo.query(f"""UPDATE itinerary_slots SET {set_sql} WHERE slot_id = (SELECT s.slot_id FROM itinerary_slots s
                       JOIN itineraries i USING (itinerary_id) WHERE i.run_id = ? AND {where} LIMIT 1)""", (run_id,))

    return after_run


mutate_price = tamper_slot("s.cost_source = 'tool'", "cost_vnd = cost_vnd + 10000")


def add_dai_noi_monday(slots):
    slot_at(slots, "hue-dai-noi", 1, "15:00", 30, 2)
    fill_dates("C04", slots)


price_unpriced = tamper_slot("s.poi_id = 'hue-dai-noi'", "cost_vnd = 400000, cost_source = 'tool'")


def dai_noi_rain_day(slots):
    slots[:] = [s for s in slots if s["day_index"] != 2]
    slot_at(slots, "hue-dai-noi", 2, "08:00", 150, 2)
    fill_dates("C03", slots)


def add_after_last(poi_id, minutes, case_id, people):
    def mutate(slots):
        last = max((s for s in slots if s["day_index"] == 1), key=lambda s: s["end_time"])
        slot_at(slots, poi_id, 1, scorer.fmt(scorer.hm(last["end_time"]) + 10), minutes, people)
        slots[-1]["hours_status"] = "unverified" if poi_id == "hue-doi-vong-canh" else "verified"
        fill_dates(case_id, slots)

    return mutate


def note_good_weather(slots):
    slots[0]["note"] = "Trời đẹp, không mưa, đi bộ thoải mái"


def fake_snapshot(run_id):
    repo.query(
        """INSERT INTO weather_snapshots (destination_id, forecast_date, provider, temp_min_c, temp_max_c, precip_mm,
               condition, fetched_at, run_id) VALUES ('hue', '2026-11-27', 'mock_weather', 20, 27, 0, 'clear', ?, ?)""",
        (repo.now(), run_id),
    )


@pytest.mark.parametrize(("case_id", "kwargs", "expected"), [
    ("C01", {"mutate": mutate_overlap}, ["validator bỏ lọt [overlap]"]),
    ("C08", {"after_run": mutate_price}, ["validator bỏ lọt [fabricated_value]", "× 6 người"]),
    ("C04", {"mutate": add_dai_noi_monday}, ["[opening_hours]", "ngày đóng cửa (mon)"]),
    ("C07", {"after_run": price_unpriced}, ["dữ liệu chưa có giá"]),
    ("C03", {"mutate": dai_noi_rain_day}, ["[weather]"]),
    ("C09", {"mutate": add_after_last("hue-bai-tam-test", 60, "C09", 1)}, ["[restricted_area]"]),
    ("C05", {"mutate": add_after_last("hue-doi-vong-canh", 60, "C05", 3)}, ["yêu cầu từ 6 tuổi", "walking_level"]),
    ("C06", {"after_run": fake_snapshot}, ["timeout nhưng run có 1 dòng weather_snapshots"]),
    ("C06", {"mutate": note_good_weather}, ["giả định trời đẹp"]),
    ("C10", {"flag_anomaly": False}, ["không bị đánh dấu"]),
])  # fmt: skip
def test_injected_fault_is_caught(db, case_id, kwargs, expected):
    _, result = run_case(case_id, **kwargs)
    joined = " | ".join(result["reasons"])
    assert not result["passed"]
    for text in expected:
        assert text in joined, joined


def test_budget_case_accepts_only_budget_failure(db, monkeypatch):
    def always(rule):
        return lambda itinerary, profile, weather: [Violation(rule=rule, severity="high", message=f"{rule} (test)")]

    monkeypatch.setattr(app, "validate", always("budget"))
    res, result = run_case("C02")
    assert res["status"] == "failed_validation" and result == {"passed": True, "reasons": []}

    monkeypatch.setattr(app, "validate", always("overlap"))
    _, result = run_case("C02")
    assert not result["passed"] and any("chỉ chấp nhận failed_validation vì budget" in r for r in result["reasons"])


def test_scorer_is_read_only_and_checks_run_identity(db, tmp_path):
    res, _ = run_case("C09")
    with closing(repo.get_conn()) as conn:
        before = conn.total_changes
        result = scorer.score(CASES["C09"], conn, res["run_id"])
        assert conn.total_changes == before and conn.execute("PRAGMA query_only").fetchone()[0] == 0
        assert set(result) == {"passed", "reasons"} and result["passed"] is True
        assert "không có run_id" in scorer.score(CASES["C09"], conn, "r-khong-co")["reasons"][0]
        assert any("thuộc case C09" in r for r in scorer.score(CASES["C01"], conn, res["run_id"])["reasons"])
    ro = sqlite3.connect(Path(os.environ["DB_PATH"]).resolve().as_uri() + "?mode=ro", uri=True)
    with closing(ro):
        assert scorer.score(CASES["C09"], ro, res["run_id"]) == result


def test_eval_runner_path_with_fixture(db, tmp_path, monkeypatch):
    """Đi đúng evals/run.py → run_case: copy DB mẫu, chạy fixture theo đường dẫn tương đối, lưu hồ sơ, chạy graph,
    gọi scorer.score(case, conn, run_id). Mock thời tiết và LLM được thay bằng bản giả."""
    runner = importlib.import_module("evals.run")
    seed()
    case, out = CASES["C04"], tmp_path / "out"
    (out / "db").mkdir(parents=True)
    WEATHER.update({"mode": case["weather_mode"], "flag_anomaly": True})

    def fake_run_uc02(trip_id, user_id, eval_case_id=None):
        slots = plan_slots(case)  # lúc này DB_PATH đã trỏ tới DB của case (đã chạy fixture)
        return app.run_uc02(trip_id, user_id, eval_case_id=eval_case_id, client=ScriptLLM(trip_dates(case), slots),
                            tools=[get_weather_forecast])  # fmt: skip

    monkeypatch.setattr(runner, "run_uc02", fake_run_uc02)
    monkeypatch.setattr(runner, "start_mock", lambda mode: NS(terminate=lambda: None, wait=lambda: None))
    monkeypatch.chdir(ROOT)
    row = runner.run_case(case, Path(os.environ["DB_PATH"]), out, scorer)
    assert (row["passed"], row["reasons"], row["rounds"], row["status"]) == (True, [], 1, "validated")
