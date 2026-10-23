"""Backend API Phase 1. Chạy: uvicorn agent.src.api.server:app --reload  (OpenAPI: /docs, /openapi.json)
Người dùng lấy từ session cookie (POST /api/session), không bao giờ từ body request."""

import json
import os
import secrets

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from agent.db import repo
from agent.db.init import FICTIONAL_USERS
from agent.schemas import TripProfile
from agent.src.graph.app import run_uc02

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
    """Chạy graph UC-02 (đồng bộ, có thể mất 1–2 phút). Lỗi → 500 kèm run_id để xem trace."""
    own_trip(trip_id, user_id)
    repo.query("UPDATE trips SET status = 'planning', updated_at = ? WHERE trip_id = ?", (repo.now(), trip_id))
    result = run_uc02(trip_id, user_id)
    if result["error"]:
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
