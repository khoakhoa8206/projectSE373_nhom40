"""Node plan của UC-02. P1 dựng khung (gọi agent_loop, gán slot_id); P2 viết lại SYSTEM và cách lọc ứng viên (P2-5)."""

import json
from itertools import groupby

from agent.schemas import Itinerary
from agent.src.graph.loop import agent_loop, load_skill

SKILL = "itinerary-planning"

# TODO(P2): prompt đầy đủ theo nhiệm vụ P2-5.
SYSTEM = """Bạn là planner lịch trình du lịch Huế. Chỉ dùng dữ liệu lấy từ tool; không tự bịa giờ mở cửa, giá vé, thời tiết.
POI không có giờ mở cửa: hours_status = "unverified". Không có giá: cost_vnd = null, cost_source = "unverified".
Nếu có violations_to_fix thì sửa đúng các lỗi đó trên previous_itinerary.
Kết quả cuối: chỉ cần điền slots (slot_id để trống, hệ thống tự gán)."""


def plan(state, client, tools, usage):
    round_ = state["round"] + 1
    skill = load_skill(SKILL, state["run_id"], "plan")
    previous = state.get("itinerary")
    user = json.dumps(
        {
            "profile": state["profile"].model_dump(mode="json"),
            "previous_itinerary": previous and [s.model_dump(mode="json") for s in previous.slots],
            "violations_to_fix": [v.model_dump() for v in state["violations"]],
        },
        ensure_ascii=False,
    )
    draft = agent_loop(client, f"{SYSTEM}\n\n{skill}", user, tools, Itinerary, state["run_id"], "plan", usage)

    # slot_id do code gán theo thứ tự trong ngày: '<itinerary_id>:d1-s2'
    slots = sorted(draft.slots, key=lambda s: (s.day_index, s.start_time))
    for day, group in groupby(slots, key=lambda s: s.day_index):
        for i, s in enumerate(group, 1):
            s.slot_id, s.itinerary_id = f"{state['itinerary_id']}:d{day}-s{i}", state["itinerary_id"]
    itinerary = Itinerary(itinerary_id=state["itinerary_id"], trip_id=state["trip_id"], profile_id=state["profile_id"],
                          run_id=state["run_id"], planner_rounds=round_, slots=slots)  # fmt: skip
    return {"itinerary": itinerary, "round": round_}
