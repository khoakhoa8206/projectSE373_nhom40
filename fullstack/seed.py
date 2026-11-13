"""Dữ liệu sẵn cho 3 tài khoản demo (hư cấu). Chạy đúng graph thật của nhóm, chỉ lần đầu tạo DB, luôn dùng planner giả để không tốn token."""

from datetime import date, datetime

from agent.db import repo
from agent.schemas import Child, TripEvent, TripProfile
from agent.src.graph import app as graph
from fullstack.demo_llm import DemoLLM


def _plan(user_id, text, client, **fields):
    trip_id = repo.create_trip(user_id)
    repo.add_message(trip_id, user_id, "user", text)
    repo.save_profile(trip_id, TripProfile(route="plan", **fields))
    result = graph.run_uc02(trip_id, user_id, client=client, approval=True)
    if result["error"]:
        raise RuntimeError(result["error"])
    return trip_id


def _approve_all(trip_id, client):
    while pending := graph.pending_approvals(trip_id):
        item = pending[0]
        keep = [i["key"] for i in item["data"]["items"] if i["sensitivity"] == "normal"] if item["kind"] == "memory_save" else None
        graph.resume(trip_id, item["approval_id"], "approved", keep, client=client)


def run():
    client = DemoLLM()
    ha = _plan("u-ha", "Nhà mình đi Huế 3 ngày từ 25/11/2026, 2 người lớn 1 bé 6 tuổi, khoảng 8 triệu", client,
               start_date=date(2026, 11, 25), end_date=date(2026, 11, 27), adults=2, children=[Child(age=6)],
               budget_total_vnd=8_000_000, interests=["history", "food"], pace="relaxed", language="vi",
               hard_constraints=["không ăn cay"])  # fmt: skip
    _approve_all(ha, client)
    slots = repo.itinerary_for_trip(ha)["slots"]
    now = datetime.now().astimezone()
    for fields in ({"event_type": "slot_done", "slot_id": slots[0]["slot_id"]}, {"event_type": "slot_done", "slot_id": slots[1]["slot_id"]},
                   {"event_type": "expense", "amount_vnd": 320000, "payload": {"category": "food", "label": "Ăn trưa cả nhà"}},
                   {"event_type": "note", "payload": {"text": "Bé rất thích khu Hoàng thành"}}):  # fmt: skip
        repo.add_trip_event(TripEvent(trip_id=ha, occurred_at=now, day_index=1, **fields))

    emma = _plan("u-emma", "I want a 2 day trip to Hue from Nov 20 2026, 1 adult, budget 5000000 VND", client,
                 start_date=date(2026, 11, 20), end_date=date(2026, 11, 21), adults=1, budget_total_vnd=5_000_000,
                 interests=["history", "photography"], pace="moderate", language="en")  # fmt: skip
    _approve_all(emma, client)

    # Minh dừng ở bước duyệt lịch trình để thử ngay interrupt và resume
    _plan("u-minh", "Đi Huế 2 ngày từ 21/11/2026, 2 người lớn, thích văn hoá, 6 triệu", client,
          start_date=date(2026, 11, 21), end_date=date(2026, 11, 22), adults=2, budget_total_vnd=6_000_000,
          interests=["culture"], pace="moderate", language="vi")  # fmt: skip
