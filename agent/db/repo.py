"""Tầng DB dùng chung (hợp đồng P1 → cả nhóm, mục 3 file nhiệm vụ).
Mỗi hàm tự mở/đóng kết nối nên gọi được từ nhiều thread (FastAPI). Đổi DB bằng biến môi trường DB_PATH."""

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone

from pydantic_core import to_jsonable_python

from agent.schemas import POI, Itinerary, TripEvent, TripProfile, Violation
from agent.src.obs.trace import mask_coords, write_jsonl

VN = timezone(timedelta(hours=7))  # Việt Nam không có giờ mùa hè


def now():
    return datetime.now(VN).isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _json(x):
    return None if x is None else json.dumps(x, ensure_ascii=False)


def get_conn():
    conn = sqlite3.connect(os.environ.get("DB_PATH", "tourguide.db"), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(sql, params=()):
    """Chạy 1 câu SQL trong 1 transaction, trả list[dict]."""
    with closing(get_conn()) as conn, conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def create_user(display_name, preferred_lang="vi", user_id=None):
    user_id = user_id or new_id("u")
    query("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?)", (user_id, display_name, preferred_lang, now()))
    return user_id


def get_user(user_id):
    rows = query("SELECT user_id, display_name, preferred_lang FROM users WHERE user_id = ?", (user_id,))
    return rows[0] if rows else None


def create_account(display_name, preferred_lang, email, password_hash):
    """Tạo users + credentials trong 1 transaction. Email đã có → sqlite3.IntegrityError."""
    user_id, ts = new_id("u"), now()
    with closing(get_conn()) as conn, conn:
        conn.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user_id, display_name, preferred_lang, ts))
        conn.execute("INSERT INTO credentials VALUES (?, ?, ?, ?)", (user_id, email, password_hash, ts))
    return user_id


def account_by_email(email):
    rows = query("SELECT user_id, password_hash FROM credentials WHERE email = ?", (email,))
    return rows[0] if rows else None


def create_trip(user_id, destination_id="hue"):
    trip_id, ts = new_id("t"), now()
    query(
        "INSERT INTO trips (trip_id, user_id, destination_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (trip_id, user_id, destination_id, ts, ts),
    )
    return trip_id


def add_message(trip_id, user_id, role, content, lang=None, run_id=None):
    message_id = new_id("m")
    query(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (message_id, trip_id, user_id, role, content, lang, run_id, now()),
    )
    return message_id


def save_profile(trip_id, profile: TripProfile, run_id=None):
    """Lưu hồ sơ thành phiên bản mới (version tự tăng theo trip). Trả profile_id."""
    p = profile.model_dump(mode="json")
    rows = query(
        """INSERT INTO trip_profiles (trip_id, version, start_date, end_date, adults, children, mobility_notes,
               budget_total_vnd, budget_includes, interests, pace, language, hard_constraints, missing_info, route,
               raw_json, run_id, created_at)
           VALUES (:trip_id, (SELECT COALESCE(MAX(version), 0) + 1 FROM trip_profiles WHERE trip_id = :trip_id),
               :start_date, :end_date, :adults, :children, :mobility_notes, :budget_total_vnd, :budget_includes,
               :interests, :pace, :language, :hard_constraints, :missing_info, :route, :raw_json, :run_id, :created_at)
           RETURNING profile_id""",
        p
        | {k: _json(p[k]) for k in ("children", "budget_includes", "interests", "hard_constraints", "missing_info")}
        | {"trip_id": trip_id, "raw_json": profile.model_dump_json(), "run_id": run_id, "created_at": now()},
    )
    return rows[0]["profile_id"]


def latest_profile(trip_id):
    """(profile_id, TripProfile) của phiên bản mới nhất, hoặc (None, None)."""
    rows = query(
        "SELECT profile_id, raw_json FROM trip_profiles WHERE trip_id = ? ORDER BY version DESC LIMIT 1", (trip_id,)
    )
    return (rows[0]["profile_id"], TripProfile.model_validate_json(rows[0]["raw_json"])) if rows else (None, None)


def create_run(uc, trip_id, user_id, eval_case_id=None):
    run_id = new_id("r")
    query(
        "INSERT INTO runs (run_id, trip_id, user_id, uc, status, started_at, eval_case_id)"
        " VALUES (?, ?, ?, ?, 'running', ?, ?)",
        (run_id, trip_id, user_id, uc, now(), eval_case_id),
    )
    return run_id


def finish_run(run_id, status, tokens_in, tokens_out, cost_usd, latency_ms):
    """Cộng dồn: 1 run có thể chạy nhiều đoạn (dừng chờ người dùng / backend restart rồi chạy tiếp)."""
    query(
        "UPDATE runs SET status = ?, ended_at = ?, tokens_in = tokens_in + ?, tokens_out = tokens_out + ?,"
        " cost_usd = cost_usd + ?, latency_ms = COALESCE(latency_ms, 0) + ? WHERE run_id = ?",
        (status, now(), tokens_in, tokens_out, cost_usd, latency_ms, run_id),
    )


def log_event(run_id, node, kind, name=None, args=None, result=None, duration_ms=None, tokens=None, error=None):
    """Ghi 1 bước vào trace_events (seq tự tăng theo run_id) và traces/<run_id>.jsonl. Toạ độ được làm thô."""
    args, result = (None if x is None else mask_coords(to_jsonable_python(x, fallback=str)) for x in (args, result))
    ev = {"run_id": run_id, "ts": now(), "node": node, "kind": kind, "name": name, "args": args, "result": result,
          "duration_ms": duration_ms, "tokens": tokens, "error": error}  # fmt: skip
    ev["seq"] = query(
        """INSERT INTO trace_events (run_id, seq, ts, node, kind, name, args, result, duration_ms, tokens, error)
           VALUES (:run_id, (SELECT COALESCE(MAX(seq), 0) + 1 FROM trace_events WHERE run_id = :run_id),
               :ts, :node, :kind, :name, :args, :result, :duration_ms, :tokens, :error)
           RETURNING seq""",
        ev | {"args": _json(args), "result": _json(result)},
    )[0]["seq"]
    write_jsonl(run_id, ev)
    return ev["seq"]


def weather_for_run(run_id):
    """{forecast_date: dòng weather_snapshots} mà tool thời tiết đã ghi trong lượt chạy này."""
    rows = query("SELECT * FROM weather_snapshots WHERE run_id = ? ORDER BY snapshot_id", (run_id,))
    return {r["forecast_date"]: r for r in rows}


def save_itinerary(it: Itinerary, history: list[tuple[int, Violation]]):
    """Lưu lịch trình cuối + vi phạm của mọi vòng (vòng trước vòng cuối = đã sửa). Tổng tiền do code cộng."""
    slot_ids = {s.slot_id for s in it.slots}
    with closing(get_conn()) as conn, conn:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM itineraries WHERE trip_id = ?", (it.trip_id,)
        ).fetchone()[0]
        conn.execute("UPDATE itineraries SET status = 'superseded' WHERE trip_id = ?", (it.trip_id,))
        conn.execute(
            """INSERT INTO itineraries (itinerary_id, trip_id, profile_id, version, status, planner_rounds,
                   total_cost_vnd, has_unpriced_item, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (it.itinerary_id, it.trip_id, it.profile_id, version, it.status, it.planner_rounds,
             # tổng các khoản đã biết giá; có khoản thiếu giá thì has_unpriced_item = 1 (UI ghi "chưa có giá")
             sum(s.cost_vnd or 0 for s in it.slots), int(any(s.cost_source == "unverified" for s in it.slots)),
             it.run_id, now()),
        )  # fmt: skip
        conn.executemany(
            """INSERT INTO itinerary_slots VALUES (:slot_id, :itinerary_id, :day_index, :slot_date, :start_time,
                   :end_time, :poi_id, :activity, :travel_minutes_from_prev, :cost_vnd, :cost_source, :hours_status,
                   :note, :progress)""",
            [s.model_dump(mode="json") | {"itinerary_id": it.itinerary_id} for s in it.slots],
        )
        conn.executemany(
            "INSERT INTO validation_violations (itinerary_id, round, slot_id, rule, severity, message, resolved)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(it.itinerary_id, r, v.slot_id if v.slot_id in slot_ids else None, v.rule, v.severity, v.message,
              int(r < it.planner_rounds)) for r, v in history],
        )  # fmt: skip
        conn.execute(
            "UPDATE trips SET status = 'awaiting_approval', updated_at = ? WHERE trip_id = ?", (now(), it.trip_id)
        )


def itinerary_for_trip(trip_id):
    """Lịch trình mới nhất của trip kèm slot (tên + toạ độ POI để vẽ bản đồ) và các vi phạm còn lại."""
    its = query("SELECT * FROM itineraries WHERE trip_id = ? ORDER BY version DESC LIMIT 1", (trip_id,))
    if not its:
        return None
    it = its[0]
    it["slots"] = query(
        """SELECT s.*, p.name_vi, p.name_en, p.lat, p.lon FROM itinerary_slots s LEFT JOIN pois p USING (poi_id)
           WHERE s.itinerary_id = ? ORDER BY s.day_index, s.start_time""",
        (it["itinerary_id"],),
    )
    it["violations"] = query(
        "SELECT * FROM validation_violations WHERE itinerary_id = ? AND resolved = 0", (it["itinerary_id"],)
    )
    return it

def _upsert_hue_pois(conn, pois: list[POI]) -> int:
    """Nạp POI trên transaction do caller quản lý."""
    if not pois:
        raise ValueError("Không có POI để nạp.")
    if any(poi.destination_id != "hue" for poi in pois):
        raise ValueError("Chỉ nhận POI thuộc Huế.")

    columns = list(POI.model_fields)
    column_names = ", ".join(columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in columns
        if column not in ("poi_id", "destination_id")
    )
    sql = (
        f"INSERT INTO pois ({column_names}) VALUES ({placeholders}) "
        f"ON CONFLICT(poi_id) DO UPDATE SET {updates}"
    )

    conn.execute(
        """INSERT INTO destinations (destination_id, name_vi, name_en)
           VALUES (?, ?, ?) ON CONFLICT(destination_id) DO NOTHING""",
        ("hue", "Huế", "Hue"),
    )
    for poi in pois:
        existing = conn.execute("SELECT destination_id FROM pois WHERE poi_id = ?", (poi.poi_id,)).fetchone()
        if existing and existing["destination_id"] != "hue":
            raise ValueError(f"Mã POI đã thuộc điểm đến khác: {poi.poi_id}")
        row = poi.model_dump()
        row["tags"] = json.dumps(poi.tags, ensure_ascii=False)
        conn.execute(sql, row)

    return len(pois)


def save_hue_pois(pois: list[POI]) -> int:
    """Nạp POI Huế trong một transaction; mã đã có thì cập nhật."""
    with closing(get_conn()) as conn, conn:
        return _upsert_hue_pois(conn, pois)


def save_hue_destination(pois: list[POI], zones: list[dict], matrix: list[dict]) -> dict:
    """Nạp bundle đã kiểm tra nguyên tử; không xoá POI cũ hoặc dữ liệu chuyến đi."""
    with closing(get_conn()) as conn, conn:
        count = _upsert_hue_pois(conn, pois)
        for zone in zones:
            existing = conn.execute("SELECT destination_id FROM restricted_zones WHERE zone_id = ?",
                                    (zone["zone_id"],)).fetchone()
            if existing and existing[0] != "hue":
                raise ValueError("Mã vùng đã thuộc điểm đến khác.")
            conn.execute(
                """INSERT INTO restricted_zones (zone_id, destination_id, name, zone_type, geometry, active_from,
                       active_to, reason, source_url, license, verified_at)
                   VALUES (:zone_id, :destination_id, :name, :zone_type, :geometry, :active_from, :active_to,
                       :reason, :source_url, :license, :verified_at)
                   ON CONFLICT(zone_id) DO UPDATE SET name=excluded.name, zone_type=excluded.zone_type,
                       geometry=excluded.geometry, active_from=excluded.active_from, active_to=excluded.active_to,
                       reason=excluded.reason, source_url=excluded.source_url, license=excluded.license,
                       verified_at=excluded.verified_at""", zone,
            )
        conn.executemany(
            """INSERT INTO travel_matrix (from_poi_id, to_poi_id, mode, minutes, distance_m, provider, computed_at)
               VALUES (:from_poi_id, :to_poi_id, :mode, :minutes, :distance_m, :provider, :computed_at)
               ON CONFLICT(from_poi_id, to_poi_id, mode) DO UPDATE SET minutes=excluded.minutes,
                   distance_m=excluded.distance_m, provider=excluded.provider, computed_at=excluded.computed_at""", matrix,
        )
    return {"pois": count, "zones": len(zones), "travel_pairs": len(matrix)}


def destination_facts() -> dict:
    """Snapshot chỉ đọc cho validator; không mạng, không ghi, không log toạ độ người dùng."""
    with closing(get_conn()) as conn, conn:
        return {"pois": {r["poi_id"]: dict(r) for r in conn.execute("SELECT * FROM pois")},
                "matrix": [dict(r) for r in conn.execute("SELECT * FROM travel_matrix")],
                "zones": [dict(r) for r in conn.execute("SELECT * FROM restricted_zones")]}


# --- Kho tri thức UC-03 (P3) ---
KB_DOC_COLS = ("doc_id", "poi_id", "lang", "title", "doc_type", "is_fictional", "source_url", "license", "retrieved_at")


def save_kb(docs: list[dict], chunks: list[dict]) -> dict:
    """Nạp lại kho tri thức trong 1 transaction (upsert theo id). Tài liệu/chunk không còn trong kho thì xoá, trừ chunk
    đã có citations: giữ lại với vector_id = NULL (không còn được tìm thấy) để không mất lịch sử trích dẫn."""
    with closing(get_conn()) as conn, conn:
        conn.execute("UPDATE kb_chunks SET vector_id = NULL")
        conn.executemany(
            f"INSERT INTO kb_documents ({', '.join(KB_DOC_COLS)}) VALUES ({', '.join(':' + c for c in KB_DOC_COLS)})"
            f" ON CONFLICT(doc_id) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in KB_DOC_COLS[1:])}",
            docs,
        )
        conn.executemany(
            """INSERT INTO kb_chunks (chunk_id, doc_id, section, chunk_index, text, vector_id)
               VALUES (:chunk_id, :doc_id, :section, :chunk_index, :text, :vector_id)
               ON CONFLICT(chunk_id) DO UPDATE SET doc_id = excluded.doc_id, section = excluded.section,
                   chunk_index = excluded.chunk_index, text = excluded.text, vector_id = excluded.vector_id""",
            chunks,
        )
        conn.execute(
            "DELETE FROM kb_chunks WHERE vector_id IS NULL AND chunk_id NOT IN (SELECT chunk_id FROM citations)"
        )
        conn.execute(
            "DELETE FROM kb_documents WHERE doc_id NOT IN (SELECT value FROM json_each(?))"
            " AND doc_id NOT IN (SELECT doc_id FROM kb_chunks)",
            (json.dumps([d["doc_id"] for d in docs]),),
        )
    return {"documents": len(docs), "chunks": len(chunks)}


def latest_trip_id(user_id):
    """trip_id mới nhất của người dùng (UC-03 gắn messages vào chuyến đi gần nhất), None nếu chưa có."""
    rows = query("SELECT trip_id FROM trips WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (user_id,))
    return rows[0]["trip_id"] if rows else None


def kb_chunks_for_docs(doc_ids) -> list[dict]:
    """Mọi chunk (kể cả chunk cũ giữ cho lịch sử) của các tài liệu có trong kb_documents, cho validator trích dẫn."""
    return query(
        """SELECT c.chunk_id, c.doc_id, c.section, c.chunk_index, c.text
           FROM kb_chunks c JOIN kb_documents d USING (doc_id)
           WHERE c.doc_id IN (SELECT value FROM json_each(?)) ORDER BY c.doc_id, c.chunk_index""",
        (json.dumps(sorted(doc_ids)),),
    )


def save_citations(rows: list[tuple]) -> int:
    """Ghi [(message_id, chunk_id, quote, is_valid)] vào bảng citations trong 1 transaction."""
    with closing(get_conn()) as conn, conn:
        conn.executemany("INSERT INTO citations (message_id, chunk_id, quote, is_valid) VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def kb_search_rows(lang=None, poi_id=None) -> list[dict]:
    """Chunk đang có vector kèm metadata tài liệu (cho retriever), lọc tuỳ chọn theo lang, poi_id."""
    return query(
        """SELECT c.chunk_id, c.doc_id, c.section, c.chunk_index, c.text, c.vector_id, d.poi_id, d.lang, d.title,
                  d.doc_type, d.is_fictional, d.source_url, d.license
           FROM kb_chunks c JOIN kb_documents d USING (doc_id)
           WHERE c.vector_id IS NOT NULL AND (:lang IS NULL OR d.lang = :lang)
             AND (:poi_id IS NULL OR d.poi_id = :poi_id)
           ORDER BY CAST(c.vector_id AS INTEGER)""",
        {"lang": lang, "poi_id": poi_id},
    )


# --- Nhật ký chuyến đi UC-09 (P3) ---
def add_trip_event(ev: TripEvent) -> str:
    """Ghi 1 sự kiện (gửi lại cùng event_id của cùng trip thì bỏ qua). slot_done/slot_skipped cập nhật
    itinerary_slots.progress. Trả event_id; event_id đã thuộc trip khác → ValueError."""
    event_id = ev.event_id or new_id("ev")
    at = ev.occurred_at if ev.occurred_at.tzinfo else ev.occurred_at.replace(tzinfo=VN)
    with closing(get_conn()) as conn, conn:
        owner = conn.execute("SELECT trip_id FROM trip_events WHERE event_id = ?", (event_id,)).fetchone()
        if owner and owner[0] != ev.trip_id:
            raise ValueError(f"event_id {event_id} đã thuộc chuyến đi khác")
        conn.execute(
            """INSERT OR IGNORE INTO trip_events (event_id, trip_id, occurred_at, day_index, event_type, slot_id,
                   poi_id, amount_vnd, payload, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, ev.trip_id, at.isoformat(timespec="seconds"), ev.day_index, ev.event_type, ev.slot_id, ev.poi_id,
             ev.amount_vnd, _json(ev.payload), ev.created_by),
        )  # fmt: skip
        if ev.slot_id and ev.event_type in ("slot_done", "slot_skipped"):
            conn.execute("UPDATE itinerary_slots SET progress = ? WHERE slot_id = ?",
                         ("done" if ev.event_type == "slot_done" else "skipped", ev.slot_id))  # fmt: skip
    return event_id


def trip_events(trip_id, day_index=None) -> list[dict]:
    """Sự kiện của chuyến (hoặc 1 ngày) theo thứ tự thời gian, kèm tên POI; payload đã parse JSON."""
    rows = query(
        """SELECT e.*, p.name_vi, p.name_en FROM trip_events e LEFT JOIN pois p USING (poi_id)
           WHERE e.trip_id = ? AND (? IS NULL OR e.day_index = ?) ORDER BY e.day_index, e.occurred_at, e.event_id""",
        (trip_id, day_index, day_index),
    )
    return [r | {"payload": json.loads(r["payload"])} for r in rows]


def sum_expenses(trip_id, day_index=None) -> dict:
    """Tổng chi do SQL cộng (SUM(amount_vnd) của sự kiện expense), không bao giờ để LLM tự cộng."""
    row = query(
        """SELECT COALESCE(SUM(amount_vnd), 0) AS total_vnd, COUNT(*) AS expense_count,
                  COALESCE(json_group_array(event_id), '[]') AS event_ids
           FROM trip_events WHERE trip_id = ? AND event_type = 'expense' AND (? IS NULL OR day_index = ?)""",
        (trip_id, day_index, day_index),
    )[0]
    return {"total_vnd": row["total_vnd"], "expense_count": row["expense_count"],
            "event_ids": [e for e in json.loads(row["event_ids"]) if e]}  # fmt: skip


def save_journal(trip_id, scope, day_index, lang, content, event_ids, total_spent_vnd, tokens_before, tokens_after,
                 run_id) -> str:
    journal_id = new_id("j")
    query(
        """INSERT INTO journals (journal_id, trip_id, scope, day_index, lang, content, event_ids, total_spent_vnd,
               tokens_before, tokens_after, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (journal_id, trip_id, scope, day_index, lang, _json(content), _json(event_ids), total_spent_vnd, tokens_before,
         tokens_after, run_id, now()),
    )  # fmt: skip
    return journal_id


def latest_journal(trip_id, scope, day_index, lang):
    """Nhật ký mới nhất cùng phạm vi + ngôn ngữ (content, event_ids đã parse JSON), None nếu chưa có."""
    rows = query(
        """SELECT * FROM journals WHERE trip_id = ? AND scope = ? AND day_index IS ? AND lang = ?
           ORDER BY created_at DESC, rowid DESC LIMIT 1""",
        (trip_id, scope, day_index, lang),
    )
    if not rows:
        return None
    return rows[0] | {"content": json.loads(rows[0]["content"]), "event_ids": json.loads(rows[0]["event_ids"])}

def prepare_itinerary_approval(itinerary_id, trip_id, user_id, run_id):
    """ID ổn định khi node interrupt replay; chỉ duyệt bản mới nhất đúng owner."""
    approval_id = f"ap-{itinerary_id}"
    with closing(get_conn()) as conn, conn:
        current = conn.execute(
            """SELECT i.itinerary_id FROM itineraries i JOIN trips t USING(trip_id)
               WHERE i.trip_id=? AND t.user_id=? ORDER BY i.version DESC LIMIT 1""", (trip_id, user_id),
        ).fetchone()
        if current is None or current[0] != itinerary_id:
            raise ValueError("Lịch trình không thuộc người dùng hoặc không còn là bản mới nhất.")
        conn.execute(
            """INSERT OR IGNORE INTO approvals (approval_id, trip_id, run_id, kind, payload, created_at)
               VALUES (?, ?, ?, 'itinerary_approval', ?, ?)""",
            (approval_id, trip_id, run_id, _json({"itinerary_id": itinerary_id}), now()),
        )
    return approval_id


def decide_itinerary_approval(approval_id, trip_id, user_id, decision, response=None):
    """Quyết định nguyên tử, kiểm owner/bản cũ; không nhận user_id từ body API."""
    if decision not in {"approved", "edited", "rejected"}:
        raise ValueError("Quyết định không hợp lệ.")
    if response is not None and (not isinstance(response, str) or len(response) > 4000):
        raise ValueError("Phản hồi phải là chuỗi tối đa 4000 ký tự.")
    if decision == "edited" and not (response or "").strip():
        raise ValueError("Cần ghi rõ nội dung muốn sửa.")
    with closing(get_conn()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT a.* FROM approvals a JOIN trips t USING(trip_id)
               WHERE a.approval_id=? AND a.trip_id=? AND t.user_id=? AND a.kind='itinerary_approval'""",
            (approval_id, trip_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError("Không tìm thấy yêu cầu duyệt của người dùng.")
        itinerary_id = json.loads(row["payload"])["itinerary_id"]
        current = conn.execute("SELECT itinerary_id FROM itineraries WHERE trip_id=? ORDER BY version DESC LIMIT 1",
                               (trip_id,)).fetchone()
        if current is None or current[0] != itinerary_id:
            raise ValueError("Yêu cầu duyệt thuộc lịch trình cũ.")
        if row["decision"] != "pending":
            if row["decision"] == decision and row["user_response"] == response:
                return itinerary_id
            raise ValueError("Yêu cầu duyệt đã có quyết định khác.")
        ts = now()
        conn.execute("UPDATE approvals SET decision=?, user_response=?, decided_at=? WHERE approval_id=?",
                     (decision, response, ts, approval_id))
        if decision == "approved":
            conn.execute("UPDATE itineraries SET status='approved', approved_at=? WHERE itinerary_id=?", (ts, itinerary_id))
            conn.execute("UPDATE trips SET status='approved', updated_at=? WHERE trip_id=?", (ts, trip_id))
    return itinerary_id
