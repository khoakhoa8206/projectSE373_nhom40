"""Graph UC-02 Phase 1: load_profile → plan → validate → (còn vi phạm và < 4 vòng thì quay lại plan) → finalize."""

import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from openai import InternalServerError, RateLimitError

from agent.db import repo
from agent.schemas import Itinerary, TripProfile, Violation
from agent.src.graph.loop import AgentLoopLimitError, make_client, ms
from agent.src.nodes.plan import plan
from agent.src.validation.validator import check_fabrication, validate

MAX_ROUNDS = 4


class State(TypedDict, total=False):
    run_id: str
    trip_id: str
    itinerary_id: str
    profile_id: int
    profile: TripProfile
    itinerary: Itinerary
    round: int
    violations: list[Violation]  # vi phạm của vòng gần nhất
    history: list[tuple[int, Violation]]  # (vòng, vi phạm) của mọi vòng, để lưu cột resolved
    best_itinerary: Itinerary
    best_violations: list[Violation]
    best_score: tuple[int, int, int]
    planning_stopped: bool
    planning_warning: str
    context: dict  # ứng viên + dự báo lấy ở vòng đầu, vòng sửa dùng lại


def default_tools():
    # import muộn: tool do P2 (destination) và P4 (weather) viết; test truyền tool giả vào run_uc02
    from agent.src.tools.destination import get_opening_hours, get_poi, get_travel_time, search_poi
    from agent.src.tools.weather import get_weather_forecast

    return [search_poi, get_poi, get_opening_hours, get_travel_time, get_weather_forecast]


def traced(name, fn):
    """Bọc node: ghi node_start, node_end (hoặc error) vào trace."""

    def wrapper(state):
        repo.log_event(state["run_id"], name, "node_start")
        t0 = time.perf_counter()
        try:
            out = fn(state)
        except Exception as e:
            repo.log_event(state["run_id"], name, "error", duration_ms=ms(t0), error=f"{type(e).__name__}: {e}")
            raise
        repo.log_event(state["run_id"], name, "node_end", duration_ms=ms(t0))
        return out

    return wrapper


def load_profile(state):
    profile_id, profile = repo.latest_profile(state["trip_id"])
    if profile is None or profile.route != "plan":
        raise ValueError("chuyến đi chưa có hồ sơ với route = plan")
    return {"profile_id": profile_id, "profile": profile, "round": 0, "violations": [], "history": []}


def check(state):
    weather = repo.weather_for_run(state["run_id"])
    violations = validate(state["itinerary"], state["profile"], weather) + check_fabrication(state["itinerary"])
    repo.log_event(state["run_id"], "validate", "guardrail", name="validator",
                   result={"round": state["round"], "violations": [v.model_dump() for v in violations]})  # fmt: skip
    score = (sum(v.severity == "high" for v in violations), len(violations),
             sum(v.severity == "medium" for v in violations))
    result = {"violations": violations, "history": state["history"] + [(state["round"], v) for v in violations]}
    if "best_score" not in state or score < state["best_score"]:
        result.update(best_itinerary=state["itinerary"].model_copy(deep=True), best_violations=violations, best_score=score)
    return result


def plan_or_keep_best(state, client, tools, usage):
    """Vòng sửa hết lượt/provider tạm lỗi: giữ bản đã kiểm và cảnh báo, không tự tạo lịch."""
    try:
        return plan(state, client, tools, usage)
    except (AgentLoopLimitError, RateLimitError, InternalServerError) as error:
        if "best_itinerary" not in state:
            raise  # chưa có bản hợp lệ theo schema thì không tạo kết quả giả
        round_ = state["round"] + 1
        limited = isinstance(error, AgentLoopLimitError)
        status = None if limited else error.status_code
        reason = "hết lượt gọi LLM" if limited else f"provider LLM trả HTTP {status} sau xử lý retry có giới hạn"
        warning = (f"Vòng sửa {round_} {reason}; đang hiển thị bản tốt nhất của vòng "
                   f"{state['best_itinerary'].planner_rounds} cùng lỗi còn lại, chưa phải lịch đã duyệt.")
        repo.log_event(state["run_id"], "plan", "guardrail",
                       name="keep_best_on_turn_limit" if limited else "keep_best_on_provider_error",
                       result={"attempted_round": round_, "selected_round": state["best_itinerary"].planner_rounds,
                               "status": status})
        return {"round": round_, "planning_stopped": True, "planning_warning": warning}


def finalize(state):
    remaining = state.get("best_violations", state["violations"])
    best = state.get("best_itinerary", state["itinerary"])
    status = "failed_validation" if remaining else "validated"
    itinerary = best.model_copy(deep=True, update={"status": status, "planner_rounds": state["round"]})
    if state.get("planning_warning"):
        first = itinerary.slots[0]
        first.note = "; ".join(filter(None, (first.note, state["planning_warning"])))
    # POI bịa không được trở thành dữ kiện bản đồ; vẫn giữ bản gốc/lỗi trong trace để debug.
    facts = repo.destination_facts()
    for index, slot in enumerate(itinerary.slots):
        if slot.poi_id and slot.poi_id not in facts["pois"]:
            repo.log_event(state["run_id"], "finalize", "guardrail", name="unknown_poi",
                           result={"slot": slot.model_dump(mode="json"), "action": "drop_unverified_poi_reference"})
            itinerary.slots = list(itinerary.slots)
            itinerary.slots[index] = slot.model_copy(update={
                "poi_id": None, "activity": "Hoạt động chưa xác minh (không phải gợi ý có nguồn)",
                "cost_vnd": None, "cost_source": "unverified", "hours_status": "not_applicable",
                "travel_minutes_from_prev": None,
                "note": f"Mã POI không tồn tại: {slot.poi_id}. Cần thay địa điểm trước khi sử dụng lịch trình.",
            })
    # unresolved phải thuộc bản được chọn, không phải mặc định bản cuối; giữ trace lịch sử nguyên vẹn.
    history = [(r, v) for r, v in state["history"] if r < state["round"]]
    history.extend((state["round"], v) for v in remaining)
    repo.log_event(state["run_id"], "finalize", "guardrail", name="best_draft",
                   result={"selected_round": best.planner_rounds, "attempted_rounds": state["round"],
                           "remaining": len(remaining)})
    repo.save_itinerary(itinerary, history)
    return {"itinerary": itinerary}


def run_uc02(trip_id, user_id, eval_case_id=None, client=None, tools=None):
    """Chạy 1 lượt UC-02 và luôn đóng run (token, chi phí, độ trễ). Trả {run_id, itinerary_id, status, error}."""
    run_id = repo.create_run("UC-02", trip_id, user_id, eval_case_id)
    usage = {"in": 0, "out": 0, "cost": 0.0}
    t0 = time.perf_counter()
    try:  # tạo run trước: thiếu tool / API key vẫn có run_id + trace để PWA xem log
        client = client or make_client()
        tools = default_tools() if tools is None else tools
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
        repo.log_event(run_id, "setup", "error", error=error)
        repo.finish_run(run_id, "failed", 0, 0, 0.0, ms(t0))
        return {"run_id": run_id, "itinerary_id": None, "status": "error", "error": error}

    g = StateGraph(State)
    g.add_node("load_profile", traced("load_profile", load_profile))
    g.add_node("plan", traced("plan", lambda s: plan_or_keep_best(s, client, tools, usage)))
    g.add_node("validate", traced("validate", check))
    g.add_node("finalize", traced("finalize", finalize))
    g.add_edge(START, "load_profile")
    g.add_edge("load_profile", "plan")
    g.add_conditional_edges("plan", lambda s: "finalize" if s.get("planning_stopped") else "validate")
    g.add_conditional_edges("validate", lambda s: "plan" if s["violations"] and s["round"] < MAX_ROUNDS else "finalize")
    g.add_edge("finalize", END)

    try:
        out = g.compile().invoke({"run_id": run_id, "trip_id": trip_id, "itinerary_id": repo.new_id("it")})
        result = {"run_id": run_id, "itinerary_id": out["itinerary"].itinerary_id, "status": out["itinerary"].status,
                  "error": None}  # fmt: skip
    except Exception as e:  # noqa: BLE001 — lỗi nào cũng phải đóng run và trả run_id
        result = {"run_id": run_id, "itinerary_id": None, "status": "error", "error": f"{type(e).__name__}: {e}"}
    repo.finish_run(run_id, "failed" if result["error"] else "succeeded", usage["in"], usage["out"], usage["cost"],
                    ms(t0))  # fmt: skip
    return result
