"""UC-01: trích hồ sơ qua harness, kiểm route bằng code; không phụ thuộc checkpointer của P1."""

import json
import re
import unicodedata
from datetime import date

from pydantic import BaseModel, model_validator

from agent.db import repo
from agent.schemas import TripProfile
from agent.src.graph.loop import AgentLoopLimitError, agent_loop, load_skill


class IntakeResult(BaseModel):
    profile: TripProfile
    destination_text: str | None
    conflicts: list[str]

    @model_validator(mode="before")
    @classmethod
    def keep_business_conflicts(cls, value):
        """Không để LLM tự sửa mâu thuẫn chắc chắn thành giá trị mà người dùng chưa chọn."""
        if not isinstance(value, dict) or not isinstance(value.get("profile"), dict):
            return value
        data = dict(value)
        profile = dict(data["profile"])
        conflicts = data.get("conflicts")
        if not isinstance(conflicts, list) or any(not isinstance(item, str) for item in conflicts):
            return value  # lỗi cấu trúc phải qua vòng sửa schema
        conflicts = list(conflicts)
        try:
            start = date.fromisoformat(profile["start_date"]) if profile.get("start_date") else None
            end = date.fromisoformat(profile["end_date"]) if profile.get("end_date") else None
        except (ValueError, TypeError):
            return value
        if start and end and (end < start or (end - start).days + 1 > 5):
            conflicts.append("start_date/end_date: ngày mâu thuẫn hoặc chuyến dài hơn 5 ngày")
            profile.update(start_date=None, end_date=None)
        for field in ("adults", "budget_total_vnd"):
            if type(profile.get(field)) is int and profile[field] <= 0:
                conflicts.append(f"{field}: phải lớn hơn 0")
                profile[field] = None
        children = profile.get("children", [])
        if isinstance(children, list) and any(
            isinstance(child, dict) and type(child.get("age")) is int and not 0 <= child["age"] <= 17
            for child in children
        ):
            conflicts.append("children: tuổi trẻ phải trong 0–17; cần xác nhận lại")
            profile["children"] = []
        data.update(profile=profile, conflicts=conflicts)
        return data


QUESTIONS = {
    "start_date": ("Bạn khởi hành ngày nào (YYYY-MM-DD)?", "What is your start date (YYYY-MM-DD)?"),
    "end_date": ("Bạn kết thúc chuyến ngày nào (tối đa 5 ngày)?", "What is your end date (at most 5 days)?"),
    "adults": ("Có bao nhiêu người lớn?", "How many adults are travelling?"),
    "budget_total_vnd": ("Ngân sách tổng bằng VND là bao nhiêu?", "What is your total budget in VND?"),
    "children": ("Bạn xác nhận lại tuổi các trẻ nhé?", "Please confirm the children's ages."),
    "destination_text": ("Bạn muốn đến Huế hay nơi khác?", "Would you like to visit Hue or another destination?"),
    "hard_constraints": ("Bạn làm rõ thông tin mâu thuẫn nhé?", "Please clarify the conflicting information."),
}


def _normalized(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFD", text.casefold())
                            if unicodedata.category(c) != "Mn").split())


def route_intake(result: IntakeResult) -> dict:
    """Hàm thuần: tối đa 3 câu, route do code quyết định, không lưu DB hoặc gọi LLM."""
    profile = result.profile.model_copy(deep=True)
    destination = _normalized(result.destination_text or "")
    if destination and destination not in {"hue", "hue city", "thanh pho hue", "thua thien hue"}:
        profile.route, profile.missing_info = "unsupported", []
        return {"profile": profile, "route": profile.route, "questions": [],
                "conflicts": result.conflicts, "message": "Hiện chỉ hỗ trợ Huế"}
    missing = [field for field in ("start_date", "end_date", "adults", "budget_total_vnd")
               if getattr(profile, field) is None]
    if not destination:
        missing.insert(0, "destination_text")
    for conflict in result.conflicts:
        fields = [field for field in QUESTIONS if field in conflict]
        # Số ngày xung đột với khoảng ngày: chưa biết người dùng sẽ sửa đầu nào.
        if any(field in fields for field in ("start_date", "end_date")) and re.search(
            r"\b(?:\d+\s*(?:ngay|days?)|duration|so ngay|thoi luong)\b", _normalized(conflict)
        ):
            fields = list(dict.fromkeys(["start_date", "end_date", *fields]))
        if not fields:
            fields = ["start_date", "end_date"] if any(
                token in _normalized(conflict) for token in ("ngay", "date", "duration", "day")
            ) else ["hard_constraints"]
        for field in fields:
            if field not in missing:
                missing.append(field)
            if field in {"start_date", "end_date", "adults", "budget_total_vnd"}:
                setattr(profile, field, None)
            elif field == "children":
                profile.children = []
    profile.route = "ask_user" if missing else "plan"
    profile.missing_info = missing
    language = int(profile.language == "en")
    questions = [{"field": field, "text": QUESTIONS[field][language]} for field in missing[:3]]
    return {"profile": profile, "route": profile.route, "questions": questions,
            "conflicts": result.conflicts, "message": ""}


def extract_intake(messages, client, run_id, usage) -> dict:
    """Một lần đầu + tối đa hai lần sửa schema; input chỉ là hội thoại, không nhận gold/eval."""
    skill = load_skill("trip-intake", run_id, "intake")
    try:
        result = agent_loop(client, skill, json.dumps(messages, ensure_ascii=False), [], IntakeResult,
                            run_id, "intake", usage, max_turns=3)
    except AgentLoopLimitError as error:
        raise ValueError("UC-01: schema vẫn sai sau 3 lượt (tối đa 2 lần sửa); không lập lịch.") from error
    return route_intake(result)


def intake(state, client, usage) -> dict:
    """Adapter node: đọc messages đúng trip/user; P1 nối questions vào interrupt và resume."""
    if not repo.query("SELECT 1 FROM trips WHERE trip_id=? AND user_id=?", (state["trip_id"], state["user_id"])):
        raise ValueError("Không tìm thấy chuyến đi của người dùng.")
    messages = repo.query(
        "SELECT role, content FROM messages WHERE trip_id=? AND user_id=? ORDER BY created_at, rowid",
        (state["trip_id"], state["user_id"]),
    )
    result = extract_intake(messages, client, state["run_id"], usage)
    repo.log_event(state["run_id"], "intake", "guardrail", name="intake_result",
                   result={**result, "profile": result["profile"].model_dump(mode="json")})
    if result["route"] == "plan":
        result["profile_id"] = repo.save_profile(state["trip_id"], result["profile"], state["run_id"])
    return result
