"""Backend API Phase 1. Chạy: uvicorn agent.src.api.server:app --reload  (OpenAPI: /docs, /openapi.json)
Người dùng lấy từ session cookie (POST /api/session), không bao giờ từ body request."""

import json
import os
import secrets
import sqlite3
import threading
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.sessions import SessionMiddleware

from agent.db import repo
from agent.db.init import FICTIONAL_USERS
from agent.schemas import TripEvent, TripProfile
from agent.src.api.stream import run_events
from agent.src.graph import app as graph
from agent.src.memory import store
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


def own_run(run_id, user_id):
    if not repo.query("SELECT 1 FROM runs WHERE run_id = ? AND user_id = ?", (run_id, user_id)):
        raise HTTPException(404, "Không tìm thấy lượt chạy")


def start(fn, *args, **kwargs):
    """Chạy graph ở thread nền; mọi kết quả/lỗi đã nằm trong runs + trace_events, PWA đọc qua stream."""
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


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
def plan_trip(trip_id: str, background: bool = False, user_id: str = Depends(current_user)):
    """Chạy graph UC-02 tới bước người dùng duyệt: kết quả có `interrupt` (kind = itinerary_approval) để gửi lại
    qua /resume. Mặc định đồng bộ (1–2 phút); `?background=true` trả ngay {run_id} để PWA mở
    GET /api/runs/{run_id}/stream. Lỗi → 500 kèm run_id để xem trace."""
    own_trip(trip_id, user_id)
    repo.query("UPDATE trips SET status = 'planning', updated_at = ? WHERE trip_id = ?", (repo.now(), trip_id))
    if background:
        run_id = repo.create_run("UC-02", trip_id, user_id)
        start(graph.run_uc02, trip_id, user_id, run_id=run_id, approval=True)
        return {"run_id": run_id, "status": "running"}
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
def resume_trip(trip_id: str, body: ResumeIn, background: bool = False, user_id: str = Depends(current_user)):
    """Trả lời 1 interrupt → graph chạy tiếp đúng chỗ dừng (đọc checkpoint, backend restart vẫn được).
    `?background=true`: trả ngay {run_id}, theo dõi bằng stream."""
    own_trip(trip_id, user_id)
    if background:
        run_id = graph.claim(trip_id, body.approval_id, body.decision, body.response)
        if run_id is None:
            raise HTTPException(409, "Không có yêu cầu đang chờ với approval_id này (đã trả lời hoặc sai chuyến đi)")
        start(graph.resume_claimed, run_id, trip_id, body.decision, body.response)
        return {"run_id": run_id, "status": "running"}
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
    """UC-01 hội thoại, chạy nền: trả {run_id} ngay, theo dõi bằng GET /api/runs/{run_id}/stream.
    Đang có câu hỏi ask_user thì tin nhắn là câu trả lời (resume); không thì bắt đầu lượt UC-01 mới."""
    own_trip(trip_id, user_id)
    asking = [p for p in graph.pending_approvals(trip_id) if p["kind"] == "ask_user"]
    if asking:
        run_id = graph.claim(trip_id, asking[0]["approval_id"], "approved", body.text)
        if run_id is None:
            raise HTTPException(409, "Câu hỏi vừa được trả lời ở nơi khác, hãy tải lại")
        start(graph.resume_claimed, run_id, trip_id, "approved", body.text)  # node ask_user lưu tin nhắn
    else:
        repo.add_message(trip_id, user_id, "user", body.text)
        run_id = repo.create_run("UC-01", trip_id, user_id)
        start(graph.run_uc01, trip_id, user_id, run_id=run_id)
    return {"run_id": run_id, "status": "running"}


@app.get("/api/trips/{trip_id}/itinerary")
def get_itinerary(trip_id: str, user_id: str = Depends(current_user)):
    """Lịch trình mới nhất: slot (kèm tên + lat/lon POI) và vi phạm còn lại."""
    own_trip(trip_id, user_id)
    itinerary = repo.itinerary_for_trip(trip_id)
    if itinerary is None:
        raise HTTPException(404, "Chuyến đi chưa có lịch trình")
    return itinerary


@app.get("/api/memory")
def list_memory(user_id: str = Depends(current_user)):
    """UC-07: bộ nhớ của người dùng trong session (không bao giờ nhận user_id từ request)."""
    return {"items": store.memory_read(user_id), "sensitive_consent": store.active_consent(user_id) is not None}


class MemoryIn(BaseModel):
    value: str


@app.post("/api/memory/consent/revoke")
def revoke_consent(user_id: str = Depends(current_user)):
    """Thu hồi đồng ý lưu mục nhạy cảm → xoá mọi mục sensitive."""
    store.revoke_sensitive_consent(user_id)
    return list_memory(user_id)


@app.patch("/api/memory/{memory_id}")
def edit_memory(memory_id: str, body: MemoryIn, user_id: str = Depends(current_user)):
    try:
        found = store.memory_update(user_id, memory_id, body.value)
    except store.MemoryRuleError as e:
        raise HTTPException(422, str(e)) from None
    if not found:
        raise HTTPException(404, "Không tìm thấy mục bộ nhớ")
    return list_memory(user_id)


@app.delete("/api/memory/{memory_id}")
def delete_memory(memory_id: str, user_id: str = Depends(current_user)):
    if not store.memory_delete(user_id, memory_id):
        raise HTTPException(404, "Không tìm thấy mục bộ nhớ")
    return list_memory(user_id)


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str, request: Request, after: int = 0, user_id: str = Depends(current_user)):
    """SSE các bước của 1 lượt chạy (event = kind trong trace, rồi interrupt / done). Xem agent/src/api/stream.py."""
    own_run(run_id, user_id)
    return StreamingResponse(run_events(run_id, after, request.is_disconnected), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # fmt: skip


@app.get("/api/runs/{run_id}/trace")
def get_trace(run_id: str, user_id: str = Depends(current_user)):
    """Các bước của 1 lượt chạy (node, tool, skill, LLM) cho panel log."""
    own_run(run_id, user_id)
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
