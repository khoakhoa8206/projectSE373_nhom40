"""UC-01 bản chạy không cần LLM: đọc lời kể thành các trường của TripProfile bằng luật. Hàm thuần, không ghi DB.
ponytail: regex chỉ hiểu các cách nói phổ biến; P2 thay bằng structured output (agent/src/nodes/intake.py, W8-P2-1)."""

import re
from datetime import date, timedelta

from agent.src.nodes.verify import fold, normalize

NUMBERS = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5, "sau": 6, "one": 1, "two": 2, "three": 3, "four": 4,
           "five": 5, "six": 6}  # fmt: skip
N = r"(\d+|" + "|".join(NUMBERS) + ")"
MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
DATE = (rf"\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}(?:/\d{{4}})?|\d{{1,2}} thang \d{{1,2}}(?: nam \d{{4}})?"
        rf"|{MONTH} \d{{1,2}}(?:st|nd|rd|th)?(?:,? \d{{4}})?|\d{{1,2}}(?:st|nd|rd|th)? {MONTH}(?: \d{{4}})?")  # fmt: skip
SUPPORTED = r"\b(?:hue|imperial city|co do)\b"
UNSUPPORTED = {"bangkok": "Bangkok", "da lat": "Đà Lạt", "dalat": "Đà Lạt", "hoi an": "Hội An", "ha noi": "Hà Nội",
               "hanoi": "Hà Nội", "phu quoc": "Phú Quốc", "sai gon": "Sài Gòn", "saigon": "Sài Gòn",
               "da nang": "Đà Nẵng", "danang": "Đà Nẵng", "nha trang": "Nha Trang", "singapore": "Singapore",
               "tokyo": "Tokyo", "paris": "Paris", "seoul": "Seoul"}  # fmt: skip
INTERESTS = {"history": r"lich su|di tich|di san|history|historic|heritage", "food": r"an uong|am thuc|mon an|food|cuisine",
             "culture": r"van hoa|culture", "nature": r"thien nhien|nature", "craft": r"lang nghe|craft",
             "nightlife": r"nightlife|cuoc song ve dem", "beach": r"tam bien|bai bien|beach",
             "photography": r"chup anh|photography|photo", "shopping": r"mua sam|shopping"}  # fmt: skip
PACE = {"relaxed": r"thong tha|nhe nhang|relaxed|slow pace|easy pace", "packed": r"day dac|packed|cang nhieu diem",
        "moderate": r"vua phai|moderate"}  # fmt: skip
MOBILITY = r"khong leo[a-z ]*|it di bo|khong di bo nhieu|nguoi cao tuoi|xe lan|wheelchair|limited mobility|no climbing"
ASK = {
    "destination": ("Bạn muốn đi đâu? (hiện hỗ trợ Huế)", "Where would you like to go? (Hue is supported)"),
    "start_date": ("Bạn khởi hành ngày nào? (vd 25/11/2026)", "What date do you start? (e.g. 25/11/2026)"),
    "days": ("Chuyến đi kéo dài mấy ngày? (1 đến 5)", "How many days is the trip? (1 to 5)"),
    "adults": ("Đoàn có mấy người lớn?", "How many adults are travelling?"),
    "budget_total_vnd": ("Ngân sách cả chuyến khoảng bao nhiêu? (vd 8 triệu)", "What is the total budget in VND? (e.g. 8000000)"),
}  # fmt: skip


def detect_lang(text: str) -> str:
    marks = re.search(r"[ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ]", text.lower())
    return "vi" if marks or re.search(r"\b(?:ngay|nguoi|trieu|toi|minh)\b", fold(text)) else "en"


def _num(s: str) -> int:
    return int(s) if s.isdigit() else NUMBERS[s]


def _money(s: str) -> int | None:
    value = normalize(s, "money")
    return None if not value else int(value * 1_000_000 if value < 1000 else value)


def _date(s: str, today: date) -> date | None:
    value = normalize(s, "date", today.year)
    if not value or len(value) != 10:
        return None
    day = date.fromisoformat(value)
    if not re.search(r"\d{4}", s) and day < today:  # không ghi năm và ngày đã qua thì là năm sau
        day = day.replace(year=day.year + 1)
    return day


def _budget(f: str) -> int | None:
    if m := re.search(r"\d+(?:[.,]\d+)?\s*(?:trieu|tr|million)\b", f):
        return int(float(re.match(r"[\d.,]+", m[0])[0].replace(",", ".")) * 1_000_000)
    if m := re.search(r"\b\d{1,3}(?:[.,]\d{3}){1,3}\b|\b\d{5,}\b", f):
        return _money(m[0])
    return None


def _adults(f: str, children: int) -> int | None:
    if m := re.search(N + r"\s*(?:nguoi lon|adults?)\b", f):
        return _num(m[1])
    if re.search(r"\b(?:vo chong|cung chong|cung vo|couple|my wife|my husband)\b", f):
        return 2
    if re.search(r"\b(?:mot minh|solo|alone|by myself|just me)\b", f):
        return 1
    if m := re.search(N + r"\s*(?:nguoi|people|persons?|travell?ers?)\b", f):
        return max(_num(m[1]) - children, 1)
    return None


def preferences(text: str) -> dict:
    """Điều chính người dùng nói ra (UC-07 chỉ được đề xuất lưu các mục này). Cắt trên bản gốc nên giữ nguyên dấu."""
    f = fold(text)
    constraints, memory = [], []
    if re.search(r"\b(?:an chay|vegetarian|vegan)\b", f):
        constraints.append("ăn chay")
        memory.append(("dietary", "ăn chay", "sensitive"))
    for pattern, kind, sensitivity, prefix in (
        (r"\b(?:khong an|khong thich an|don'?t eat|do not eat)\s+([^,.;\n]+)", "food_dislike", "normal", "không ăn "),
        (r"\b(?:di ung|allergic to)\s+([^,.;\n]+)", "allergy", "sensitive", "dị ứng "),
    ):
        for m in re.finditer(pattern, f):
            value = text[m.start(1) : m.end(1)].strip()
            constraints.append(prefix + value)
            memory.append((kind, prefix + value, sensitivity))
    mobility = re.search(MOBILITY, f)
    interests = [k for k, p in INTERESTS.items() if re.search(rf"\b(?:{p})\b", f)]
    pace = next((k for k, p in PACE.items() if re.search(rf"\b(?:{p})\b", f)), None)
    memory += [("interest", i, "normal") for i in interests]
    if pace:
        memory.append(("pace", pace, "normal"))
    return {"constraints": constraints, "memory": memory, "interests": interests, "pace": pace,
            "mobility_notes": text[mobility.start() : mobility.end()] if mobility else None}  # fmt: skip


def analyse(text: str, answers: dict | None = None, today: date | None = None) -> dict:
    """Trả các trường hồ sơ + route. Thiếu/mâu thuẫn → route ask_user, tối đa 3 câu hỏi, không đoán ngày hay ngân sách."""
    answers, today = answers or {}, today or date.today()
    f = fold(text)
    lang = detect_lang(text)
    pick = 0 if lang == "vi" else 1

    # Điểm đến
    wanted = answers.get("destination") or text
    fw = fold(wanted)
    elsewhere = next((name for key, name in UNSUPPORTED.items() if re.search(rf"\b{key}\b", fw)), None)
    if elsewhere and not re.search(SUPPORTED, fw):
        return {"route": "unsupported", "destination": elsewhere, "lang": lang, "questions": [], "conflicts": []}
    has_destination = bool(re.search(SUPPORTED, fw))

    # Ngày: "25-27/11" → "25/11 den 27/11"
    expanded = re.sub(r"\b(\d{1,2})\s*(?:-|den)\s*(\d{1,2})/(\d{1,2})", r"\1/\3 den \2/\3", f)
    dates = [d for d in (_date(m[0], today) for m in re.finditer(DATE, expanded)) if d]
    start = _date(fold(answers["start_date"]), today) if answers.get("start_date") else (dates[0] if dates else None)
    end = dates[1] if len(dates) > 1 and not answers.get("start_date") else None
    told = re.search(N + r"\s*(?:ngay|days?)\b", f) or re.search(r"\b(\d)\s*n\s*\d\s*d\b", f)
    days = _num(told[1]) if told else None
    answered = re.search(r"\d+", str(answers.get("days", "")))
    conflicts = []
    if answered:
        days, end = int(answered[0]), None
    if start and end and days and (end - start).days + 1 != days:
        span = (end - start).days + 1
        conflicts.append(f"Bạn nói {days} ngày nhưng từ ngày đi tới ngày về là {span} ngày." if lang == "vi"
                         else f"You said {days} days but the dates span {span} days.")  # fmt: skip
    elif start and days and not end:
        end = start + timedelta(days=days - 1)
    bad_length = bool(start and end and not 1 <= (end - start).days + 1 <= 5) or bool(days and not 1 <= days <= 5)
    if bad_length and not conflicts:
        conflicts.append("Hệ thống chỉ lập lịch từ 1 đến 5 ngày." if lang == "vi" else "Trips can be 1 to 5 days long.")

    # Người và tiền
    ages = [int(a) for a in re.findall(r"(\d{1,2})\s*(?:tuoi|years?[- ]old|yo)\b", f) if int(a) <= 17]
    ages = ages or [int(a) for a in re.findall(r"\b(?:be|con|chau|child|kid|son|daughter)\s+(\d{1,2})\b", f)]
    adults_answer = re.search(r"\d+", str(answers.get("adults", "")))
    adults = int(adults_answer[0]) if adults_answer else _adults(f, len(ages))
    budget = _money(answers["budget_total_vnd"]) if answers.get("budget_total_vnd") else _budget(f)

    missing = [field for field, ok in (("destination", has_destination), ("start_date", start),
                                       ("days", (end or days) and not conflicts), ("adults", adults),
                                       ("budget_total_vnd", budget)) if not ok]  # fmt: skip
    questions = [{"field": x, "text": ASK[x][pick]} for x in missing[:3]]
    prefs = preferences(text)
    return {"route": "ask_user" if questions else "plan", "lang": lang, "questions": questions, "conflicts": conflicts,
            "missing": missing, "destination": "hue", "start_date": start, "end_date": end, "adults": adults,
            "children": ages, "budget": budget, **prefs}  # fmt: skip


if __name__ == "__main__":  # python -m fullstack.intake
    today = date(2026, 11, 9)
    a = analyse("Nhà mình đi Huế 3 ngày từ 25/11/2026, 2 người lớn 1 bé 6 tuổi, khoảng 8 triệu, thích ăn uống", today=today)
    assert a["route"] == "plan" and a["end_date"] == date(2026, 11, 27) and a["children"] == [6] and a["budget"] == 8_000_000
    assert analyse("Cuối tháng 11 đi Huế", today=today)["route"] == "ask_user"
    assert analyse("đi Bangkok 3 ngày", today=today)["route"] == "unsupported"
    b = analyse("Huế 3 ngày từ 25/11 đến 29/11, 2 người lớn, 8 triệu", today=today)
    assert b["conflicts"] and b["questions"][0]["field"] == "days"
    print("ok")
