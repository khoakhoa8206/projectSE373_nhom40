"""Backend API Phase 1. Chạy: uvicorn agent.src.api.server:app --reload  (OpenAPI: /docs, /openapi.json)
Người dùng lấy từ session cookie (POST /api/session), không bao giờ từ body request."""

import json
import os
import secrets
import sqlite3
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.sessions import SessionMiddleware

from agent.db import repo
from agent.db.init import FICTIONAL_USERS
from agent.schemas import TripEvent, TripProfile
from agent.src.graph.app import run_uc02
from agent.src.nodes.journal import run_uc09
from agent.src.nodes.narrate import run_uc03

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


class NarrateIn(BaseModel):
    """Body UC-03: poi_id (UI tự tìm POI gần nhất, không bao giờ gửi toạ độ) và/hoặc câu hỏi."""

    model_config = ConfigDict(extra="forbid")  # gửi kèm lat/lon → 422, không lưu vị trí chính xác
    poi_id: str | None = None
    question: str | None = Field(None, max_length=500)
    lang: Literal["vi", "en"]
    length: Literal["short", "detail"] = "short"


class JournalIn(BaseModel):
    """Body UC-09: nhật ký 1 ngày (scope = day, cần day_index) hoặc tóm tắt cả chuyến (scope = trip)."""

    model_config = ConfigDict(extra="forbid")
    scope: Literal["day", "trip"]
    day_index: int | None = Field(None, ge=0, le=5)
    lang: Literal["vi", "en"] = "vi"


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


@app.post("/api/narrate")
def narrate(body: NarrateIn, user_id: str = Depends(current_user)):
    """UC-03 (P3): thuyết minh có trích dẫn [doc_id §section] theo ngôn ngữ người dùng. Kho không có thông tin →
    out_of_kb = true và câu mẫu. Lỗi → 500 kèm run_id để xem trace."""
    question = (body.question or "").strip() or None
    if not question and not body.poi_id:
        raise HTTPException(422, "Cần poi_id hoặc question")
    if body.poi_id and not repo.query("SELECT 1 FROM pois WHERE poi_id = ?", (body.poi_id,)):
        raise HTTPException(404, "Không tìm thấy POI")
    name, lang = USERS[user_id]
    repo.create_user(name, lang, user_id)  # có sẵn sau make db; tạo lại nếu DB mới
    result = run_uc03(user_id, question, body.poi_id, body.lang, body.length)
    if result["error"]:
        raise HTTPException(500, result)
    return {k: result[k] for k in ("text", "citations", "out_of_kb", "run_id")}


@app.get("/api/trips")
def list_trips(user_id: str = Depends(current_user)):
    """Chuyến đi của người dùng (mới nhất trước) kèm ngày đi/về của hồ sơ mới nhất, cho màn hình Nhật ký."""
    return repo.query(
        """SELECT t.trip_id, t.status, t.created_at, p.start_date, p.end_date FROM trips t
           LEFT JOIN trip_profiles p
             ON p.profile_id = (SELECT MAX(profile_id) FROM trip_profiles WHERE trip_id = t.trip_id)
           WHERE t.user_id = ? ORDER BY t.created_at DESC, t.rowid DESC""",
        (user_id,),
    )


@app.post("/api/trips/{trip_id}/events")
def add_trip_event(trip_id: str, event: TripEvent, user_id: str = Depends(current_user)):
    """UC-09 (P3): ghi 1 sự kiện chuyến đi. trip_id lấy từ URL; vị trí chỉ là poi_id (gửi toạ độ → 422)."""
    own_trip(trip_id, user_id)
    try:
        return {"event_id": repo.add_trip_event(event.model_copy(update={"trip_id": trip_id}))}
    except (ValueError, sqlite3.IntegrityError) as e:  # poi_id/slot_id không tồn tại, event_id của chuyến khác
        raise HTTPException(400, f"Không ghi được sự kiện: {e}") from e


@app.get("/api/trips/{trip_id}/events")
def list_trip_events(trip_id: str, day_index: int | None = None, user_id: str = Depends(current_user)):
    own_trip(trip_id, user_id)
    return repo.trip_events(trip_id, day_index)


@app.post("/api/trips/{trip_id}/journal")
def make_journal(trip_id: str, body: JournalIn, user_id: str = Depends(current_user)):
    """UC-09 (P3): nhật ký ngày / tóm tắt chuyến (nén theo tầng). Trả nội dung, event_ids, total_spent_vnd (tool
    sum_expenses), tokens_before → tokens_after, run_id. Lỗi → 500 kèm run_id."""
    own_trip(trip_id, user_id)
    if (body.scope == "day") != (body.day_index is not None):
        raise HTTPException(422, "scope = day cần day_index; scope = trip không gửi day_index")
    result = run_uc09(trip_id, user_id, body.scope, body.day_index, body.lang)
    if result["error"]:
        raise HTTPException(500, result)
    return result["journal"] | {"run_id": result["run_id"]}
