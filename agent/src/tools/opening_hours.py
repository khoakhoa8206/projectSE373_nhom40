"""Diễn giải tập con OSM opening_hours; cú pháp chưa hỗ trợ luôn trả unknown."""

import re
from datetime import date, timedelta

DAYS = {day: i for i, day in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"))}
RULE = re.compile(r"(?:(?P<days>[A-Za-z,-]+)\s+)?(?P<times>off|closed|[\d:,\s-]+)$")


def minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    if not (0 <= hour <= 24 and 0 <= minute < 60) or (hour == 24 and minute):
        raise ValueError("Giờ không hợp lệ.")
    return hour * 60 + minute


def _weekdays(text):
    if text is None:
        return set(range(7))
    result = set()
    for group in text.split(","):
        ends = group.split("-")
        if len(ends) == 1:
            result.add(DAYS[ends[0]])
        elif len(ends) == 2:
            start, end = (DAYS[d] for d in ends)
            result.update((start + step) % 7 for step in range((end - start) % 7 + 1))
        else:
            raise ValueError("Ngày không hợp lệ.")
    return result


def opening_intervals(raw: str | None, on_date: date) -> list[tuple[int, int]] | None:
    """Khoảng phút trong ngày; [] = đóng; None = chưa đủ dữ liệu/cú pháp chưa hỗ trợ.

    Hỗ trợ 24/7, weekday/range, nhiều khoảng và off. Không đoán PH/SH, ngày lễ,
    mùa, sunrise, || hay chú thích. Tất cả rule được parse trước, dù khác thứ.
    """
    if not raw:
        return None
    if raw.strip() == "24/7":
        return [(0, 1440)]
    try:
        rules = []
        for part in raw.split(";"):
            match = RULE.fullmatch(part.strip())
            if not match:
                return None
            weekdays = _weekdays(match["days"])
            if rules and match["days"] is None and match["times"] not in ("off", "closed"):
                return None  # không tự suy đoán ngày áp dụng của rule giờ rời rạc
            intervals = []
            if match["times"] not in ("off", "closed"):
                for interval in match["times"].split(","):
                    start, end = (minutes(t.strip()) for t in interval.strip().split("-"))
                    if start >= 1440 or start == end:
                        return None
                    intervals.append((start, end if end > start else end + 1440))
            rules.append((weekdays, intervals))
        result = []
        # Rule cụ thể sau ghi đè ngày trước; unknown không thành open-all-day.
        for delta in (-1, 0):
            weekday = (on_date + timedelta(days=delta)).weekday()
            daily = []
            for weekdays, intervals in rules:
                if weekday in weekdays:
                    daily = intervals
            for start, end in daily:
                start, end = max(0, start + delta * 1440), min(1440, end + delta * 1440)
                if start < end:
                    result.append((start, end))
        merged = []
        for start, end in sorted(result):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        return merged
    except (KeyError, ValueError, TypeError):
        return None
