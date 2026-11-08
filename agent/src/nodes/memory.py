"""UC-07 (W9-P1-1): trích sở thích từ hồ sơ chuyến → đề xuất lưu → người dùng xác nhận → nạp vào chuyến sau.

Node `remember` (agent/src/graph/app.py) chạy sau khi người dùng duyệt lịch trình: gọi candidates(), dừng ở
interrupt memory_save với data = {"items": [{key, kind, value, sensitivity}]}, người dùng trả response = danh sách
key được chọn (hoặc {key, value} nếu sửa giá trị). Mục sensitive được chọn = người dùng đồng ý lưu mục nhạy cảm.
"""

from agent.db import repo
from agent.schemas import TripProfile
from agent.src.memory import store

# ponytail: phân loại bằng từ khoá trên hồ sơ đã qua Pydantic; cần bắt ý từ hội thoại tự do thì thay bằng LLM structured output
ALLERGY = ("dị ứng", "allerg")
DIETARY = ("ăn chay", "vegetarian", "vegan", "halal", "kiêng")


def _kind(text):
    low = text.lower()
    if any(k in low for k in ALLERGY):
        return "allergy", "sensitive"
    if any(k in low for k in DIETARY):
        return "dietary", "sensitive"
    return "other", "normal"


def candidates(profile: TripProfile, user_id, trip_id):
    """Ứng viên lưu (chưa có trong bộ nhớ) lấy từ hồ sơ người dùng đã khai cho chuyến này."""
    items = [("interest", i, "normal") for i in profile.interests]
    if profile.pace:
        items.append(("pace", profile.pace, "normal"))
    for text in profile.hard_constraints:
        kind, sensitivity = _kind(text)
        items.append((kind, text, sensitivity))
    if profile.mobility_notes:
        items.append(("other", profile.mobility_notes, "sensitive"))  # thông tin đi lại / sức khoẻ
    city = repo.query("SELECT d.name_vi FROM trips t JOIN destinations d USING (destination_id) WHERE t.trip_id = ?",
                      (trip_id,))  # fmt: skip
    if city:
        items.append(("visited_city", city[0]["name_vi"], "normal"))
    known = {(m["kind"], m["value"]) for m in store.memory_read(user_id)}
    out, seen = [], set()
    for kind, value, sensitivity in items:
        if (kind, value) not in known and (kind, value) not in seen:
            seen.add((kind, value))
            out.append({"key": f"{kind}:{value}", "kind": kind, "value": value, "sensitivity": sensitivity})
    return out


def save_selected(user_id, trip_id, items, response):
    """Lưu các mục người dùng chọn. response: [key] hoặc [{key, value}]. Trả {"saved": [memory_id], "skipped": [lý do]}."""
    by_key = {i["key"]: i for i in items}
    saved, skipped = [], []
    for choice in response if isinstance(response, list) else []:
        key, value = (choice, None) if isinstance(choice, str) else (choice.get("key"), choice.get("value"))
        item = by_key.get(key)
        if item is None:
            skipped.append(f"{key}: không nằm trong danh sách đề xuất")
            continue
        if item["sensitivity"] == "sensitive":
            store.grant_sensitive_consent(user_id)  # tick chọn mục nhạy cảm trên thẻ duyệt = đồng ý lưu
        try:
            saved.append(store.memory_write(user_id, item["kind"], value or item["value"], item["sensitivity"], trip_id))
        except store.MemoryRuleError as e:
            skipped.append(f"{key}: {e}")
    return {"saved": saved, "skipped": skipped}


def memory_context(user_id, run_id):
    """Bộ nhớ đưa vào plan của chuyến sau; trace chỉ ghi mục nào được dùng (id + loại), không ghi giá trị."""
    items = store.memory_read(user_id)
    repo.log_event(run_id, "load_profile", "tool_call", name="memory_read",
                   result={"used": [{"memory_id": m["memory_id"], "kind": m["kind"]} for m in items]})  # fmt: skip
    return [{"kind": m["kind"], "value": m["value"]} for m in items]
