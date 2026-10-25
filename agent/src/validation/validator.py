"""Kiểm nghiệp vụ bằng code. Core nhận facts thuần; facade giữ chữ ký P1, chỉ đọc snapshot DB."""

from collections import defaultdict
from datetime import timedelta
from itertools import pairwise

from agent.db import repo
from agent.schemas import Itinerary, TripProfile, Violation
from agent.src.tools.opening_hours import minutes, opening_intervals
from agent.src.validation.facts import active, contains

# Ngưỡng nhịp đi phải khớp evals/uc02/scorer.py (PACE_LIMITS): phút hoạt động + di chuyển, số điểm tham quan/ngày.
PACE_MINUTES = {"relaxed": 360, "moderate": 480, "packed": 600}
PACE_ATTRACTIONS = {"relaxed": 3, "moderate": 5, "packed": 7}
PACE_WALK_M = {"relaxed": 3000, "moderate": 6000, "packed": 10000}
HEAVY_RAIN_MM = 50.0


def party_size(profile: TripProfile) -> int:
    """Số người tính vé: giá vé dữ liệu là giá/người lớn, nhân cho cả đoàn (chưa có giá trẻ em có nguồn)."""
    return (profile.adults or 1) + len(profile.children)


def expected_cost(price, people):
    """(cost_vnd, cost_source) suy từ giá dữ liệu: null = chưa xác minh, 0 = miễn phí có nguồn."""
    if price is None:
        return None, "unverified"
    return (0, "free") if price == 0 else (price * people, "tool")


def _violation(rule, message, slot=None, severity="high"):
    return Violation(rule=rule, severity=severity, slot_id=slot.slot_id if slot else None, message=message)


def _pairs(facts, origin, target):
    return [row for row in facts["matrix"] if row["from_poi_id"] == origin and row["to_poi_id"] == target]


def fabrication_with_facts(itinerary: Itinerary, facts: dict, people: int = 1) -> list[Violation]:
    """Core thuần: mọi con số giá (giá dữ liệu × số người) và di chuyển phải đối chiếu facts."""
    violations = []
    previous = {}
    for slot in sorted(itinerary.slots, key=lambda s: (s.day_index, s.start_time)):
        if slot.poi_id is None:
            if slot.cost_vnd is not None or slot.cost_source != "unverified":
                violations.append(_violation("fabricated_value", "Slot nghỉ không có nguồn giá: để null/unverified.", slot))
            if slot.hours_status != "not_applicable":
                violations.append(_violation("fabricated_value", "Slot nghỉ phải có hours_status=not_applicable.", slot))
            continue
        poi = facts["pois"].get(slot.poi_id)
        if poi is None or not all(poi.get(k) for k in ("source_url", "license", "verified_at")):
            violations.append(_violation("fabricated_value", f"POI {slot.poi_id} không tồn tại/thiếu nguồn.", slot))
            previous[slot.day_index] = slot
            continue
        cost, source = expected_cost(poi["ticket_price_vnd"], people)
        if (slot.cost_vnd, slot.cost_source) != (cost, source):
            violations.append(_violation("fabricated_value", (
                f"Giá {slot.poi_id}: slot ghi cost_vnd={slot.cost_vnd} ({slot.cost_source}); dữ liệu: "
                f"cost_vnd={cost} ({source}), giá/người × {people} người."), slot))
        intervals = opening_intervals(poi["opening_hours"], slot.slot_date)
        if intervals is None and slot.hours_status != "unverified":
            violations.append(_violation("fabricated_value", "Giờ chưa biết/chưa parse được: hours_status=unverified.", slot))
        if slot.hours_status == "not_applicable":
            violations.append(_violation("fabricated_value", "POI không được bỏ qua kiểm giờ bằng not_applicable.", slot))
        prev = previous.get(slot.day_index)
        if prev and prev.poi_id != slot.poi_id:
            pairs = _pairs(facts, prev.poi_id, slot.poi_id)
            if not pairs or slot.travel_minutes_from_prev not in {p["minutes"] for p in pairs}:
                expected = ", ".join(f"{p['mode']}={p['minutes']} phút" for p in pairs) or "chưa có tuyến; đổi/giảm POI"
                violations.append(_violation("fabricated_value", (
                    f"Chặng {prev.poi_id} → {slot.poi_id} cùng ngày: travel_minutes_from_prev="
                    f"{slot.travel_minutes_from_prev}; cache có hướng: {expected}."), slot))
        elif slot.travel_minutes_from_prev not in (None, 0):
            violations.append(_violation("fabricated_value", "Không có chặng trước để xác minh thời gian di chuyển.", slot))
        previous[slot.day_index] = slot
    return violations


def validate_with_facts(itinerary: Itinerary, profile: TripProfile, weather: dict, facts: dict) -> list[Violation]:
    """Core thuần: 6 rule; null giá/giờ là unknown, không chứng nhận ngân sách đầy đủ."""
    violations, days = [], defaultdict(list)
    if not any(slot.poi_id for slot in itinerary.slots):
        violations.append(_violation("overload", "Chưa có hoạt động POI nào; không được báo lịch nghỉ toàn chuyến là hoàn thành."))
    if profile.start_date and profile.end_date:
        expected_dates = {profile.start_date + timedelta(days=i)
                          for i in range((profile.end_date - profile.start_date).days + 1)}
        if {s.slot_date for s in itinerary.slots} != expected_dates:
            violations.append(_violation("overlap", "Lịch trình chưa phủ đúng các ngày trong hồ sơ."))
    known_cost = sum(s.cost_vnd for s in itinerary.slots if s.cost_vnd is not None)
    if profile.budget_total_vnd is not None and known_cost > profile.budget_total_vnd:
        violations.append(_violation("budget", f"Chi phí đã biết {known_cost} vượt ngân sách {profile.budget_total_vnd} VND."))
    for slot in itinerary.slots:
        days[slot.day_index].append(slot)
        if profile.start_date:
            expected = profile.start_date + timedelta(days=slot.day_index - 1)
            if slot.slot_date != expected or (profile.end_date and slot.slot_date > profile.end_date):
                violations.append(_violation("overlap", "slot_date/day_index nằm ngoài hồ sơ chuyến đi.", slot))
        poi = facts["pois"].get(slot.poi_id)
        if not poi:
            continue  # fabrication checker xử lý POI không tồn tại
        # Phase 1 chỉ chặn khi dữ liệu có nguồn cho thấy không phù hợp; metadata null được planner ghi "chưa xác minh".
        youngest = min((child.age for child in profile.children), default=None)
        if youngest is not None and poi.get("min_age") is not None and poi["min_age"] > youngest:
            violations.append(_violation("overload", f"POI yêu cầu từ {poi['min_age']} tuổi, đoàn có trẻ {youngest} tuổi.", slot))
        if poi.get("walking_level") == "high" and (profile.mobility_notes or (youngest is not None and youngest < 7)):
            violations.append(_violation("overload", "POI có mức đi bộ high, quá sức đoàn (trẻ nhỏ/ghi chú đi lại).", slot))
        intervals = opening_intervals(poi["opening_hours"], slot.slot_date)
        start, end = minutes(slot.start_time), minutes(slot.end_time)
        if intervals is not None and not any(a <= start and end <= b for a, b in intervals):
            hours = ", ".join(f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}" for a, b in intervals) or "đóng cửa"
            violations.append(_violation("opening_hours", (
                f"{slot.poi_id} ngày {slot.slot_date}: slot {slot.start_time}-{slot.end_time}; "
                f"khoảng mở cửa có nguồn: {hours}. Dời cả slot vào một khoảng hoặc đổi điểm."), slot))
        for zone in facts["zones"]:
            if zone["destination_id"] == poi["destination_id"] and active(zone, slot.slot_date.isoformat()) and contains(
                    zone["geometry"], poi["lon"], poi["lat"]):
                violations.append(_violation("restricted_area", f"POI thuộc vùng hạn chế: {zone['name']}; {zone['source_url']}", slot))
    for day, slots in days.items():
        slots.sort(key=lambda s: s.start_time)
        date_values = {s.slot_date for s in slots}
        if len(date_values) != 1:
            violations.append(_violation("overlap", f"Ngày thứ {day} có nhiều slot_date khác nhau."))
        for prev, current in pairwise(slots):
            travel = current.travel_minutes_from_prev or 0
            if minutes(current.start_time) < minutes(prev.end_time) + travel:
                earliest = minutes(prev.end_time) + travel
                violations.append(_violation("overlap", (
                    f"Sau slot {prev.slot_id} kết thúc {prev.end_time}, cần travel={travel} phút; "
                    f"start_time của slot này sớm nhất {earliest // 60:02d}:{earliest % 60:02d}, "
                    f"không phải {current.start_time}. Dời giờ/giảm điểm, không bịa travel."), current))
        forecast = weather.get(slots[0].slot_date.isoformat(), {})
        heavy = (forecast.get("condition") == "heavy_rain" or (forecast.get("precip_mm") or 0) >= HEAVY_RAIN_MM) and (
            not forecast.get("is_anomalous") and forecast.get("status", "ok") not in ("anomalous", "no_forecast"))
        outdoor_minutes = 0
        activity_minutes = 0
        attractions = 0
        walking_m = 0
        last_poi = None
        for slot in slots:
            poi = facts["pois"].get(slot.poi_id)
            duration = minutes(slot.end_time) - minutes(slot.start_time)
            # Khớp scorer: mọi slot (kể cả ăn/nghỉ/tự do) + di chuyển đều tính vào thời lượng ngày.
            activity_minutes += duration + (slot.travel_minutes_from_prev or 0)
            if poi:
                attractions += poi.get("category") == "attraction"
                # Điểm tham quan chưa rõ outdoor không được mặc định an toàn trong mưa lớn; quán ăn/lưu trú thì không tính.
                if poi.get("is_outdoor") in (1, True) or (poi.get("is_outdoor") is None and poi.get("category") == "attraction"):
                    outdoor_minutes += duration
                if last_poi and slot.travel_minutes_from_prev is not None:
                    matching = [p for p in _pairs(facts, last_poi, slot.poi_id)
                                if p["minutes"] == slot.travel_minutes_from_prev]
                    if matching and all(p["mode"] == "walk" for p in matching):
                        walking_m += max(p["distance_m"] for p in matching)
                last_poi = slot.poi_id
        if heavy and outdoor_minutes > 120:
            violations.append(_violation("weather", f"Ngày {day}: ngoài trời/chưa rõ outdoor {outdoor_minutes} phút >120 khi mưa lớn."))
        pace = profile.pace or "moderate"
        if activity_minutes > PACE_MINUTES[pace] or walking_m > PACE_WALK_M[pace]:
            violations.append(_violation("overload", (
                f"Ngày {day}: {activity_minutes} phút (tổng mọi slot kể cả ăn/nghỉ + di chuyển), tối đa "
                f"{PACE_MINUTES[pace]} với pace={pace}; rút ngắn/bớt slot, không chèn slot nghỉ dài.")))
        if attractions > PACE_ATTRACTIONS[pace]:
            violations.append(_violation("overload", (
                f"Ngày {day}: {attractions} điểm tham quan, tối đa {PACE_ATTRACTIONS[pace]} với pace={pace}.")))
    return violations


def validate(itinerary: Itinerary, profile: TripProfile, weather: dict) -> list[Violation]:
    """Facade giữ contract: chỉ đọc facts; weather thuộc run hiện tại; không LLM/ghi DB."""
    return validate_with_facts(itinerary, profile, weather, repo.destination_facts())


def check_fabrication(itinerary: Itinerary) -> list[Violation]:
    """Đối chiếu POI/nhãn/giá/travel; core thuần nằm ở fabrication_with_facts. Số người lấy từ hồ sơ của chuyến."""
    _, profile = repo.latest_profile(itinerary.trip_id)
    return fabrication_with_facts(itinerary, repo.destination_facts(), party_size(profile) if profile else 1)
