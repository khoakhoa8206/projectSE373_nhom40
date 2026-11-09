"""HTTP/SSE hư cấu chỉ để kiểm UI. Không dùng làm backend hoặc bằng chứng nghiệm thu LLM thật."""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="UI TEST ONLY — không LLM, không DB thật")
state = {"ready": False, "status": "failed_validation"}


@app.get("/api/users")
def users():
    return [{"user_id": "ui-test", "display_name": "Người dùng UI hư cấu", "preferred_lang": "vi"}]


@app.post("/api/session")
def session():
    return {"user_id": "ui-test"}


@app.post("/api/trips")
def trip():
    return {"trip_id": "ui-test-trip"}


@app.post("/api/trips/{trip_id}/messages")
def message(trip_id: str):
    return {"run_id": "ui-test-question"}


@app.post("/api/trips/{trip_id}/resume")
def resume(trip_id: str, body: dict):
    if body.get("approval_id") == "ui-test-ask":
        state["ready"] = True
        return {"run_id": "ui-test-review"}
    state["status"] = "approved" if body.get("decision") == "approved" else "failed_validation"
    return {"run_id": "ui-test-done"}


@app.get("/api/runs/{run_id}/stream")
def stream(run_id: str):
    if run_id == "ui-test-question":
        data = {"kind": "ask_user", "approval_id": "ui-test-ask", "data": {
            "questions": [{"field": "adults", "text": "Có bao nhiêu người lớn? (UI giả)"}], "conflicts": []}}
        event = "interrupt"
    elif run_id == "ui-test-review":
        data = {"kind": "itinerary_approval", "approval_id": "ui-test-approval", "data": {"itinerary_id": "ui-test-it"}}
        event = "interrupt"
    else:
        data, event = {"message": "Đã ghi quyết định trong HTTP mock UI, không phải backend thật."}, "done"
    return Response(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n", media_type="text/event-stream")


@app.get("/api/trips/{trip_id}/itinerary")
def itinerary(trip_id: str):
    if not state["ready"]:
        raise HTTPException(404, "Chưa có fixture UI")
    slots = [{"slot_id": f"ui-s{day}", "day_index": day, "slot_date": f"2026-11-{26 + day}",
              "start_time": "09:00", "end_time": "10:00", "poi_id": f"ui-p{day}",
              "activity": "Hoạt động UI hư cấu — không phải gợi ý du lịch thật",
              "travel_minutes_from_prev": None, "cost_vnd": None, "cost_source": "unverified",
              "hours_status": "unverified", "note": "Fixture giao diện, không có dữ kiện nguồn thực địa.",
              "name_vi": f"Điểm UI hư cấu {day}", "lat": 16.46 + day * 0.003, "lon": 107.57 + day * 0.003}
             for day in (1, 2)]
    return {"itinerary_id": "ui-test-it", "status": state["status"], "planner_rounds": 2,
            "total_cost_vnd": None, "has_unpriced_item": 1, "slots": slots,
            "violations": [{"violation_id": 1, "slot_id": "ui-s1", "rule": "weather", "severity": "high",
                            "message": "Vi phạm hư cấu để kiểm UI còn lỗi; không phải dự báo thời tiết."}]}


@app.get("/api/pois")
def pois():
    return []


@app.get("/mobile-preview", response_class=HTMLResponse)
def mobile():
    return '<h1>HTTP MOCK UI — viewport iframe 390×844, không phải điện thoại thật</h1>' \
           '<iframe title="UI 390px" src="/" style="width:390px;height:844px;border:1px solid #777"></iframe>'


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web/dist", html=True), name="ui-only")
