"""Graph UC-02: load_profile → plan → validate → (còn vi phạm và < 4 vòng thì quay lại plan) → finalize
→ review (UC-06, chỉ khi review=True và lịch validated: 3 reviewer; còn findings và < 2 vòng thì quay lại plan)
→ approve (người dùng duyệt / sửa / từ chối, chỉ khi approval=True) → END, hoặc quay lại plan nếu người dùng sửa;
duyệt xong → remember (UC-07: đề xuất lưu sở thích, người dùng chọn mục nào được lưu) → END.
Chạy có checkpointer SQLite (thread_id = trip_id): backend chết giữa chừng thì continue_run chạy tiếp đúng node;
graph đang chờ người dùng thì resume chạy tiếp sau khi người dùng trả lời, kể cả khi backend đã restart."""

import json
import time
from typing import TypedDict

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from openai import InternalServerError, RateLimitError

from agent.db import repo
from agent.schemas import Itinerary, TripProfile, Violation
from agent.src.graph.checkpoint import config, open_checkpointer
from agent.src.graph.loop import AgentLoopLimitError, make_client, ms
from agent.src.nodes import intake as uc01
from agent.src.nodes import memory
from agent.src.nodes.plan import plan
from agent.src.nodes.review import review
from agent.src.validation.validator import check_fabrication, validate

MAX_ROUNDS = 4
INTERRUPT_KINDS = ("ask_user", "itinerary_approval", "memory_save")  # khớp approvals.kind
DECISIONS = ("approved", "rejected", "edited")


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
    best_score: list[int]  # checkpoint đọc lại tuple thành list, nên dùng list ngay từ đầu
    planning_stopped: bool
    planning_warning: str
    context: dict  # ứng viên + dự báo lấy ở vòng đầu, vòng sửa dùng lại
    approval: bool  # có dừng chờ người dùng duyệt lịch trình không (API: có; eval/test cũ: không)
    decision: str  # quyết định gần nhất của người dùng ở bước duyệt
    user_feedback: str | None  # ghi chú khi người dùng chọn "sửa", plan dùng làm yêu cầu cho lượt mới
    approved_before: Itinerary | None  # sửa lịch đã duyệt: bản cũ, khôi phục nếu người dùng từ chối bản mới
    user_id: str
    memory: list[dict]  # UC-07: sở thích người dùng đã đồng ý lưu từ chuyến trước, plan dùng để ưu tiên
    intake: dict  # UC-01: {route, questions, conflicts, message} của lượt intake gần nhất
    approval_decision: str  # graph duyệt riêng của P2 (build_approval_graph)
    feedback: str
    review: bool  # UC-06: lịch trình validated có qua 3 reviewer không (API: có; eval UC-02/test cũ: không)
    review_round: int  # số vòng review đã chạy (≤ 2)
    review_findings: list[dict]  # findings medium/high của vòng review gần nhất, planner sửa theo
    review_again: bool


def default_tools():
    # Import muộn: tool điểm đến của P2 và thời tiết của P4.
    from agent.src.tools.destination import (
        check_restricted_area,
        get_opening_hours,
        get_poi,
        get_travel_time,
        search_poi,
    )
    from agent.src.tools.weather import get_weather_forecast

    return [
        search_poi,
        get_poi,
        get_opening_hours,
        get_travel_time,
        check_restricted_area,
        get_weather_forecast,
    ]


def traced(name, fn):
    """Bọc node: ghi node_start, node_end (hoặc error) vào trace."""

    def wrapper(state):
        repo.log_event(state["run_id"], name, "node_start")
        t0 = time.perf_counter()
        try:
            out = fn(state)
        except GraphBubbleUp:  # interrupt() là điểm dừng hợp lệ, không phải lỗi
            raise
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
    user_id = repo.query("SELECT user_id FROM trips WHERE trip_id = ?", (state["trip_id"],))[0]["user_id"]
    return {"profile_id": profile_id, "profile": profile, "round": 0, "violations": [], "history": [],
            "user_id": user_id, "memory": memory.memory_context(user_id, state["run_id"])}  # fmt: skip


def check(state):
    weather = repo.weather_for_run(state["run_id"])
    violations = validate(state["itinerary"], state["profile"], weather) + check_fabrication(state["itinerary"])
    repo.log_event(state["run_id"], "validate", "guardrail", name="validator",
                   result={"round": state["round"], "violations": [v.model_dump() for v in violations]})  # fmt: skip
    score = [sum(v.severity == "high" for v in violations), len(violations),
             sum(v.severity == "medium" for v in violations)]
    result = {"violations": violations, "history": state["history"] + [(state["round"], v) for v in violations]}
    if state.get("best_score") is None or score < state["best_score"]:
        result.update(best_itinerary=state["itinerary"].model_copy(deep=True), best_violations=violations, best_score=score)
    return result


def plan_or_keep_best(state, client, tools, usage):
    """Vòng sửa hết lượt/provider tạm lỗi: giữ bản đã kiểm và cảnh báo, không tự tạo lịch."""
    try:
        return plan(state, client, tools, usage)
    except (AgentLoopLimitError, RateLimitError, InternalServerError) as error:
        if state.get("best_itinerary") is None:
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
    best, remaining = state.get("best_itinerary"), state.get("best_violations")
    if best is None:
        best, remaining = state["itinerary"], state["violations"]
    status = "failed_validation" if remaining else "validated"
    itinerary = best.model_copy(deep=True, update={"status": status, "planner_rounds": state["round"],
                                                   "review_rounds": state.get("review_round", 0)})  # fmt: skip
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


def ask_human(kind, data):
    """Dừng graph chờ người dùng (W8-P1-2): ask_user (UC-01), duyệt lịch trình, đồng ý lưu bộ nhớ (UC-07).
    drive() ghi approvals + trace và trả payload {kind, approval_id, data} cho PWA. Khi người dùng trả lời, LangGraph
    chạy LẠI node từ đầu và lời gọi này trả {"decision": approved|rejected|edited, "response": ...}.
    => Code đứng trước ask_human trong node phải chạy lại được (không ghi DB, không gọi LLM trước nó)."""
    if kind not in INTERRUPT_KINDS:
        raise ValueError(f"kind phải thuộc {INTERRUPT_KINDS}")
    return interrupt({"kind": kind, "data": data})


def fresh_plan():
    """Bắt đầu 1 lượt lập lịch mới (bản mới, đủ 4 vòng validator) dựa trên state["itinerary"] làm bản trước."""
    return {"round": 0, "violations": [], "history": [], "itinerary_id": repo.new_id("it"), "best_itinerary": None,
            "best_violations": None, "best_score": None, "planning_stopped": False, "planning_warning": None}  # fmt: skip


def review_node(state, client, tools, usage):
    """UC-06: 3 reviewer. Còn findings medium/high và chưa đủ 2 vòng → planner lập lại theo findings."""
    out = review(state, client, tools, usage)
    return out | fresh_plan() if out["review_again"] else out


def after_finalize(state):
    if state.get("review") and state["itinerary"].status == "validated":
        return "review"
    return "approve" if state.get("approval") else END


def approve(state):
    """Người dùng duyệt lịch trình: duyệt → approved; sửa → lập lại theo ghi chú; từ chối → quay về hồ sơ."""
    itinerary = state["itinerary"]
    answer = ask_human("itinerary_approval", {"itinerary_id": itinerary.itinerary_id, "status": itinerary.status})
    decision, ts = answer["decision"], repo.now()
    if decision == "approved":
        repo.query("UPDATE itineraries SET status = 'approved' WHERE itinerary_id = ?", (itinerary.itinerary_id,))
        repo.query("UPDATE trips SET status = 'approved', updated_at = ? WHERE trip_id = ?", (ts, state["trip_id"]))
        return {"decision": decision, "itinerary": itinerary.model_copy(update={"status": "approved"})}
    if decision == "edited":  # lượt lập lịch mới (đủ 4 vòng) dựa trên bản vừa xem + ghi chú của người dùng
        return fresh_plan() | {"decision": decision, "user_feedback": str(answer.get("response") or ""),
                               "review_round": 0, "review_findings": None}  # fmt: skip
    if previous := state.get("approved_before"):  # từ chối bản sửa → bản đã duyệt trước đó lại là bản mới nhất
        new_id = repo.new_id("it")
        slots = [s.model_copy(update={"slot_id": s.slot_id.replace(previous.itinerary_id, new_id, 1)}) for s in previous.slots]
        repo.save_itinerary(previous.model_copy(update={"itinerary_id": new_id, "status": "approved", "slots": slots,
                                                        "run_id": state["run_id"]}), [])  # fmt: skip
        repo.query("UPDATE trips SET status = 'approved', updated_at = ? WHERE trip_id = ?", (ts, state["trip_id"]))
        repo.log_event(state["run_id"], "approve", "guardrail", name="keep_approved_itinerary",
                       result={"restored_from": previous.itinerary_id, "itinerary_id": new_id})
        return {"decision": decision}
    repo.query("UPDATE trips SET status = 'profiling', updated_at = ? WHERE trip_id = ?", (ts, state["trip_id"]))
    return {"decision": decision}


def remember(state):
    """UC-07: sau khi lịch trình được duyệt, đề xuất lưu sở thích; chỉ lưu mục người dùng chọn."""
    items = memory.candidates(state["profile"], state["user_id"], state["trip_id"])
    if not items:
        return {}
    answer = ask_human("memory_save", {"items": items})
    result = {"saved": [], "skipped": []}
    if answer["decision"] != "rejected":
        result = memory.save_selected(state["user_id"], state["trip_id"], items, answer.get("response"))
    repo.log_event(state["run_id"], "remember", "guardrail", name="memory_write", result=result)
    return {}


def intake_node(state, client, usage):
    """UC-01 (node intake của P2): hội thoại → TripProfile; thiếu/mâu thuẫn thì hỏi lại, ngoài Huế thì dừng."""
    result = uc01.intake(state, client, usage)
    out = {k: result[k] for k in ("route", "questions", "conflicts", "message")}
    text = "\n".join(q["text"] for q in result["questions"]) if result["route"] == "ask_user" else result["message"]
    if text:  # lưu câu agent nói để lượt intake sau có đủ ngữ cảnh hội thoại
        repo.add_message(state["trip_id"], state["user_id"], "assistant", text, run_id=state["run_id"])
    return {"intake": out}


def ask_user(state):
    """Dừng chờ người dùng trả lời các câu hỏi của intake; câu trả lời được lưu thành tin nhắn rồi intake chạy lại."""
    asked = state["intake"]
    answer = ask_human("ask_user", {"questions": asked["questions"], "conflicts": asked["conflicts"]})
    reply = answer.get("response")
    text = reply if isinstance(reply, str) else "; ".join(f"{k}: {v}" for k, v in (reply or {}).items())
    if text.strip():
        repo.add_message(state["trip_id"], state["user_id"], "user", text, run_id=state["run_id"])
    return {}


def add_planning(g, client, tools, usage):
    """Các node UC-02 dùng chung cho graph UC-02 (form) và UC-01 (hội thoại rồi lập lịch)."""
    g.add_node("load_profile", traced("load_profile", load_profile))
    g.add_node("plan", traced("plan", lambda s: plan_or_keep_best(s, client, tools, usage)))
    g.add_node("validate", traced("validate", check))
    g.add_node("finalize", traced("finalize", finalize))
    g.add_node("review", traced("review", lambda s: review_node(s, client, tools, usage)))
    g.add_node("approve", traced("approve", approve))
    g.add_node("remember", traced("remember", remember))
    g.add_edge("load_profile", "plan")
    g.add_conditional_edges("plan", lambda s: "finalize" if s.get("planning_stopped") else "validate")
    g.add_conditional_edges("validate", lambda s: "plan" if s["violations"] and s["round"] < MAX_ROUNDS else "finalize")
    g.add_conditional_edges("finalize", after_finalize)
    g.add_conditional_edges("review", lambda s: "plan" if s["review_again"] else "approve" if s.get("approval") else END)
    g.add_conditional_edges("approve", lambda s: {"edited": "plan", "approved": "remember"}.get(s["decision"], END))
    g.add_edge("remember", END)
    return g


def build_uc02(client, tools, usage):
    g = add_planning(StateGraph(State), client, tools, usage)
    g.add_edge(START, "load_profile")
    return g


def build_uc01(client, tools, usage):
    g = add_planning(StateGraph(State), client, tools, usage)
    g.add_node("intake", traced("intake", lambda s: intake_node(s, client, usage)))
    g.add_node("ask_user", traced("ask_user", ask_user))
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", lambda s: {"ask_user": "ask_user", "plan": "load_profile"}.get(s["intake"]["route"], END))
    g.add_edge("ask_user", "intake")
    return g


GRAPHS = {"UC-01": build_uc01, "UC-02": build_uc02}  # runs.uc → hàm dựng graph; UC khác đăng ký thêm ở đây để continue/resume tìm đúng


def drive(uc, run_id, trip_id, graph_input, client=None, tools=None):
    """Chạy graph trên thread trip_id tới END / interrupt / lỗi, cộng token và độ trễ vào runs. Trả (state cuối, lỗi).
    graph_input = dict: lượt chạy mới (xoá checkpoint cũ của trip); None: chạy tiếp từ checkpoint cuối;
    Command(resume=...): câu trả lời của người dùng cho interrupt đang chờ.
    Dừng ở interrupt: ghi approvals (pending) + trace kind 'approval', runs.status = interrupted."""
    usage = {"in": 0, "out": 0, "cost": 0.0}
    t0 = time.perf_counter()
    out, error = None, None
    try:  # lỗi setup vẫn có run_id + trace để PWA xem log
        client = client or make_client()
        tools = default_tools() if tools is None else tools
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {e}"
        repo.log_event(run_id, "setup", "error", error=error)
    if error is None:
        with open_checkpointer() as saver:
            if isinstance(graph_input, dict):
                saver.delete_thread(trip_id)  # lượt mới không được kế thừa best_* của lượt trước
                repo.query("UPDATE approvals SET decision = 'rejected', decided_at = ? WHERE trip_id = ? AND decision = 'pending'",
                           (repo.now(), trip_id))  # fmt: skip — yêu cầu chờ của lượt cũ không còn graph để chạy tiếp
            graph = GRAPHS[uc](client, tools, usage).compile(checkpointer=saver)
            try:
                out = graph.invoke(graph_input, config(trip_id))
            except Exception as e:  # noqa: BLE001 — lỗi nào cũng phải đóng run và trả run_id
                error = f"{type(e).__name__}: {e}"
    pending = (out or {}).get("__interrupt__") or []
    for item in pending:
        payload = item.value | {"approval_id": repo.new_id("ap")}
        repo.query(
            "INSERT INTO approvals (approval_id, trip_id, run_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (payload["approval_id"], trip_id, run_id, payload["kind"], json.dumps(payload, ensure_ascii=False), repo.now()),
        )
        repo.log_event(run_id, "approval", "approval", name=payload["kind"], result=payload)
    status = "failed" if error else "interrupted" if pending else "succeeded"
    repo.finish_run(run_id, status, usage["in"], usage["out"], usage["cost"], ms(t0))
    return out, error


def pending_approvals(trip_id, run_id=None):
    """Payload các interrupt đang chờ người dùng của trip (PWA tải lại trang vẫn thấy câu hỏi / nút duyệt)."""
    rows = repo.query(
        "SELECT payload FROM approvals WHERE trip_id = ? AND decision = 'pending' AND (? IS NULL OR run_id = ?)"
        " ORDER BY created_at",
        (trip_id, run_id, run_id),
    )
    return [json.loads(r["payload"]) for r in rows]


def summarize(run_id, out, error):
    """{run_id, itinerary_id, status, error, interrupt}; status = trạng thái lịch trình nếu graph có lịch trình."""
    if error:
        return {"run_id": run_id, "itinerary_id": None, "status": "error", "error": error, "interrupt": None}
    trip_id = repo.query("SELECT trip_id FROM runs WHERE run_id = ?", (run_id,))[0]["trip_id"]
    pending = pending_approvals(trip_id, run_id)
    it = out.get("itinerary")
    status = it.status if it else "interrupted" if pending else "succeeded"
    return {"run_id": run_id, "itinerary_id": it and it.itinerary_id, "status": status, "error": None,
            "interrupt": pending[0] if pending else None}  # fmt: skip


def run_uc02(trip_id, user_id, eval_case_id=None, client=None, tools=None, run_id=None, approval=False, revise=None,
             review=False):
    """Chạy 1 lượt UC-02 và luôn đóng run (token, chi phí, độ trễ). approval=True: dừng chờ người dùng duyệt.
    revise = (lịch đã duyệt, ghi chú): lập lại theo ghi chú như nút "sửa"; từ chối bản mới thì giữ bản cũ.
    review=True: lịch trình validated qua 3 reviewer UC-06 (≤ 2 vòng) trước khi tới bước duyệt.
    Trả {run_id, itinerary_id, status, error, interrupt}."""
    run_id = run_id or repo.create_run("UC-02", trip_id, user_id, eval_case_id)
    state = {"run_id": run_id, "trip_id": trip_id, "itinerary_id": repo.new_id("it"), "approval": approval,
             "review": review}  # fmt: skip
    if revise:
        previous, note = revise
        state |= {"itinerary": previous, "user_feedback": note, "approved_before": previous}
    return summarize(run_id, *drive("UC-02", run_id, trip_id, state, client, tools))


def run_uc01(trip_id, user_id, client=None, tools=None, run_id=None, review=False):
    """Lượt hội thoại UC-01 (tin nhắn đã lưu trong messages): intake → hỏi lại → lập lịch → duyệt → lưu bộ nhớ."""
    run_id = run_id or repo.create_run("UC-01", trip_id, user_id)
    state = {"run_id": run_id, "trip_id": trip_id, "user_id": user_id, "itinerary_id": repo.new_id("it"), "approval": True,
             "review": review}  # fmt: skip
    return summarize(run_id, *drive("UC-01", run_id, trip_id, state, client, tools))


def claim(trip_id, approval_id, decision, response=None):
    """Ghi câu trả lời của người dùng cho 1 interrupt đang chờ, đặt run về running. Trả run_id, None nếu không còn chờ.
    Tách khỏi resume để API chạy nền: ghi đồng bộ trước, stream mở ngay sau đó đã thấy run đang chạy."""
    if decision not in DECISIONS:
        raise ValueError(f"decision phải thuộc {DECISIONS}")
    rows = repo.query(  # 1 câu UPDATE: bấm 2 lần thì lần 2 không còn dòng pending
        "UPDATE approvals SET decision = ?, user_response = ?, decided_at = ? WHERE approval_id = ? AND trip_id = ?"
        " AND decision = 'pending' RETURNING run_id, kind",
        (decision, json.dumps(response, ensure_ascii=False), repo.now(), approval_id, trip_id),
    )
    if not rows:
        return None
    run_id = rows[0]["run_id"]
    repo.log_event(run_id, "approval", "approval", name=rows[0]["kind"],
                   result={"approval_id": approval_id, "decision": decision, "response": response})  # fmt: skip
    repo.query("UPDATE runs SET status = 'running', ended_at = NULL WHERE run_id = ?", (run_id,))
    return run_id


def resume_claimed(run_id, trip_id, decision, response=None, client=None, tools=None):
    uc = repo.query("SELECT uc FROM runs WHERE run_id = ?", (run_id,))[0]["uc"]
    command = Command(resume={"decision": decision, "response": response})
    return summarize(run_id, *drive(uc, run_id, trip_id, command, client, tools))


def resume(trip_id, approval_id, decision, response=None, client=None, tools=None):
    """Người dùng trả lời 1 interrupt đang chờ → chạy tiếp graph từ điểm dừng (đọc checkpoint, không cần process cũ).
    Trả None nếu không có yêu cầu đang chờ với approval_id đó (sai trip, đã trả lời rồi)."""
    run_id = claim(trip_id, approval_id, decision, response)
    return run_id and resume_claimed(run_id, trip_id, decision, response, client, tools)


def continue_run(trip_id, client=None, tools=None):
    """Backend chết khi graph đang chạy: chạy tiếp từ checkpoint cuối của trip, không lặp lại node đã xong.
    Trả None nếu trip không có lượt chạy dở (đã xong, hoặc đang chờ người dùng: khi đó dùng resume)."""
    with open_checkpointer() as saver:
        snapshot = saver.get_tuple(config(trip_id))
        if snapshot is None:
            return None
        run_id = snapshot.checkpoint["channel_values"]["run_id"]
        uc = repo.query("SELECT uc FROM runs WHERE run_id = ?", (run_id,))[0]["uc"]
        state = GRAPHS[uc](None, None, {}).compile(checkpointer=saver).get_state(config(trip_id))
        if not state.next or state.interrupts:
            return None
    repo.query("UPDATE runs SET status = 'running', ended_at = NULL WHERE run_id = ?", (run_id,))
    return summarize(run_id, *drive(uc, run_id, trip_id, None, client, tools))


def build_approval_graph(client, tools, usage, checkpointer):
    """P1 cấp checkpointer; giữ API run_uc02 Phase 1 để không phá caller cũ."""
    from agent.src.nodes.approve import approve

    if checkpointer is None:
        raise ValueError("Graph duyệt cần checkpointer và thread_id=trip_id do P1 cung cấp.")
    graph = StateGraph(State)
    graph.add_node("load_profile", traced("load_profile", load_profile))
    graph.add_node("plan", traced("plan", lambda state: plan_or_keep_best(state, client, tools, usage)))
    graph.add_node("validate", traced("validate", check))
    graph.add_node("finalize", traced("finalize", finalize))
    graph.add_node("approve", approve)
    graph.add_edge(START, "load_profile")
    graph.add_edge("load_profile", "plan")
    graph.add_conditional_edges("plan", lambda state: "finalize" if state.get("planning_stopped") else "validate")
    graph.add_conditional_edges("validate", lambda state:
                               "plan" if state["violations"] and state["round"] < MAX_ROUNDS else "finalize")
    graph.add_edge("finalize", "approve")
    graph.add_conditional_edges("approve", lambda state:
                               "plan" if state["approval_decision"] == "edited" and state["round"] < MAX_ROUNDS else END)
    return graph.compile(checkpointer=checkpointer)
