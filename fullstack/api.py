"""Route phụ /api/ui/* cho giao diện mới, đặt trên API thật của nhóm (agent/src/api/server.py, không sửa file đó).
Chỉ gom dữ liệu để hiển thị; lập lịch, duyệt, bộ nhớ, thuyết minh, nhật ký đều đi qua route thật của P1, P3.
Người dùng luôn lấy từ session cookie, không bao giờ từ body. Chạy bằng run.py ở gốc app/."""

import csv
import functools
import json
import os
import re
import threading
from pathlib import Path

import httpx
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agent.db import repo
from agent.schemas import Child, Itinerary, TripProfile
from agent.src.api import server
from agent.src.api.server import app, current_user, own_trip, plan_trip
from agent.src.graph import app as graph
from agent.src.graph.checkpoint import open_checkpointer
from agent.src.nodes.verify import extract_regex, verify_and_fix, verify_itinerary
from fullstack.demo_llm import DemoLLM
from fullstack.intake import analyse, detect_lang

HAS_LLM = bool(os.environ.get("LLM_API_KEY"))
if not HAS_LLM:
    graph.make_client = DemoLLM  # không có key: chỉ planner UC-02 là bản giả; thuyết minh, nhật ký vẫn báo cần key
    server.REVIEW = False  # 3 reviewer UC-06 cần LLM thật, planner giả không review được

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


def _review(itinerary: dict):
    """UC-06: báo cáo mọi vòng review của lượt chạy (vòng 1 nằm ở bản lịch trước, đã superseded) kèm tên POI của slot,
    và coordination trace (orchestrator ↔ reviewer ↔ planner) dựng từ trace_events của lượt chạy đó."""
    run_id = itinerary["run_id"]
    reports = repo.query(
        """SELECT r.* FROM review_reports r JOIN itineraries i USING (itinerary_id) WHERE i.run_id = ?
           ORDER BY r.created_at, r.round, r.reviewer""",
        (run_id,),
    )
    for r in reports:
        r["findings"] = repo.query(
            """SELECT f.*, s.day_index, s.start_time, p.name_vi, p.name_en FROM review_findings f
               LEFT JOIN itinerary_slots s ON s.slot_id = f.slot_ref LEFT JOIN pois p ON p.poi_id = s.poi_id
               WHERE f.report_id = ? ORDER BY f.finding_id""",
            (r["report_id"],),
        )
    events = repo.query(
        """SELECT ts, node, kind, name, args, result, error FROM trace_events WHERE run_id = ?
           AND (node LIKE 'reviewer.%' OR (node = 'review' AND kind = 'guardrail')) ORDER BY seq""",
        (run_id,),
    )
    return {"reports": reports, "coordination": [m for e in events if (m := _message(e))]}


def _message(e):
    """1 dòng trace của UC-06 → 1 thông điệp giữa các agent; tool_call / llm_call xem ở trace viewer."""
    who = e["node"].removeprefix("reviewer.")
    args, result = (json.loads(e[k]) if e[k] else {} for k in ("args", "result"))
    msg = {"ts": e["ts"], "from": "orchestrator", "to": who}
    if e["kind"] == "node_start":
        return msg | {"message": f"gửi lịch trình {args.get('itinerary_id')} để review vòng {args.get('round')}"}
    if e["kind"] == "node_end":
        verdict = "chấp thuận" if result.get("verdict") == "approve" else "yêu cầu sửa"
        return msg | {"from": who, "to": "orchestrator", "message": f"{verdict}, {len(result.get('findings', []))} phát hiện"}
    if e["kind"] == "error":
        return msg | {"from": who, "to": "orchestrator", "message": f"lỗi, bỏ qua ý kiến của reviewer này ({e['error'][:120]})"}
    if e["name"] == "tool_denied":
        return msg | {"from": "harness", "message": f"chặn tool {args.get('tool')} (không có trong permissions.yaml)"}
    if e["name"] == "unknown_slot_ref":
        return msg | {"message": f"bỏ phát hiện trỏ slot không tồn tại: {', '.join(map(str, result.get('dropped', [])))}"}
    if e["name"] == "review_round":
        if result.get("again"):
            return msg | {"to": "planner", "message": f"gửi {result.get('to_fix')} phát hiện mức trung bình/cao để lập lại lịch"}
        return msg | {"to": "người dùng", "message": f"chốt lịch trình sau {result.get('round')} vòng review"}
    return None


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


# Cùng nguồn/profile với travel_matrix (scripts/build_travel_matrix.py). Máy chủ demo công cộng hay chập chờn
# (18/11 router.project-osrm.org hết thời gian kết nối) nên thử lần lượt, máy chủ FOSSGIS làm dự phòng.
OSRM_URLS = ("https://router.project-osrm.org/route/v1/driving", "https://routing.openstreetmap.de/routed-car/route/v1/driving")


# ponytail: cache trong process (512 tuyến), restart là hỏi lại OSRM; cần chạy offline thì lưu tuyến vào data/ như ma trận
@functools.lru_cache(maxsize=512)
def _osrm_route(points: tuple[tuple[float, float], ...]) -> dict:
    coords = ";".join(f"{lon},{lat}" for lat, lon in points)
    for i, base in enumerate(OSRM_URLS):
        try:
            r = httpx.get(f"{base}/{coords}", params={"overview": "full", "geometries": "geojson"},
                          timeout=httpx.Timeout(15, connect=10),
                          follow_redirects=False)  # fmt: skip
            r.raise_for_status()
            route = r.json()["routes"][0]
            break
        except (httpx.HTTPError, KeyError, IndexError, ValueError):
            if i == len(OSRM_URLS) - 1:
                raise
    return {"coordinates": [[lat, lon] for lon, lat in route["geometry"]["coordinates"]],
            "distance_m": round(route["distance"]), "duration_min": round(route["duration"] / 60)}  # fmt: skip


@app.get("/api/ui/route")
def route(pois: str, user_id: str = Depends(current_user)):
    """Đường đi thực tế (OSRM, ô tô) qua các POI theo thứ tự. Chỉ gửi toạ độ POI công khai, không bao giờ gửi vị trí
    người dùng. OSRM lỗi / mất mạng → coordinates = null, bản đồ vẽ nét đứt nối thẳng và ghi rõ."""
    ids = pois.split(",")
    if not 2 <= len(ids) <= 25:
        raise HTTPException(422, "Cần 2–25 poi_id")
    rows = {r["poi_id"]: r for r in repo.query(
        f"SELECT poi_id, lat, lon FROM pois WHERE poi_id IN ({','.join('?' * len(ids))})", ids)}  # fmt: skip
    if any(i not in rows for i in ids):
        raise HTTPException(404, "Không tìm thấy POI")
    try:
        return _osrm_route(tuple((rows[i]["lat"], rows[i]["lon"]) for i in ids)) | {"source": "osrm"}
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return {"coordinates": None, "source": None}


@app.get("/api/ui/activity")
def activity(user_id: str = Depends(current_user)):
    """Chuyến có agent đang chạy nền, đang chờ người dùng, hoặc lượt lập lịch gần nhất bị lỗi (không im lặng biến mất):
    PWA hiện thanh báo ở mọi trang."""
    return repo.query(
        """SELECT t.trip_id,
               EXISTS (SELECT 1 FROM runs r WHERE r.trip_id = t.trip_id AND r.status = 'running') AS running,
               (SELECT kind FROM approvals a WHERE a.trip_id = t.trip_id AND a.decision = 'pending'
                ORDER BY a.created_at LIMIT 1) AS waiting,
               (SELECT r.status FROM runs r WHERE r.trip_id = t.trip_id AND r.uc IN ('UC-01', 'UC-02')
                ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1) = 'failed' AS failed
           FROM trips t WHERE t.user_id = ? AND (running OR waiting IS NOT NULL OR failed)
           ORDER BY t.updated_at DESC""",
        (user_id,),
    )


@app.get("/api/ui/trips/{trip_id}/messages")
def trip_messages(trip_id: str, user_id: str = Depends(current_user)):
    """Hội thoại UC-01 của chuyến: trang chat mở lại vẫn thấy, không lưu nội dung trong trình duyệt."""
    own_trip(trip_id, user_id)
    return repo.query("SELECT role, content FROM messages WHERE trip_id = ? AND role IN ('user', 'assistant')"
                      " ORDER BY created_at, rowid", (trip_id,))  # fmt: skip


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
        "review": _review(itinerary) if itinerary else {"reports": [], "coordination": []},
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
