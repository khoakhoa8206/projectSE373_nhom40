"""Graph UC-02 Phase 1: load_profile → plan → validate → (còn vi phạm và < 4 vòng thì quay lại plan) → finalize."""

import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent.db import repo
from agent.schemas import Itinerary, TripProfile, Violation
from agent.src.graph.loop import make_client, ms
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
    return {"violations": violations, "history": state["history"] + [(state["round"], v) for v in violations]}


def finalize(state):
    status = "failed_validation" if state["violations"] else "validated"
    itinerary = state["itinerary"].model_copy(update={"status": status})
    repo.save_itinerary(itinerary, state["history"])
    return {"itinerary": itinerary}


def run_uc02(trip_id, user_id, eval_case_id=None, client=None, tools=None):
    """Chạy 1 lượt UC-02 và luôn đóng run (token, chi phí, độ trễ). Trả {run_id, itinerary_id, status, error}."""
    client = client or make_client()
    tools = default_tools() if tools is None else tools
    run_id = repo.create_run("UC-02", trip_id, user_id, eval_case_id)
    usage = {"in": 0, "out": 0, "cost": 0.0}

    g = StateGraph(State)
    g.add_node("load_profile", traced("load_profile", load_profile))
    g.add_node("plan", traced("plan", lambda s: plan(s, client, tools, usage)))
    g.add_node("validate", traced("validate", check))
    g.add_node("finalize", traced("finalize", finalize))
    g.add_edge(START, "load_profile")
    g.add_edge("load_profile", "plan")
    g.add_edge("plan", "validate")
    g.add_conditional_edges("validate", lambda s: "plan" if s["violations"] and s["round"] < MAX_ROUNDS else "finalize")
    g.add_edge("finalize", END)

    t0 = time.perf_counter()
    try:
        out = g.compile().invoke({"run_id": run_id, "trip_id": trip_id, "itinerary_id": repo.new_id("it")})
        result = {"run_id": run_id, "itinerary_id": out["itinerary"].itinerary_id, "status": out["itinerary"].status,
                  "error": None}  # fmt: skip
    except Exception as e:  # noqa: BLE001 — lỗi nào cũng phải đóng run và trả run_id
        result = {"run_id": run_id, "itinerary_id": None, "status": "error", "error": f"{type(e).__name__}: {e}"}
    repo.finish_run(run_id, "failed" if result["error"] else "succeeded", usage["in"], usage["out"], usage["cost"],
                    ms(t0))  # fmt: skip
    return result
