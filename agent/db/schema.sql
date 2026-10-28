-- =====================================================================
-- Tour Guide Agent (Đề tài 08 · SE373) — schema database mẫu v0.1
-- Engine: SQLite 3.35+  (bật khoá ngoại: PRAGMA foreign_keys = ON;)
-- Quy ước:
--   * Thời gian: TEXT ISO-8601 (vd '2026-11-20T08:30:00+07:00'), ngày: 'YYYY-MM-DD'
--   * Trường JSON: TEXT, có CHECK json_valid(...). Pydantic là nguồn sự thật cho cấu trúc JSON.
--   * Tiền: INTEGER, đơn vị VND. Không có giá -> NULL (không điền ước đoán).
--   * KHÔNG có bảng nào lưu toạ độ chính xác của người dùng (quy định 4 của đề).
--   * Bảng checkpoint của LangGraph do SqliteSaver tự tạo, không định nghĩa ở đây.
--   * Cột "Phase" trong chú thích = phase cần tạo bảng.
-- =====================================================================
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- A. DỮ LIỆU ĐIỂM ĐẾN  (owner: P2)  · Phase 1
--    Nạp từ data/destinations/<slug>/*.csv|geojson bằng script, agent chỉ ĐỌC.
-- ---------------------------------------------------------------------
CREATE TABLE destinations (
    destination_id  TEXT PRIMARY KEY,                -- slug: 'hue'
    name_vi         TEXT NOT NULL,
    name_en         TEXT NOT NULL,
    timezone        TEXT NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    is_supported    INTEGER NOT NULL DEFAULT 1 CHECK (is_supported IN (0,1))
);

CREATE TABLE pois (
    poi_id            TEXT PRIMARY KEY,              -- 'hue-dai-noi'
    destination_id    TEXT NOT NULL REFERENCES destinations(destination_id),
    name_vi           TEXT NOT NULL,
    name_en           TEXT,
    category          TEXT NOT NULL CHECK (category IN ('attraction','food','lodging')),
    lat               REAL NOT NULL,
    lon               REAL NOT NULL,
    opening_hours     TEXT,                          -- cú pháp OSM, vd 'Mo-Su 07:00-17:30'; NULL = chưa xác minh
    ticket_price_vnd  INTEGER CHECK (ticket_price_vnd IS NULL OR ticket_price_vnd >= 0),
    avg_visit_minutes INTEGER CHECK (avg_visit_minutes IS NULL OR avg_visit_minutes > 0),
    is_outdoor        INTEGER CHECK (is_outdoor IN (0,1)),
    min_age           INTEGER,                       -- NULL = không giới hạn / chưa rõ
    walking_level     TEXT CHECK (walking_level IN ('low','medium','high')),
    tags              TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags)),   -- ["history","unesco"]
    source_url        TEXT NOT NULL,                 -- bắt buộc: thiếu nguồn thì không được nạp
    license           TEXT NOT NULL,                 -- 'ODbL', 'CC BY-SA 4.0', 'self-written'
    verified_at       TEXT NOT NULL
);
CREATE INDEX idx_pois_dest_cat ON pois(destination_id, category);

CREATE TABLE restricted_zones (
    zone_id         TEXT PRIMARY KEY,
    destination_id  TEXT NOT NULL REFERENCES destinations(destination_id),
    name            TEXT NOT NULL,
    zone_type       TEXT NOT NULL CHECK (zone_type IN ('military','beach_warning','landslide','restoration','other')),
    geometry        TEXT NOT NULL CHECK (json_valid(geometry)),  -- GeoJSON Polygon hoặc {"type":"Circle","center":[lon,lat],"radius_m":...}
    active_from     TEXT,                            -- NULL = luôn hiệu lực; có giá trị = vùng nguy hiểm theo mùa
    active_to       TEXT,
    reason          TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    license         TEXT NOT NULL,
    verified_at     TEXT NOT NULL
);

CREATE TABLE travel_matrix (
    from_poi_id   TEXT NOT NULL REFERENCES pois(poi_id),
    to_poi_id     TEXT NOT NULL REFERENCES pois(poi_id),
    mode          TEXT NOT NULL CHECK (mode IN ('walk','drive','bike')),
    minutes       INTEGER NOT NULL CHECK (minutes >= 0),
    distance_m    INTEGER NOT NULL CHECK (distance_m >= 0),
    provider      TEXT NOT NULL CHECK (provider IN ('osrm','ors')),
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (from_poi_id, to_poi_id, mode)
);

-- Cache kết quả tool thời tiết (P4). Validator UC-02 và verifier UC-11 đọc lại bảng này.
CREATE TABLE weather_snapshots (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    destination_id  TEXT NOT NULL REFERENCES destinations(destination_id),
    forecast_date   TEXT NOT NULL,
    provider        TEXT NOT NULL CHECK (provider IN ('mock_weather','open_meteo')),
    temp_min_c      REAL,
    temp_max_c      REAL,
    precip_mm       REAL,
    condition       TEXT,                            -- 'heavy_rain', 'clear'...
    is_anomalous    INTEGER NOT NULL DEFAULT 0 CHECK (is_anomalous IN (0,1)),
    anomaly_reason  TEXT,                            -- '48°C ngoài miền hợp lý', 'lượng mưa âm'
    fetched_at      TEXT NOT NULL,
    run_id          TEXT REFERENCES runs(run_id)
);
CREATE INDEX idx_weather_dest_date ON weather_snapshots(destination_id, forecast_date);

-- ---------------------------------------------------------------------
-- B. NGƯỜI DÙNG, CHUYẾN ĐI, HỒ SƠ  (owner: P1 bảng users/trips, P2 trip_profiles)  · Phase 1
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,                -- uuid; eval chỉ dùng người dùng hư cấu
    display_name    TEXT NOT NULL,
    preferred_lang  TEXT NOT NULL DEFAULT 'vi' CHECK (preferred_lang IN ('vi','en')),
    created_at      TEXT NOT NULL
);

CREATE TABLE trips (
    trip_id         TEXT PRIMARY KEY,                -- cũng là thread_id của LangGraph checkpointer
    user_id         TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    destination_id  TEXT REFERENCES destinations(destination_id),   -- NULL khi route = unsupported
    status          TEXT NOT NULL DEFAULT 'profiling'
                    CHECK (status IN ('profiling','planning','awaiting_approval','approved','in_progress','completed','cancelled')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    ended_at        TEXT                             -- mốc tính 24h để xoá/làm thô dữ liệu vị trí
);
CREATE INDEX idx_trips_user ON trips(user_id);

-- Một trip có nhiều phiên bản hồ sơ (người dùng bổ sung thông tin -> version tăng).
CREATE TABLE trip_profiles (
    profile_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id           TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    version           INTEGER NOT NULL,
    start_date        TEXT,
    end_date          TEXT,
    adults            INTEGER CHECK (adults IS NULL OR adults >= 1),
    children          TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(children)),       -- [{"age":6}]
    mobility_notes    TEXT,
    budget_total_vnd  INTEGER CHECK (budget_total_vnd IS NULL OR budget_total_vnd > 0),
    budget_includes   TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(budget_includes)), -- ["lodging","food","tickets","transport"]
    interests         TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(interests)),
    pace              TEXT CHECK (pace IN ('relaxed','moderate','packed')),
    language          TEXT NOT NULL DEFAULT 'vi' CHECK (language IN ('vi','en')),
    hard_constraints  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(hard_constraints)),
    missing_info      TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(missing_info)),
    route             TEXT NOT NULL CHECK (route IN ('plan','ask_user','unsupported')),
    repair_attempts   INTEGER NOT NULL DEFAULT 0 CHECK (repair_attempts BETWEEN 0 AND 2),
    raw_json          TEXT NOT NULL CHECK (json_valid(raw_json)),  -- nguyên TripProfile đã qua Pydantic
    run_id            TEXT REFERENCES runs(run_id),
    created_at        TEXT NOT NULL,
    UNIQUE (trip_id, version),
    CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date)
);

-- ---------------------------------------------------------------------
-- C. LỊCH TRÌNH & VALIDATOR  (owner: P2)  · Phase 1
-- ---------------------------------------------------------------------
CREATE TABLE itineraries (
    itinerary_id      TEXT PRIMARY KEY,
    trip_id           TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    profile_id        INTEGER NOT NULL REFERENCES trip_profiles(profile_id),
    version           INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft','validated','failed_validation','reviewed','approved','superseded')),
    planner_rounds    INTEGER NOT NULL DEFAULT 0 CHECK (planner_rounds BETWEEN 0 AND 4),
    review_rounds     INTEGER NOT NULL DEFAULT 0 CHECK (review_rounds BETWEEN 0 AND 2),   -- UC-06
    total_cost_vnd    INTEGER,                       -- do tool cộng, không do LLM tính
    has_unpriced_item INTEGER NOT NULL DEFAULT 0 CHECK (has_unpriced_item IN (0,1)),
    run_id            TEXT REFERENCES runs(run_id),
    created_at        TEXT NOT NULL,
    approved_at       TEXT,
    UNIQUE (trip_id, version)
);

CREATE TABLE itinerary_slots (
    slot_id                   TEXT PRIMARY KEY,      -- '<itinerary_id>:d1-s2', dùng làm slot_ref cho reviewer
    itinerary_id              TEXT NOT NULL REFERENCES itineraries(itinerary_id) ON DELETE CASCADE,
    day_index                 INTEGER NOT NULL CHECK (day_index BETWEEN 1 AND 5),
    slot_date                 TEXT NOT NULL,
    start_time                TEXT NOT NULL,          -- 'HH:MM'
    end_time                  TEXT NOT NULL,
    poi_id                    TEXT REFERENCES pois(poi_id),   -- NULL = nghỉ / tự do
    activity                  TEXT NOT NULL,
    travel_minutes_from_prev  INTEGER CHECK (travel_minutes_from_prev IS NULL OR travel_minutes_from_prev >= 0),
    cost_vnd                  INTEGER,                -- NULL = "chưa có giá"
    cost_source               TEXT NOT NULL CHECK (cost_source IN ('tool','unverified','free')),
    hours_status              TEXT NOT NULL CHECK (hours_status IN ('verified','unverified','not_applicable')),
    note                      TEXT,
    progress                  TEXT NOT NULL DEFAULT 'planned' CHECK (progress IN ('planned','done','skipped')),  -- UC-09
    CHECK (end_time > start_time)
);
CREATE INDEX idx_slots_itin_day ON itinerary_slots(itinerary_id, day_index, start_time);

CREATE TABLE validation_violations (
    violation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    itinerary_id   TEXT NOT NULL REFERENCES itineraries(itinerary_id) ON DELETE CASCADE,
    round          INTEGER NOT NULL CHECK (round BETWEEN 1 AND 4),
    slot_id        TEXT REFERENCES itinerary_slots(slot_id),   -- NULL = vi phạm cấp ngày/chuyến (vd ngân sách)
    rule           TEXT NOT NULL CHECK (rule IN ('overlap','opening_hours','overload','budget','weather','restricted_area','fabricated_value')),
    severity       TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    message        TEXT NOT NULL,
    resolved       INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0,1))
);

-- ---------------------------------------------------------------------
-- D. MULTI-AGENT REVIEW  (owner: P1 · UC-06)  · Phase 3
--    Reviewer chỉ có quyền ĐỌC các bảng khác; chỉ orchestrator ghi 2 bảng này.
-- ---------------------------------------------------------------------
CREATE TABLE review_reports (
    report_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    itinerary_id  TEXT NOT NULL REFERENCES itineraries(itinerary_id) ON DELETE CASCADE,
    round         INTEGER NOT NULL CHECK (round BETWEEN 1 AND 2),
    reviewer      TEXT NOT NULL CHECK (reviewer IN ('local_expert','budget','safety')),
    verdict       TEXT NOT NULL CHECK (verdict IN ('approve','request_changes')),
    run_id        TEXT REFERENCES runs(run_id),
    created_at    TEXT NOT NULL,
    UNIQUE (itinerary_id, round, reviewer)
);

CREATE TABLE review_findings (
    finding_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    INTEGER NOT NULL REFERENCES review_reports(report_id) ON DELETE CASCADE,
    slot_ref     TEXT REFERENCES itinerary_slots(slot_id),   -- phải trỏ slot có thật
    severity     TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    rule         TEXT NOT NULL,
    message      TEXT NOT NULL,
    suggestion   TEXT
);

-- ---------------------------------------------------------------------
-- E. BỘ NHỚ DÀI HẠN & ĐỒNG Ý  (owner: P1 · UC-07)  · Phase 2
-- ---------------------------------------------------------------------
CREATE TABLE consents (
    consent_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    scope        TEXT NOT NULL CHECK (scope IN ('location_session','sensitive_memory')),
    granted      INTEGER NOT NULL CHECK (granted IN (0,1)),
    decided_at   TEXT NOT NULL,
    revoked_at   TEXT
);

CREATE TABLE memory_items (
    memory_id        TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,   -- mọi truy vấn PHẢI lọc user_id
    kind             TEXT NOT NULL CHECK (kind IN ('food_like','food_dislike','allergy','dietary','pace','interest','visited_city','other')),
    value            TEXT NOT NULL,                  -- 'không ăn cay'; visited_city chỉ lưu tên thành phố
    sensitivity      TEXT NOT NULL CHECK (sensitivity IN ('normal','sensitive')),
    consent_id       INTEGER REFERENCES consents(consent_id),
    source_message_id TEXT REFERENCES messages(message_id),   -- câu nói nào của người dùng
    source_trip_id   TEXT REFERENCES trips(trip_id) ON DELETE SET NULL,
    confirmed_by_user INTEGER NOT NULL DEFAULT 0 CHECK (confirmed_by_user IN (0,1)),
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    deleted_at       TEXT,                           -- xoá mềm; job dọn hết hạn xoá cứng
    CHECK (sensitivity = 'normal' OR consent_id IS NOT NULL)          -- sensitive bắt buộc có đồng ý
);
CREATE INDEX idx_memory_user ON memory_items(user_id, deleted_at);

-- ---------------------------------------------------------------------
-- F. HỘI THOẠI & BƯỚC NGƯỜI DUYỆT  (owner: P1)  · Phase 1 (messages) / Phase 2 (approvals)
-- ---------------------------------------------------------------------
CREATE TABLE messages (
    message_id   TEXT PRIMARY KEY,
    trip_id      TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content      TEXT NOT NULL,                      -- không chứa toạ độ chính xác
    lang         TEXT CHECK (lang IN ('vi','en')),
    run_id       TEXT REFERENCES runs(run_id),
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_messages_trip ON messages(trip_id, created_at);

CREATE TABLE approvals (
    approval_id   TEXT PRIMARY KEY,
    trip_id       TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    run_id        TEXT REFERENCES runs(run_id),
    kind          TEXT NOT NULL CHECK (kind IN ('ask_user','itinerary_approval','memory_save')),
    payload       TEXT NOT NULL CHECK (json_valid(payload)),   -- câu hỏi / lịch trình / mục bộ nhớ đề xuất
    decision      TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','approved','rejected','edited')),
    user_response TEXT,
    created_at    TEXT NOT NULL,
    decided_at    TEXT
);

-- ---------------------------------------------------------------------
-- G. KHO TRI THỨC (metadata)  (owner: P3 · UC-03)  · Phase 2
--    Nội dung + embedding nằm ở kb/ và vector store; bảng này để validator kiểm trích dẫn.
-- ---------------------------------------------------------------------
CREATE TABLE kb_documents (
    doc_id        TEXT PRIMARY KEY,                  -- 'hue-dai-noi-vi-01'
    poi_id        TEXT REFERENCES pois(poi_id),
    lang          TEXT NOT NULL CHECK (lang IN ('vi','en')),
    title         TEXT NOT NULL,
    doc_type      TEXT NOT NULL CHECK (doc_type IN ('history','culture','situation','emergency','review')),
    is_fictional  INTEGER NOT NULL DEFAULT 0 CHECK (is_fictional IN (0,1)),   -- review hư cấu = 1
    source_url    TEXT NOT NULL,
    license       TEXT NOT NULL,
    retrieved_at  TEXT NOT NULL
);

CREATE TABLE kb_chunks (
    chunk_id      TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL REFERENCES kb_documents(doc_id) ON DELETE CASCADE,
    section       TEXT NOT NULL,                     -- dùng trong trích dẫn [doc_id §section]
    chunk_index   INTEGER NOT NULL,
    text          TEXT NOT NULL,
    vector_id     TEXT,                              -- id trong Chroma/FAISS
    UNIQUE (doc_id, chunk_index)
);

CREATE TABLE citations (
    citation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    chunk_id      TEXT NOT NULL REFERENCES kb_chunks(chunk_id),
    quote         TEXT,                              -- đoạn trích; validator kiểm có nằm trong chunk
    is_valid      INTEGER CHECK (is_valid IN (0,1))
);

-- ---------------------------------------------------------------------
-- H. NHẬT KÝ CHUYẾN ĐI  (owner: P3 · UC-09)  · Phase 2
-- ---------------------------------------------------------------------
CREATE TABLE trip_events (
    event_id      TEXT PRIMARY KEY,
    trip_id       TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    occurred_at   TEXT NOT NULL,
    day_index     INTEGER NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('slot_done','slot_skipped','note','photo_meta','expense','adjustment')),
    slot_id       TEXT REFERENCES itinerary_slots(slot_id),
    poi_id        TEXT REFERENCES pois(poi_id),      -- vị trí chỉ ở mức POI, không lưu lat/lon
    amount_vnd    INTEGER CHECK (amount_vnd IS NULL OR amount_vnd >= 0),
    payload       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),   -- ghi chú, metadata ảnh
    created_by    TEXT NOT NULL CHECK (created_by IN ('user','system'))
);
CREATE INDEX idx_events_trip_day ON trip_events(trip_id, day_index, occurred_at);

CREATE TABLE journals (
    journal_id       TEXT PRIMARY KEY,
    trip_id          TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
    scope            TEXT NOT NULL CHECK (scope IN ('day','trip')),
    day_index        INTEGER,                        -- NULL khi scope = 'trip'
    lang             TEXT NOT NULL CHECK (lang IN ('vi','en')),
    content          TEXT NOT NULL CHECK (json_valid(content)),   -- DailyJournal | TripSummary
    event_ids        TEXT NOT NULL CHECK (json_valid(event_ids)), -- mọi sự kiện trong nhật ký phải nằm ở đây
    total_spent_vnd  INTEGER NOT NULL,               -- tool SUM(amount_vnd), lệch 0 đồng
    tokens_before    INTEGER,
    tokens_after     INTEGER,
    run_id           TEXT REFERENCES runs(run_id),
    created_at       TEXT NOT NULL,
    CHECK ((scope = 'day') = (day_index IS NOT NULL))
);

-- ---------------------------------------------------------------------
-- I. KIỂM CHỨNG THÔNG TIN  (owner: P4 · UC-11)  · Phase 3 (bản thử Phase 2)
-- ---------------------------------------------------------------------
CREATE TABLE claims (
    claim_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    target_type     TEXT NOT NULL CHECK (target_type IN ('message','itinerary_slot')),
    target_id       TEXT NOT NULL,
    claim_type      TEXT NOT NULL CHECK (claim_type IN ('opening_hours','price','festival_date','weather','distance')),
    claim_text      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('verified','unverified','contradicted')),
    evidence_kind   TEXT CHECK (evidence_kind IN ('tool','kb')),
    evidence_ref    TEXT,                            -- poi_id / chunk_id / snapshot_id
    source_url      TEXT,
    verified_at     TEXT,
    corrected_text  TEXT,                            -- bắt buộc khi contradicted
    CHECK (status <> 'contradicted' OR corrected_text IS NOT NULL),
    CHECK (status <> 'verified' OR source_url IS NOT NULL)
);

-- ---------------------------------------------------------------------
-- J. QUAN SÁT: RUN & TRACE  (owner: P1)  · Phase 1
--    Có thể ghi song song ra traces/<run_id>.jsonl. Toạ độ trong args/result phải qua mask_coords().
-- ---------------------------------------------------------------------
CREATE TABLE runs (
    run_id        TEXT PRIMARY KEY,
    trip_id       TEXT REFERENCES trips(trip_id) ON DELETE SET NULL,
    user_id       TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    uc            TEXT NOT NULL CHECK (uc IN ('UC-01','UC-02','UC-03','UC-06','UC-07','UC-09','UC-11','EVAL')),
    status        TEXT NOT NULL CHECK (status IN ('running','interrupted','succeeded','failed')),
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    latency_ms    INTEGER,
    eval_case_id  TEXT                               -- có giá trị khi run do eval runner tạo
);
CREATE INDEX idx_runs_trip ON runs(trip_id);

CREATE TABLE trace_events (
    run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    ts            TEXT NOT NULL,
    node          TEXT NOT NULL,                     -- 'intake', 'plan', 'validator', 'reviewer.safety'...
    kind          TEXT NOT NULL CHECK (kind IN ('node_start','node_end','llm_call','tool_call','skill_use','guardrail','approval','error')),
    name          TEXT,                              -- tên tool/skill/guardrail
    args          TEXT CHECK (args IS NULL OR json_valid(args)),
    result        TEXT CHECK (result IS NULL OR json_valid(result)),
    duration_ms   INTEGER,
    tokens        INTEGER,
    error         TEXT,
    PRIMARY KEY (run_id, seq)
);
