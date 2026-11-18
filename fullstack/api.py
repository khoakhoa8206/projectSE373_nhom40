"""Route phụ /api/ui/* cho giao diện mới, đặt trên API thật của nhóm (agent/src/api/server.py, không sửa file đó).
Chỉ gom dữ liệu để hiển thị; lập lịch, duyệt, bộ nhớ, thuyết minh, nhật ký đều đi qua route thật của P1, P3.
Người dùng luôn lấy từ session cookie, không bao giờ từ body. Chạy bằng run.py ở gốc app/."""

import csv
import json
import os
import re
import threading
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent.db import repo
from agent.schemas import Child, Itinerary, TripProfile
from agent.src.api.server import app, current_user, own_trip, plan_trip
from agent.src.graph import app as graph
from agent.src.graph.checkpoint import open_checkpointer
from agent.src.nodes.verify import extract_regex, verify_and_fix, verify_itinerary
from fullstack.demo_llm import DemoLLM
from fullstack.intake import analyse, detect_lang

HAS_LLM = bool(os.environ.get("LLM_API_KEY"))
if not HAS_LLM:
    graph.make_client = DemoLLM  # không có key: chỉ planner UC-02 là bản giả; thuyết minh, nhật ký vẫn báo cần key

IMAGES = Path(__file__).resolve().parents[1] / "data/destinations/hue/poi_images.csv"
VERIFY_LOCK = threading.Lock()


class TextIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


def poi_images() -> dict:
    if not IMAGES.exists():
        return {}
    with IMAGES.open(encoding="utf-8", newline="") as f:
        return {r["poi_id"]: r | {"illustrative": r["illustrative"] == "1"} for r in csv.DictReader(f)}


def _launch(profile: TripProfile, text: str, user_id: str):
    """Tạo chuyến rồi gọi đúng route lập lịch thật của P1, chạy nền để PWA mở SSE."""
    trip_id = repo.create_trip(user_id)
    repo.add_message(trip_id, user_id, "user", text)
    repo.save_profile(trip_id, profile.model_copy(update={"route": "plan", "missing_info": []}))
    return {"trip_id": trip_id, "run_id": plan_trip(trip_id, True, user_id)["run_id"]}


def _claims(itinerary: dict, trip_id: str, user_id: str):
    """UC-11 chưa ghép vào graph (Phase 3): kiểm lần đầu khi mở chuyến rồi dùng lại kết quả trong bảng claims."""
    read = lambda: repo.query(
        "SELECT * FROM claims WHERE target_type = 'itinerary_slot' AND target_id LIKE ? ORDER BY claim_id",
        (itinerary["itinerary_id"] + ":%",),
    )
    with VERIFY_LOCK:
        if not read():
            run_id = repo.create_run("UC-11", trip_id, user_id)
            verify_itinerary(Itinerary.model_validate(itinerary | {"has_unpriced_item": bool(itinerary["has_unpriced_item"])}),
                             run_id, extractor=extract_regex)  # fmt: skip
            repo.finish_run(run_id, "succeeded", 0, 0, 0.0, 0)
    return read()


def _review(itinerary_id: str):
    """UC-06 thuộc Phase 3: hai bảng còn rỗng thì giao diện ẩn tab Review."""
    reports = repo.query("SELECT * FROM review_reports WHERE itinerary_id = ? ORDER BY round, report_id", (itinerary_id,))
    for r in reports:
        r["findings"] = repo.query("SELECT * FROM review_findings WHERE report_id = ?", (r["report_id"],))
    return {"reports": reports, "coordination": []}


def _journals(trip_id: str):
    """Bản mới nhất của mỗi phạm vi và ngôn ngữ."""
    rows, seen = [], set()
    for r in repo.query("SELECT * FROM journals WHERE trip_id = ? ORDER BY created_at DESC, rowid DESC", (trip_id,)):
        if (key := (r["scope"], r["day_index"], r["lang"])) not in seen:
            seen.add(key)
            rows.append(r | {"content": json.loads(r["content"]), "event_ids": json.loads(r["event_ids"])})
    return sorted(rows, key=lambda r: (r["scope"] != "trip", r["day_index"] or 0))


@app.get("/api/ui/meta")
def meta():
    return {"llm": HAS_LLM}


@app.get("/api/ui/me")
def me(request: Request):
    return {"user_id": request.session.get("user_id")}


@app.post("/api/ui/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/ui/catalog")
def catalog():
    images = poi_images()
    kb = {r["poi_id"] for r in repo.query(
        "SELECT DISTINCT poi_id FROM kb_documents WHERE poi_id IS NOT NULL AND is_fictional = 0 AND doc_type <> 'review'")}  # fmt: skip
    rows = repo.query("SELECT * FROM pois WHERE destination_id = 'hue' ORDER BY poi_id")
    return [r | {"tags": json.loads(r["tags"]), "image": images.get(r["poi_id"]), "has_story": r["poi_id"] in kb} for r in rows]


@app.get("/api/ui/pois/{poi_id}")
def poi(poi_id: str):
    rows = repo.query("SELECT * FROM pois WHERE poi_id = ?", (poi_id,))
    if not rows:
        raise HTTPException(404, "Không tìm thấy địa điểm")
    about = repo.query(
        """SELECT d.lang, d.title, c.section, c.text, d.doc_id, d.source_url, d.license FROM kb_chunks c JOIN kb_documents d USING (doc_id)
           WHERE d.poi_id = ? AND d.is_fictional = 0 AND d.doc_type <> 'review' ORDER BY d.doc_id, c.chunk_index""",
        (poi_id,),
    )
    nearby = repo.query(
        """SELECT p.poi_id, p.name_vi, p.name_en, p.category, t.minutes FROM travel_matrix t JOIN pois p ON p.poi_id = t.to_poi_id
           WHERE t.from_poi_id = ? AND t.mode = 'drive' AND t.to_poi_id <> ? AND p.category = 'attraction' ORDER BY t.minutes LIMIT 6""",
        (poi_id, poi_id),
    )
    return rows[0] | {"tags": json.loads(rows[0]["tags"]), "image": poi_images().get(poi_id), "about": about, "nearby": nearby}


@app.post("/api/ui/start-form")
def start_form(profile: TripProfile, user_id: str = Depends(current_user)):
    if not (profile.start_date and profile.end_date and profile.adults):
        raise HTTPException(400, "Cần có ngày đi, ngày về và số người lớn")
    if profile.adults + len(profile.children) > 6:
        raise HTTPException(400, "Hệ thống chỉ lập lịch cho nhóm từ 1 đến 6 người")
    if len(profile.mobility_notes or "") > 500:
        raise HTTPException(400, "Ghi chú tối đa 500 ký tự")
    children = f", trẻ em {', '.join(str(c.age) for c in profile.children)} tuổi" if profile.children else ""
    budget = f", ngân sách {profile.budget_total_vnd:,} đ".replace(",", ".") if profile.budget_total_vnd else ""
    return _launch(profile, f"Huế từ {profile.start_date} đến {profile.end_date}, {profile.adults} người lớn{children}{budget}", user_id)


@app.post("/api/ui/start-text")
def start_text(body: TextIn, user_id: str = Depends(current_user)):
    """ponytail: đọc lời kể bằng luật, thiếu thông tin thì báo điền form; thay bằng UC-01 khi P2 có node intake và interrupt ask_user."""
    f = analyse(body.text)
    if f["route"] == "unsupported":
        raise HTTPException(422, f"Hiện chỉ có dữ liệu đã xác minh cho Huế, chưa có cho {f['destination']}.")
    if f["route"] == "ask_user":
        raise HTTPException(422, " ".join([*f["conflicts"], *(q["text"] for q in f["questions"])]) + " Hãy ghi thêm hoặc dùng form.")
    profile = TripProfile(start_date=f["start_date"], end_date=f["end_date"], adults=f["adults"], children=[Child(age=a) for a in f["children"]],
                          budget_total_vnd=f["budget"], interests=f["interests"], pace=f["pace"] or "moderate", language=f["lang"],
                          mobility_notes=f["mobility_notes"], hard_constraints=f["constraints"])  # fmt: skip
    return _launch(profile, body.text, user_id)


@app.get("/api/ui/trips")
def my_trips(user_id: str = Depends(current_user)):
    return repo.query(
        """SELECT t.trip_id, t.status, t.created_at, p.start_date, p.end_date, p.adults, p.budget_total_vnd,
               (SELECT content FROM messages m WHERE m.trip_id = t.trip_id AND m.role = 'user' ORDER BY created_at LIMIT 1) AS request,
               (SELECT 1 FROM approvals a WHERE a.trip_id = t.trip_id AND a.decision = 'pending' LIMIT 1) AS waiting
           FROM trips t JOIN trip_profiles p ON p.trip_id = t.trip_id AND p.version =
               (SELECT MAX(version) FROM trip_profiles x WHERE x.trip_id = t.trip_id)
           WHERE t.user_id = ? ORDER BY t.created_at DESC, t.rowid DESC""",
        (user_id,),
    )


@app.get("/api/ui/trips/{trip_id}")
def trip_detail(trip_id: str, user_id: str = Depends(current_user)):
    own_trip(trip_id, user_id)
    _, profile = repo.latest_profile(trip_id)
    itinerary = repo.itinerary_for_trip(trip_id)
    pending = graph.pending_approvals(trip_id)
    runs = repo.query("SELECT run_id, uc, status, started_at, latency_ms, tokens_in, tokens_out FROM runs WHERE trip_id = ? ORDER BY started_at DESC, rowid DESC", (trip_id,))
    return {
        "trip": repo.query("SELECT * FROM trips WHERE trip_id = ?", (trip_id,))[0],
        "profile": profile.model_dump(mode="json") if profile else None,
        "pending": pending[0] if pending else None,
        "itinerary": itinerary,
        "claims": _claims(itinerary, trip_id, user_id) if itinerary else [],
        "review": _review(itinerary["itinerary_id"]) if itinerary else {"reports": [], "coordination": []},
        "events": repo.trip_events(trip_id),
        "journal": _journals(trip_id),
        "runs": runs,
        "running": any(r["status"] == "running" for r in runs),
    }


@app.delete("/api/ui/trips/{trip_id}")
def delete_trip(trip_id: str, user_id: str = Depends(current_user)):
    own_trip(trip_id, user_id)
    repo.query("DELETE FROM claims WHERE run_id IN (SELECT run_id FROM runs WHERE trip_id = ?)", (trip_id,))
    repo.query("DELETE FROM trips WHERE trip_id = ?", (trip_id,))
    with open_checkpointer() as saver:
        saver.delete_thread(trip_id)
    return {"ok": True}


@app.post("/api/ui/verify")
def verify(body: TextIn, user_id: str = Depends(current_user)):
    """UC-11 trên văn bản tự do: nháp vào, trả bản đã sửa theo nguồn và nhãn từng dữ kiện."""
    run_id = repo.create_run("UC-11", None, user_id)
    result = verify_and_fix(body.text, run_id, "manual", ctx={"destination_id": "hue", "lang": detect_lang(body.text)},
                            extractor=None if HAS_LLM else extract_regex)  # fmt: skip
    repo.finish_run(run_id, "succeeded", 0, 0, 0.0, 0)
    claims = [c.model_dump() for c in result["claims"]]
    return {"text": result["text"], "blocked": result["blocked"], "claims": claims, "lines": by_line(result["text"], claims), "run_id": run_id}


def by_line(text: str, claims: list[dict]) -> list[dict]:
    """Mỗi câu một dòng kèm nhãn của dữ kiện trong câu. Câu đã sửa chứa corrected_text thay cho claim_text.
    Mỗi lần khớp xoá đúng một chỗ, nên hai câu cùng ghi một con số không dồn nhãn vào câu đầu."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if s]
    lines, rest = [{"text": s, "claims": []} for s in sentences], list(sentences)
    for claim in claims:
        needle = claim["corrected_text"] or claim["claim_text"]
        # không tìm thấy (bản bị chặn, thay bằng câu cảnh báo) thì gắn vào dòng cuối để không mất nhãn
        i = next((i for i, s in enumerate(rest) if needle in s), len(lines) - 1)
        rest[i] = rest[i].replace(needle, "\0", 1)
        lines[i]["claims"].append(claim)
    return lines
