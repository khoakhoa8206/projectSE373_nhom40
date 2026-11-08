"""Backend API Phase 1. Chạy: uvicorn agent.src.api.server:app --reload  (OpenAPI: /docs, /openapi.json)
Người dùng lấy từ session cookie (POST /api/session), không bao giờ từ body request."""

import json
import os
import secrets
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from agent.db import repo
from agent.db.init import FICTIONAL_USERS
from agent.schemas import TripProfile
from agent.src.graph import app as graph

load_dotenv()
USERS = {user_id: (name, lang) for user_id, name, lang in FICTIONAL_USERS}

app = FastAPI(title="Tour Guide Agent API", version="0.1.0")
# ponytail: thiếu SESSION_SECRET thì sinh ngẫu nhiên → restart server là phải chọn lại người dùng
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET") or secrets.token_hex(32))


def current_user(request: Request) -> str:
    user_id = request.session.get("user_id")
    if user_id not in USERS:
        raise HTTPException(401, "Chưa chọn người dùng: gọi POST /api/session trước")
    return user_id


def own_trip(trip_id, user_id):
    if not repo.query("SELECT 1 FROM trips WHERE trip_id = ? AND user_id = ?", (trip_id, user_id)):
        raise HTTPException(404, "Không tìm thấy chuyến đi")


def _parse(s):
    return json.loads(s) if s else None


class SessionIn(BaseModel):
    user_id: str


@app.get("/api/users")
def list_users():
    """3 người dùng hư cấu cho màn hình chọn người dùng."""
    return [{"user_id": u, "display_name": name, "preferred_lang": lang} for u, (name, lang) in USERS.items()]


@app.post("/api/session")
def login(body: SessionIn, request: Request):
    if body.user_id not in USERS:
        raise HTTPException(400, "Chỉ chọn được 1 trong 3 người dùng hư cấu")
    request.session["user_id"] = body.user_id
    return {"user_id": body.user_id}


@app.post("/api/trips")
def create_trip(profile: TripProfile, user_id: str = Depends(current_user)):
    """Nhận form hồ sơ → tạo trip + trip_profiles v1 (route = plan)."""
    name, lang = USERS[user_id]
    repo.create_user(name, lang, user_id)  # có sẵn sau make db; tạo lại nếu DB mới
    trip_id = repo.create_trip(user_id)
    profile_id = repo.save_profile(trip_id, profile.model_copy(update={"route": "plan", "missing_info": []}))
    return {"trip_id": trip_id, "profile_id": profile_id}


@app.post("/api/trips/{trip_id}/plan")
def plan_trip(trip_id: str, user_id: str = Depends(current_user)):
    """Chạy graph UC-02 (đồng bộ, có thể mất 1–2 phút) tới bước người dùng duyệt: kết quả có `interrupt`
    (kind = itinerary_approval) để gửi lại qua /resume. Lỗi → 500 kèm run_id để xem trace."""
    own_trip(trip_id, user_id)
    repo.query("UPDATE trips SET status = 'planning', updated_at = ? WHERE trip_id = ?", (repo.now(), trip_id))
    result = graph.run_uc02(trip_id, user_id, approval=True)
    if result["error"]:
        raise HTTPException(500, result)
    return result


@app.get("/api/trips/{trip_id}/approvals")
def list_approvals(trip_id: str, user_id: str = Depends(current_user)):
    """Các câu hỏi / bước duyệt đang chờ người dùng: [{kind, approval_id, data}]. Tải lại trang vẫn thấy."""
    own_trip(trip_id, user_id)
    return graph.pending_approvals(trip_id)


class ResumeIn(BaseModel):
    approval_id: str
    decision: Literal["approved", "rejected", "edited"]
    response: Any = None  # ask_user: câu trả lời; edited: ghi chú sửa; memory_save: các mục được chọn


@app.post("/api/trips/{trip_id}/resume")
def resume_trip(trip_id: str, body: ResumeIn, user_id: str = Depends(current_user)):
    """Trả lời 1 interrupt → graph chạy tiếp đúng chỗ dừng (đọc checkpoint, backend restart vẫn được)."""
    own_trip(trip_id, user_id)
    result = graph.resume(trip_id, body.approval_id, body.decision, body.response)
    if result is None:
        raise HTTPException(409, "Không có yêu cầu đang chờ với approval_id này (đã trả lời hoặc sai chuyến đi)")
    if result["error"]:
        raise HTTPException(500, result)
    return result


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.post("/api/trips/{trip_id}/messages")
def post_message(trip_id: str, body: MessageIn, user_id: str = Depends(current_user)):
    """UC-01 hội thoại: lưu tin nhắn; đang có câu hỏi ask_user thì tin nhắn là câu trả lời (resume),
    không thì bắt đầu lượt UC-01 mới (graph UC-01 do P2 đăng ký vào GRAPHS)."""
    own_trip(trip_id, user_id)
    repo.add_message(trip_id, user_id, "user", body.text)
    asking = [p for p in graph.pending_approvals(trip_id) if p["kind"] == "ask_user"]
    if asking:
        result = graph.resume(trip_id, asking[0]["approval_id"], "approved", body.text)
    elif "UC-01" in graph.GRAPHS:
        run_id = repo.create_run("UC-01", trip_id, user_id)
        result = graph.summarize(run_id, *graph.drive("UC-01", run_id, trip_id, {"run_id": run_id, "trip_id": trip_id}))
    else:
        raise HTTPException(501, "UC-01 hội thoại chưa được đăng ký (W8-P2-1)")
    if result is None or result["error"]:
        raise HTTPException(500, result)
    return result


@app.get("/api/trips/{trip_id}/itinerary")
def get_itinerary(trip_id: str, user_id: str = Depends(current_user)):
    """Lịch trình mới nhất: slot (kèm tên + lat/lon POI) và vi phạm còn lại."""
    own_trip(trip_id, user_id)
    itinerary = repo.itinerary_for_trip(trip_id)
    if itinerary is None:
        raise HTTPException(404, "Chuyến đi chưa có lịch trình")
    return itinerary


@app.get("/api/runs/{run_id}/trace")
def get_trace(run_id: str, user_id: str = Depends(current_user)):
    """Các bước của 1 lượt chạy (node, tool, skill, LLM) cho panel log."""
    if not repo.query("SELECT 1 FROM runs WHERE run_id = ? AND user_id = ?", (run_id, user_id)):
        raise HTTPException(404, "Không tìm thấy lượt chạy")
    rows = repo.query("SELECT * FROM trace_events WHERE run_id = ? ORDER BY seq", (run_id,))
    return [r | {"args": _parse(r["args"]), "result": _parse(r["result"])} for r in rows]


@app.get("/api/pois")
def list_pois(destination_id: str = "hue", category: str | None = None):
    """POI để vẽ bản đồ (dữ liệu công khai, không cần chọn người dùng)."""
    rows = repo.query(
        "SELECT * FROM pois WHERE destination_id = ? AND (? IS NULL OR category = ?) ORDER BY poi_id",
        (destination_id, category, category),
    )
    return [r | {"tags": _parse(r["tags"])} for r in rows]
