"""Planner giả (không phải LLM) cho lúc chưa có LLM_API_KEY: gọi tool thật rồi nộp lịch có giờ tính từ ma trận di chuyển thật.
Giá, giờ mở cửa do node plan điền từ dữ liệu; validator thật vẫn chấm. Có LLM_API_KEY thì không dùng file này."""

import json
import math
from datetime import date, timedelta
from types import SimpleNamespace as NS

from openai.types.chat import ChatCompletion

from agent.db import repo
from agent.src.graph.loop import SUBMIT
from agent.src.nodes.verify import fold

# (poi_id, số phút, là bữa ăn): 5 mẫu ngày không lặp điểm, điểm có giờ mở cửa buổi sáng đứng đầu ngày
DAYS = [
    [("hue-bao-tang-co-vat", 90, 0), ("hue-dai-noi", 90, 0), ("hue-com-hen-hoa-dong", 60, 1), ("hue-lang-tu-duc", 105, 0)],
    [("hue-chua-thien-mu", 90, 0), ("hue-lang-khai-dinh", 90, 0), ("hue-madam-thu", 60, 1), ("hue-chua-bao-quoc", 75, 0)],
    [("hue-quoc-tu-giam", 75, 0), ("hue-dien-thai-hoa", 75, 0), ("hue-lien-hoa", 60, 1), ("hue-cau-thanh-toan", 90, 0)],
    [("hue-bao-tang-ho-chi-minh", 90, 0), ("hue-vien-co-mat", 75, 0), ("hue-lac-thien", 60, 1), ("hue-lang-huong-thuy-xuan", 90, 0)],
    [("hue-chua-dieu-de", 75, 0), ("hue-bia-quoc-hoc", 60, 0), ("hue-lac-thanh", 60, 1)],
]  # fmt: skip
VEGETARIAN = ["hue-san-may", "hue-loving-hut"]
LUNCH = 11 * 60 + 30


def _call(i, name, args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def _slots(profile):
    facts = repo.destination_facts()
    drive = {(r["from_poi_id"], r["to_poi_id"]): r["minutes"] for r in facts["matrix"] if r["mode"] == "drive"}
    notes = fold(" ".join(profile["hard_constraints"]))
    veg = "an chay" in notes
    dropped = {p for p, row in facts["pois"].items() if "bo " + fold(row["name_vi"]) in notes}
    start = date.fromisoformat(profile["start_date"])
    days = (date.fromisoformat(profile["end_date"]) - start).days + 1
    en = profile["language"] == "en"
    slots = []
    for i in range(days):
        stops = [s for s in DAYS[i % len(DAYS)] if s[0] not in dropped]
        if profile["pace"] == "relaxed":
            stops = stops[:3]
        clock, previous = 8 * 60 + 30, None
        for poi_id, minutes, meal in stops:
            if meal and veg:
                poi_id = VEGETARIAN[i % 2]
            clock += math.ceil(drive.get((previous, poi_id), 0) / 5) * 5
            if meal:
                clock = max(clock, LUNCH)
            name = facts["pois"][poi_id]["name_en"] if en and facts["pois"][poi_id]["name_en"] else facts["pois"][poi_id]["name_vi"]
            verb = ("Lunch at" if meal else "Visit") if en else ("Ăn trưa tại" if meal else "Tham quan")
            slots.append({"day_index": i + 1, "slot_date": (start + timedelta(days=i)).isoformat(),
                          "start_time": _hhmm(clock), "end_time": _hhmm(clock + minutes), "poi_id": poi_id,
                          "activity": f"{verb} {name}", "cost_source": "unverified", "hours_status": "unverified"})  # fmt: skip
            clock, previous = clock + minutes, poi_id
    return slots


class DemoLLM:
    """Cùng giao diện client OpenAI: lượt 1 gọi tool thật, lượt 2 nộp lịch trình. Không báo token vì không gọi model nào."""

    def __init__(self):
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        msgs = kw["messages"]
        profile = json.loads(next(m["content"] for m in msgs if m["role"] == "user"))["profile"]
        if msgs[-1]["role"] != "tool":
            first = DAYS[0][0][0]
            message = {"content": None, "tool_calls": [
                _call(1, "get_opening_hours", {"poi_id": first, "date": profile["start_date"]}),
                _call(2, "get_travel_time", {"from_poi_id": first, "to_poi_id": DAYS[0][1][0], "mode": "drive"}),
            ]}  # fmt: skip
        else:
            message = {"content": None, "tool_calls": [_call(3, SUBMIT, {"slots": _slots(profile)})]}
        return ChatCompletion.model_validate({
            "id": "demo", "object": "chat.completion", "created": 0, "model": "demo-planner-no-llm",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", **message}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0},
        })  # fmt: skip
