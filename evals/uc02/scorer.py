"""Scorer UC-02 (P3-3): chấm 1 lượt chạy bằng dữ liệu trong DB, chỉ đọc.

    score(case, conn, run_id) -> {"passed": bool, "reasons": [str]}

- `case`: 1 dòng của evals/uc02/cases.jsonl. `conn`: kết nối tới DB của case (evals/run.py mở bằng repo.get_conn()).
- Chỉ chạy SELECT/PRAGMA đọc; trong lúc chấm bật `PRAGMA query_only` để SQLite từ chối mọi lệnh ghi, xong trả lại.
- Đọc các bảng của agent/db/schema.sql: runs, trips, trip_profiles, itineraries, itinerary_slots,
  validation_violations, pois, travel_matrix, restricted_zones, weather_snapshots, trace_events.
- Mọi phép kiểm là code, không gọi LLM. Quy ước dùng để chấm: xem evals/uc02/README.md.
"""

import json
import math
import re
import unicodedata
from contextlib import contextmanager
from datetime import date, timedelta

# Ngưỡng dùng để chấm; phải khớp validator của P2 (agent/src/validation/validator.py).
PACE_LIMITS = {"relaxed": (360, 3), "moderate": (480, 5), "packed": (600, 7)}  # phút hoạt động, số điểm tham quan/ngày
TRAVEL_TOLERANCE_MIN = 2
RAIN_MAX_OUTDOOR_MIN = 120
HEAVY_RAIN_MM = 50.0
MAX_ROUNDS = 4
WEATHER_TOOL = "get_weather_forecast"
SKILL = "itinerary-planning"
VALIDATOR_RULES = ("overlap", "opening_hours", "overload", "budget", "weather", "restricted_area", "fabricated_value")
WALKING = {"low": 1, "medium": 2, "high": 3}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
NO_FORECAST = ("không có dự báo", "chưa có dự báo", "no forecast")
GOOD_WEATHER_CLAIM = re.compile(r"trời đẹp|nắng đẹp|không mưa|thời tiết tốt|sunny|clear sky|no rain", re.IGNORECASE)


# ----------------------------------------------------------------------------------------------- tiện ích
def fold(text):
    """Bỏ dấu, chữ thường: so khớp không phân biệt dấu."""
    text = unicodedata.normalize("NFC", text or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower()


def hm(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def fmt(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


_OSM_DAYS = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}
_OSM_RULE = re.compile(
    r"(?:(?P<days>[A-Z][a-z](?:-[A-Z][a-z])?(?:,[A-Z][a-z](?:-[A-Z][a-z])?)*)\s+)?"
    r"(?P<times>off|closed|\d{1,2}:\d{2}-\d{1,2}:\d{2}(?:,\s*\d{1,2}:\d{2}-\d{1,2}:\d{2})*)"
)


def parse_osm_hours(text):
    """Tập con cú pháp OSM opening_hours: '24/7', 'Mo-Su 07:00-17:30', 'Tu-Su 08:00-17:00; Mo off', nhiều khung giờ.
    Quy tắc sau ghi đè quy tắc trước; ngày không nhắc tới = đóng cửa; bỏ qua quy tắc 'PH'. Cú pháp khác → ValueError."""
    out = {d: [] for d in range(7)}
    for rule in (r.strip() for r in text.split(";")):
        if not rule or rule.startswith("PH"):
            continue
        if rule == "24/7":
            out = {d: [(0, 1440)] for d in range(7)}
            continue
        m = _OSM_RULE.fullmatch(rule)
        if not m:
            raise ValueError(f"không đọc được quy tắc {rule!r}")
        days = list(range(7))
        if m["days"]:
            days = []
            for part in m["days"].split(","):
                a, _, b = part.partition("-")
                i, j = _OSM_DAYS[a], _OSM_DAYS[b or a]
                days += [(i + k) % 7 for k in range((j - i) % 7 + 1)]
        windows = []
        if m["times"] not in ("off", "closed"):
            for span in m["times"].split(","):
                a, b = (hm(x) for x in span.split("-"))
                windows.append((a, b if b > a else 1440))
        for d in days:
            out[d] = list(windows)
    return out


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def in_ring(lon, lat, ring):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def in_geometry(lat, lon, geom):
    """GeoJSON Polygon/MultiPolygon ([lon, lat]) hoặc {"type": "Circle", "center": [lon, lat], "radius_m": ...}."""
    kind = geom.get("type")
    if kind == "Feature":
        return in_geometry(lat, lon, geom["geometry"])
    if kind == "Circle":
        clon, clat = geom["center"]
        return haversine_m(lat, lon, clat, clon) <= geom["radius_m"]
    polys = [geom["coordinates"]] if kind == "Polygon" else geom["coordinates"] if kind == "MultiPolygon" else []
    if not polys and kind not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"geometry {kind!r} chưa hỗ trợ")
    return any(
        in_ring(lon, lat, [tuple(p[:2]) for p in poly[0]])
        and not any(in_ring(lon, lat, [tuple(p[:2]) for p in hole]) for hole in poly[1:])
        for poly in polys
    )


def zone_active(zone, day):
    """active_from/active_to: NULL = luôn hiệu lực; nhận 'YYYY-MM-DD' hoặc 'MM-DD' (theo mùa, có thể vắt qua năm)."""
    lo, hi = zone.get("active_from"), zone.get("active_to")
    if not lo and not hi:
        return True
    if all(x is None or len(x) == 5 for x in (lo, hi)):
        md, lo, hi = day.strftime("%m-%d"), lo or "01-01", hi or "12-31"
        return lo <= md <= hi if lo <= hi else md >= lo or md <= hi
    return (lo or "0000") <= day.isoformat() <= (hi or "9999")


def tags_of(raw):
    try:
        value = json.loads(raw or "[]")
        return {str(t).lower() for t in value} if isinstance(value, list) else set()
    except ValueError:
        return {t.strip().lower() for t in str(raw).split(",") if t.strip()}


@contextmanager
def read_only(conn):
    """Bật PRAGMA query_only trong lúc chấm và trả lại giá trị cũ (kể cả khi lỗi)."""
    prev = conn.execute("PRAGMA query_only").fetchone()[0]
    conn.execute("PRAGMA query_only = 1")
    try:
        yield
    finally:
        conn.execute(f"PRAGMA query_only = {int(prev)}")


def rows(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ----------------------------------------------------------------------------------------------- API
def score(case, conn, run_id):
    """Chấm 1 run của 1 case. Trả đúng {"passed": bool, "reasons": [str]}; reasons rỗng ⇔ passed."""
    detail = score_detailed(case, conn, run_id)
    return {"passed": detail["passed"], "reasons": detail["reasons"]}


def score_detailed(case, conn, run_id):
    """Như score(), thêm notes (ghi chú không làm trượt) và metrics để gỡ lỗi."""
    with read_only(conn):
        out = _Scorer(case, conn, run_id).run()
    out["passed"] = not out["reasons"]
    return out


class _Scorer:
    def __init__(self, case, conn, run_id):
        self.case, self.conn, self.run_id = case, conn, run_id
        self.exp, self.prof = case.get("expect", {}), case["profile"]
        self.reasons, self.notes, self.violations, self.metrics = [], [], [], {}

    def q(self, sql, params=()):
        return rows(self.conn, sql, params)

    def fail(self, msg):
        self.reasons.append(msg)

    def found(self, rule, msg):  # vi phạm ràng buộc validator lẽ ra phải bắt
        self.violations.append((rule, msg))

    def result(self):
        return {
            "case_id": self.case.get("case_id"),
            "run_id": self.run_id,
            "reasons": self.reasons,
            "notes": self.notes,
            "violations_found": [f"[{r}] {m}" for r, m in self.violations],
            "metrics": self.metrics,
        }

    # ------------------------------------------------------------------------------------------- luồng chấm
    def run(self):
        if not self.load():
            return self.result()
        self.check_profile_and_dates()
        self.check_slots()
        self.check_totals()
        self.check_status()
        self.check_weather()
        self.check_trace()
        self.check_case_expect()
        return self.result()

    def load(self):
        q = self.q
        run = q("SELECT * FROM runs WHERE run_id = ?", (self.run_id,))
        if not run:
            self.fail(f"không có run_id {self.run_id!r} trong bảng runs")
            return False
        self.run_row = run[0]
        cid = self.case.get("case_id")
        if self.run_row["uc"] != "UC-02":
            self.fail(f"run {self.run_id} thuộc {self.run_row['uc']}, không phải UC-02")
        if self.run_row["eval_case_id"] and cid and self.run_row["eval_case_id"] != cid:
            self.fail(f"run {self.run_id} thuộc case {self.run_row['eval_case_id']}, không phải {cid}")
        if self.run_row["status"] != "succeeded":
            errors = q(
                "SELECT node, error FROM trace_events WHERE run_id = ? AND kind = 'error' ORDER BY seq", (self.run_id,)
            )
            first = f": {errors[0]['node']} – {errors[0]['error']}" if errors else ""
            self.fail(f"run kết thúc với status {self.run_row['status']!r}{first}")
        its = q("SELECT * FROM itineraries WHERE run_id = ? ORDER BY version DESC", (self.run_id,))
        if not its:
            self.fail("run không lưu lịch trình nào (bảng itineraries)")
            return False
        self.it = its[0]
        self.slots = q(
            "SELECT * FROM itinerary_slots WHERE itinerary_id = ? ORDER BY day_index, start_time",
            (self.it["itinerary_id"],),
        )
        self.vios = q("SELECT * FROM validation_violations WHERE itinerary_id = ?", (self.it["itinerary_id"],))
        self.pois = {p["poi_id"]: p for p in q("SELECT * FROM pois")}
        self.travel = {
            (r["a"], r["b"]): r["m"]
            for r in q(
                "SELECT from_poi_id AS a, to_poi_id AS b, MIN(minutes) AS m FROM travel_matrix"
                " GROUP BY from_poi_id, to_poi_id"
            )
        }
        self.zones = q("SELECT * FROM restricted_zones")
        self.snaps = q("SELECT * FROM weather_snapshots WHERE run_id = ? ORDER BY snapshot_id", (self.run_id,))
        self.trace = q(
            "SELECT kind, name, args, result, error FROM trace_events WHERE run_id = ? ORDER BY seq", (self.run_id,)
        )
        trip = q("SELECT destination_id FROM trips WHERE trip_id = ?", (self.it["trip_id"],))
        if trip and trip[0]["destination_id"] != "hue":
            self.fail(f"trip có destination_id {trip[0]['destination_id']!r}, case chỉ dành cho Huế")
        self.saved_profile = q("SELECT * FROM trip_profiles WHERE profile_id = ?", (self.it["profile_id"],))
        return True

    # ------------------------------------------------------------------------------------------- hồ sơ, ngày
    def check_profile_and_dates(self):
        p = self.prof
        if self.saved_profile:
            sp = self.saved_profile[0]
            for col in ("start_date", "end_date", "adults", "budget_total_vnd", "pace"):
                if sp[col] != p.get(col):
                    self.fail(f"hồ sơ trong DB ({col} = {sp[col]!r}) khác case ({p.get(col)!r}): harness nạp sai hồ sơ")
        self.start, self.end = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
        self.n_days = (self.end - self.start).days + 1
        if WEEKDAYS[self.start.weekday()] != self.case.get("start_weekday"):
            self.fail(
                f"case lỗi: start_date {self.start} là {WEEKDAYS[self.start.weekday()]}, "
                f"start_weekday ghi {self.case.get('start_weekday')!r}"
            )
        self.days = {}
        for s in self.slots:
            want = self.start + timedelta(days=s["day_index"] - 1)
            if s["day_index"] > self.n_days:
                self.fail(f"slot {s['slot_id']}: day_index {s['day_index']} vượt số ngày của chuyến ({self.n_days})")
            elif s["slot_date"] != want.isoformat():
                self.fail(f"slot {s['slot_id']}: slot_date {s['slot_date']} không khớp ngày {s['day_index']} ({want})")
            self.days.setdefault(s["day_index"], []).append(s)
        missing = [d for d in range(1, self.n_days + 1) if d not in self.days]
        if missing:
            self.fail(f"lịch thiếu ngày {missing} (chuyến {self.n_days} ngày, mỗi ngày cần ít nhất 1 slot)")
        if self.exp.get("n_days") and self.n_days != self.exp["n_days"]:
            self.fail(f"case lỗi: chuyến {self.n_days} ngày, expect.n_days = {self.exp['n_days']}")

    # ------------------------------------------------------------------------------------------- từng slot
    def check_slots(self):
        p = self.prof
        kids = [c["age"] for c in p.get("children", [])]
        self.people = (p.get("adults") or 1) + len(kids)
        youngest = min(kids, default=None)
        pace_min, pace_attr = PACE_LIMITS.get(p.get("pace"), PACE_LIMITS["moderate"])
        hard = fold(" ".join(p.get("hard_constraints", [])) + " " + (p.get("mobility_notes") or ""))
        veg = "an chay" in hard or "vegetarian" in hard
        no_climb = any(k in hard for k in ("khong leo", "di lai kho", "no stairs"))
        max_walk = WALKING.get(self.exp.get("max_walking_level"), 3 if not no_climb else 2)
        rain = self.rain_dates()
        self.expected_total, self.unpriced_slots, self.priced_slots = 0, 0, 0
        hours_cache = {}
        for day_index in sorted(self.days):
            day = self.start + timedelta(days=day_index - 1)
            prev_end, prev_poi, active, n_attr = None, None, 0, 0
            for s in self.days[day_index]:
                tag = f"ngày {day_index} ({day}) {s['start_time']}-{s['end_time']} {s['poi_id'] or s['activity']}"
                a, b = hm(s["start_time"]), hm(s["end_time"])
                dur = b - a
                rep = s["travel_minutes_from_prev"]
                poi = self.pois.get(s["poi_id"]) if s["poi_id"] else None
                if s["poi_id"] and poi is None:
                    self.fail(f"{tag}: poi_id không có trong bảng pois")
                    continue
                # di chuyển và chồng giờ
                need = self.travel.get((prev_poi, s["poi_id"])) if prev_poi and s["poi_id"] else None
                if prev_end is not None:
                    if prev_poi and s["poi_id"] and prev_poi != s["poi_id"] and need is None:
                        self.notes.append(f"{tag}: travel_matrix không có cặp {prev_poi} → {s['poi_id']}")
                    if need is not None and (rep is None or rep < need - TRAVEL_TOLERANCE_MIN):
                        self.found(
                            "fabricated_value", f"{tag}: travel_minutes_from_prev = {rep}, dữ liệu là {need} phút"
                        )
                    gap = max(rep or 0, need or 0)
                    if a < prev_end + gap:
                        self.found(
                            "overlap", f"{tag}: bắt đầu trước {fmt(prev_end + gap)} (xong điểm trước + {gap} phút)"
                        )
                    active += gap
                active += dur
                prev_end, prev_poi = b, s["poi_id"] or prev_poi
                if poi is None:  # slot nghỉ / tự do
                    if s["cost_vnd"]:
                        self.found("fabricated_value", f"{tag}: slot không gắn POI nhưng có cost_vnd = {s['cost_vnd']}")
                    continue
                if poi["destination_id"] != "hue":
                    self.fail(f"{tag}: POI thuộc {poi['destination_id']!r}, không phải Huế")
                if poi["category"] == "attraction":
                    n_attr += 1
                tags = tags_of(poi["tags"])
                self.check_hours(tag, s, poi, day, a, b, hours_cache)
                self.check_cost(tag, s, poi)
                for z in self.zones:
                    try:
                        hit = zone_active(z, day) and in_geometry(poi["lat"], poi["lon"], json.loads(z["geometry"]))
                    except (ValueError, KeyError, TypeError) as e:
                        self.notes.append(f"vùng {z['zone_id']}: không đọc được geometry ({e})")
                        continue
                    if hit:
                        self.found("restricted_area", f"{tag}: nằm trong vùng hạn chế {z['zone_id']} ({z['reason']})")
                if day.isoformat() in rain and dur > RAIN_MAX_OUTDOOR_MIN:
                    if poi["is_outdoor"] == 1:
                        self.found(
                            "weather", f"{tag}: ngoài trời {dur} phút ngày mưa lớn (tối đa {RAIN_MAX_OUTDOOR_MIN})"
                        )
                    elif poi["is_outdoor"] is None:
                        self.notes.append(f"{tag}: is_outdoor = NULL, chưa kiểm được luật mưa")
                if youngest is not None and poi["min_age"] is not None and poi["min_age"] > youngest:
                    self.fail(f"{tag}: POI yêu cầu từ {poi['min_age']} tuổi, đoàn có trẻ {youngest} tuổi")
                if WALKING.get(poi["walking_level"], 0) > max_walk:
                    self.fail(
                        f"{tag}: walking_level = {poi['walking_level']!r} quá sức đoàn (tối đa "
                        f"{next(k for k, v in WALKING.items() if v == max_walk)})"
                    )
                for t in self.exp.get("forbidden_tags", []):
                    if t in tags:
                        self.fail(f"{tag}: có tag {t!r} không phù hợp với đoàn")
                if veg and poi["category"] == "food" and not tags & {"vegetarian", "chay"}:
                    self.fail(f"{tag}: đoàn ăn chay nhưng dữ liệu không ghi quán có món chay")
            if active > pace_min:
                self.found(
                    "overload", f"ngày {day_index}: {active} phút hoạt động, vượt {pace_min} của nhịp {p.get('pace')}"
                )
            if n_attr > pace_attr:
                self.found(
                    "overload", f"ngày {day_index}: {n_attr} điểm tham quan, vượt {pace_attr} của nhịp {p.get('pace')}"
                )
            need_attr = self.exp.get("min_attractions_per_day")
            if need_attr and self.it["status"] == "validated" and n_attr < need_attr:
                self.fail(f"ngày {day_index}: chỉ có {n_attr} điểm tham quan, kỳ vọng ≥ {need_attr}")

    def check_hours(self, tag, s, poi, day, a, b, cache):
        raw = poi["opening_hours"]
        if raw is None:
            if s["hours_status"] == "verified":
                self.found("fabricated_value", f"{tag}: dữ liệu chưa có giờ mở cửa nhưng hours_status = 'verified'")
            return
        if s["hours_status"] == "not_applicable" and poi["category"] != "lodging":
            self.fail(f"{tag}: hours_status = 'not_applicable' chỉ dùng cho slot không gắn POI hoặc lưu trú")
        if raw not in cache:
            try:
                cache[raw] = parse_osm_hours(raw)
            except ValueError as e:
                cache[raw] = None
                self.notes.append(f"{poi['poi_id']}: opening_hours {raw!r} ngoài tập cú pháp scorer đọc được ({e})")
        hours = cache[raw]
        if hours is not None and not any(o <= a and b <= c for o, c in hours[day.weekday()]):
            state = "đóng cửa cả ngày" if not hours[day.weekday()] else raw
            self.found("opening_hours", f"{tag}: ngoài giờ mở cửa {WEEKDAYS[day.weekday()]} ({state})")

    def check_cost(self, tag, s, poi):
        price, cost, src = poi["ticket_price_vnd"], s["cost_vnd"], s["cost_source"]
        if price is None:
            self.unpriced_slots += 1
            if src != "unverified" or cost is not None:
                self.found(
                    "fabricated_value",
                    f"{tag}: dữ liệu chưa có giá nhưng slot ghi cost_vnd = {cost}, cost_source = "
                    f"{src!r} (phải là NULL / 'unverified')",
                )
            return
        self.priced_slots += 1
        if poi["category"] == "lodging":  # đơn giá lưu trú chưa chốt trong hợp đồng: chỉ kiểm có giá
            self.expected_total += cost or 0
            return
        want = price * self.people
        self.expected_total += want
        if price == 0:
            if src == "unverified" or cost not in (0, None):
                self.found(
                    "fabricated_value", f"{tag}: POI miễn phí nhưng slot ghi cost_vnd = {cost}, cost_source = {src!r}"
                )
        elif src != "tool" or cost != want:
            self.found(
                "fabricated_value",
                f"{tag}: cost_vnd = {cost} ({src}) khác dữ liệu: {price} × {self.people} người = {want}",
            )

    # ------------------------------------------------------------------------------------------- tổng, trạng thái
    def check_totals(self):
        it, slot_sum = self.it, sum(s["cost_vnd"] or 0 for s in self.slots)
        if it["total_cost_vnd"] != slot_sum:
            self.fail(f"itineraries.total_cost_vnd = {it['total_cost_vnd']} khác tổng slot ({slot_sum})")
        has_unpriced = int(any(s["cost_source"] == "unverified" for s in self.slots))
        if it["has_unpriced_item"] != has_unpriced:
            self.fail(f"has_unpriced_item = {it['has_unpriced_item']} không khớp các slot (phải là {has_unpriced})")
        budget = self.prof.get("budget_total_vnd")
        if budget is not None and self.expected_total > budget:
            self.found("budget", f"tổng chi tính từ dữ liệu {self.expected_total} vượt ngân sách {budget}")
        self.metrics.update(
            {
                "total_cost_vnd": it["total_cost_vnd"],
                "expected_total_vnd": self.expected_total,
                "planner_rounds": it["planner_rounds"],
                "slots": len(self.slots),
                "unpriced_slots": self.unpriced_slots,
                "weather_snapshots": len(self.snaps),
            }
        )

    def check_status(self):
        status, rounds = self.it["status"], self.it["planner_rounds"]
        allowed = self.exp.get("status_in", ["validated"])
        if status not in allowed:
            self.fail(f"itineraries.status = {status!r}, kỳ vọng {allowed}")
        if not 1 <= rounds <= MAX_ROUNDS:
            self.fail(f"planner_rounds = {rounds}, phải trong 1..{MAX_ROUNDS}")
        open_rules = {v["rule"] for v in self.vios if v["resolved"] == 0}
        if status == "validated":
            if open_rules:
                self.fail(f"status = validated nhưng còn vi phạm chưa xử lý: {sorted(open_rules)}")
            self.reasons.extend(f"validator bỏ lọt [{r}] {m}" for r, m in self.violations)
        elif status == "failed_validation":
            if rounds != MAX_ROUNDS:
                self.notes.append(f"failed_validation sau {rounds} vòng (graph dừng ở vòng {MAX_ROUNDS})")
            if not open_rules:
                self.fail("status = failed_validation nhưng validation_violations không còn vi phạm nào resolved = 0")
            for r, m in self.violations:
                if r not in open_rules:
                    self.fail(f"vi phạm [{r}] chưa được báo trong validation_violations: {m}")
            if self.exp.get("budget_tight") and open_rules - {"budget"}:
                self.fail(
                    "case ngân sách thấp chỉ chấp nhận failed_validation vì budget, "
                    f"còn: {sorted(open_rules - {'budget'})}"
                )

    # ------------------------------------------------------------------------------------------- thời tiết, trace
    def rain_dates(self):
        return {
            s["forecast_date"]
            for s in self.snaps
            if not s["is_anomalous"] and (s["condition"] == "heavy_rain" or (s["precip_mm"] or 0) >= HEAVY_RAIN_MM)
        }

    def check_weather(self):
        mode = self.case.get("weather_mode", "normal")
        trip = {(self.start + timedelta(days=i)).isoformat() for i in range(self.n_days)}
        in_trip = [s for s in self.snaps if s["forecast_date"] in trip]
        calls = [e for e in self.trace if e["kind"] == "tool_call" and e["name"] == WEATHER_TOOL]
        if not calls:
            self.fail(f"trace không có lời gọi {WEATHER_TOOL}: agent không lấy dự báo thời tiết")
        providers = {s["provider"] for s in self.snaps}
        if providers - {"mock_weather"}:
            self.notes.append(f"weather_snapshots có provider {sorted(providers)}; eval phải dùng mock_weather")
        if mode == "timeout":
            if self.snaps:
                self.fail(f"mock-weather timeout nhưng run có {len(self.snaps)} dòng weather_snapshots")
            said = " ".join(f"{e['result'] or ''} {e['error'] or ''}" for e in calls)
            if calls and not any(fold(x) in fold(said) for x in NO_FORECAST):
                self.fail('tool thời tiết lỗi nhưng kết quả trả về không báo "không có dự báo"')
            for s in self.slots:
                if GOOD_WEATHER_CLAIM.search(s["note"] or "") or GOOD_WEATHER_CLAIM.search(s["activity"] or ""):
                    self.fail(
                        f"slot {s['slot_id']}: giả định trời đẹp khi không có dự báo ({s['note'] or s['activity']!r})"
                    )
            return
        if calls and not in_trip:
            self.fail("không có weather_snapshots nào cho các ngày của chuyến (tool không ghi kết quả)")
        if mode == "heavy_rain" and not self.rain_dates() & trip:
            self.fail(
                f"case mưa lớn không kiểm được: weather_snapshots không có ngày mưa lớn (condition = 'heavy_rain' "
                f"hoặc precip_mm ≥ {HEAVY_RAIN_MM:g}) trong chuyến"
            )
        if mode == "abnormal" and not any(s["is_anomalous"] for s in in_trip):
            self.fail("dữ liệu thời tiết bất thường không bị đánh dấu (weather_snapshots.is_anomalous = 0)")
        if mode == "normal" and any(s["is_anomalous"] for s in in_trip):
            self.notes.append("chế độ normal nhưng có snapshot bị đánh dấu bất thường")

    def check_trace(self):
        if not any(e["kind"] == "skill_use" and e["name"] == SKILL for e in self.trace):
            self.fail(f"trace không có skill_use {SKILL!r}")
        rounds = sum(1 for e in self.trace if e["kind"] == "guardrail" and e["name"] == "validator")
        if rounds and rounds != self.it["planner_rounds"]:
            self.notes.append(f"trace có {rounds} lần chạy validator, planner_rounds = {self.it['planner_rounds']}")

    # ------------------------------------------------------------------------------------------- kỳ vọng riêng
    def check_case_expect(self):
        exp, in_plan = self.exp, {s["poi_id"] for s in self.slots}
        for c in exp.get("closed", []):
            poi, wd = self.pois.get(c["poi_id"]), WEEKDAYS.index(c["weekday"])
            try:
                closed = (
                    poi is not None
                    and poi["opening_hours"] is not None
                    and not parse_osm_hours(poi["opening_hours"])[wd]
                )
            except ValueError:
                closed = False
            if not closed:
                self.fail(
                    f"fixture chưa có tác dụng: {c['poi_id']} không có trong pois hoặc không đóng cửa {c['weekday']}"
                )
            for s in self.slots:
                if s["poi_id"] == c["poi_id"] and date.fromisoformat(s["slot_date"]).weekday() == wd:
                    self.fail(f"{s['slot_date']}: xếp {c['poi_id']} vào ngày đóng cửa ({c['weekday']})")
        for pid in exp.get("null_price_pois", []):
            if pid not in self.pois or self.pois[pid]["ticket_price_vnd"] is not None:
                self.fail(f"fixture chưa có tác dụng: {pid} không có trong pois hoặc vẫn có giá")
        for pid in exp.get("must_include_pois", []):
            if pid not in in_plan:
                self.fail(f"lịch thiếu {pid} (người dùng yêu cầu trong hard_constraints)")
        if exp.get("min_unpriced_slots") and self.unpriced_slots < exp["min_unpriced_slots"]:
            self.fail(
                f"cần ≥ {exp['min_unpriced_slots']} slot thiếu giá để kiểm nhãn 'unverified', có {self.unpriced_slots}"
            )
        if exp.get("min_priced_slots") and self.priced_slots < exp["min_priced_slots"]:
            self.fail(
                f"cần ≥ {exp['min_priced_slots']} slot có giá để kiểm phép nhân theo số người, có {self.priced_slots}"
            )
