"""Node duyệt cho graph có checkpointer của P1; không tự lưu checkpoint hoặc tạo API."""

from langgraph.types import interrupt

from agent.db import repo


def approve(state):
    itinerary_id = state["itinerary"].itinerary_id
    approval_id = repo.prepare_itinerary_approval(
        itinerary_id, state["trip_id"], state["user_id"], state["run_id"])
    answer = interrupt({"kind": "itinerary_approval", "approval_id": approval_id,
                        "data": {"itinerary_id": itinerary_id}})
    if not isinstance(answer, dict) or answer.get("approval_id") != approval_id:
        raise ValueError("Phản hồi không khớp approval_id đang chờ.")
    decision, response = answer.get("decision"), answer.get("response")
    repo.decide_itinerary_approval(approval_id, state["trip_id"], state["user_id"], decision, response)
    repo.log_event(state["run_id"], "approve", "approval", name="itinerary_approval",
                   result={"approval_id": approval_id, "decision": decision})
    result = {"approval_decision": decision}
    if decision == "approved":
        result["itinerary"] = state["itinerary"].model_copy(update={"status": "approved"})
    if decision == "edited":
        result["feedback"] = response
        if state["round"] < 4:
            result.update(itinerary_id=repo.new_id("it"), best_itinerary=None, best_violations=None, best_score=None)
        else:
            result["planning_warning"] = "Đã dùng đủ 4 vòng; chưa áp dụng yêu cầu sửa, giữ bản nháp."
    return result
