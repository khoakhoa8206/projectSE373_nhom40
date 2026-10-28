# AGENTS.md — quy ước code (cho người và công cụ AI hỗ trợ code)

## Luôn làm

- Python 3.13. Tên biến/hàm tiếng Anh, comment và docstring tiếng Việt, ngắn. Ruff (line 120) + pytest.
- Chạy `make test` trước khi mở PR. CI (ruff, pytest, gitleaks) phải xanh; PR cần 1 người review.
- Nhánh `feat/<mã task>` (vd `feat/P2-3`), mỗi task là 1 GitHub Issue.
- Đọc/ghi DB qua `agent/db/repo.py`; thêm hàm vào đó thay vì mở kết nối riêng. DB lấy từ biến môi trường `DB_PATH`.
- Ghi log agent qua `repo.log_event(...)`: hàm này tự làm thô lat/lon và ghi song song `traces/<run_id>.jsonl`.
- Tool nào ghi DB thì nhận tham số `run_id` (harness tự truyền, LLM không thấy tham số này).
- Dùng công cụ AI để code thì ghi vào `docs/ai_usage.md`.

## Không bao giờ

- Commit `.env`, API key, dữ liệu người thật (lộ key: −1 điểm; gitleaks quét cả lịch sử Git).
- Điền giờ mở cửa, giá vé, thời tiết ước đoán. Không có nguồn → để NULL và gắn `unverified` / "chưa xác minh".
- Nạp dòng dữ liệu thiếu `source_url`, `license`, `verified_at`.
- Lưu toạ độ chính xác của người dùng (chỉ POI và vùng hạn chế có lat/lon).
- Tin `user_id` gửi trong body request: API lấy người dùng từ session (`POST /api/session`).
- Cho agent đọc `evals/` (bộ chấm phải giấu khỏi agent).
- Sửa `agent/db/schema.sql`, `agent/schemas/` hay chữ ký dưới đây mà không mở PR nhãn `contract` và báo lead.

## Hợp đồng giữa các thành viên (chốt 12:00 T7 24/10)

**P1 → cả nhóm**
- `agent/db/repo.py`: `get_conn()`, `query(sql, params)`, `create_run(uc, trip_id, user_id, eval_case_id=None) -> run_id`,
  `finish_run(run_id, status, tokens_in, tokens_out, cost_usd, latency_ms)`,
  `log_event(run_id, node, kind, name=None, args=None, result=None, duration_ms=None, tokens=None, error=None)`,
  `create_user`, `create_trip`, `add_message`, `save_profile(trip_id, TripProfile) -> profile_id`,
  `latest_profile(trip_id)`, `weather_for_run(run_id)`, `save_itinerary(...)`, `itinerary_for_trip(trip_id)`.
- `agent/schemas`: `TripProfile`, `Slot`, `Itinerary`, `POI`, `Violation` (tên trường = tên cột DB), `SCHEMA_VERSION`.
- `agent/src/graph/loop.py`: `agent_loop(...)`, `load_skill(...)` — node nào cần LLM + tool thì dùng lại, không tự gọi API.

**P2 → P1, P3**
- `agent/src/tools/destination.py`: `search_poi(destination_id, category=None, tags=None, max_walking_level=None,
  child_age=None, outdoor=None, limit=20)`, `get_poi(poi_id)`, `get_opening_hours(poi_id, date)`,
  `get_travel_time(from_poi_id, to_poi_id, mode)`. Hàm thường có type hint + docstring (harness tự sinh tool schema
  từ chữ ký và docstring, nên docstring chính là mô tả tool cho LLM). Trả dict/list/Pydantic; sai tham số thì raise
  lỗi rõ ràng (harness trả lỗi về cho LLM).
- `agent/src/validation/validator.py`: `validate(itinerary, profile, weather) -> list[Violation]`,
  `check_fabrication(itinerary) -> list[Violation]` — hàm thuần, không gọi LLM, không ghi DB.
  `weather` = `{forecast_date: dòng weather_snapshots}` của lượt chạy hiện tại.
- `agent/src/nodes/plan.py`: sửa `SYSTEM` và phần lọc ứng viên; slot_id, lưu DB, vòng lặp ≤ 4 do graph lo.
- `scripts/load_destination.py hue`: nạp CSV/GeoJSON vào DB ở `DB_PATH` (eval runner gọi lệnh này cho DB tạm).

**P4 → P1, P2**
- `mocks/mock_weather/app.py` (FastAPI, cổng 8081): `GET /forecast?destination=hue&date=YYYY-MM-DD`.
  Chế độ lỗi đọc từ biến môi trường `MOCK_WEATHER_MODE` (`normal` / `heavy_rain` / `timeout` / `abnormal`)
  hoặc header `X-Mock-Mode`. Eval runner bật lại mock cho từng case với biến môi trường này.
- `agent/src/tools/weather.py`: `get_weather_forecast(destination_id, date, run_id)`, URL lấy từ `WEATHER_BASE_URL`.
- `web/`: cấu hình Vite proxy `/api` → `http://localhost:8000` (cookie session cần cùng origin).

**P3 → P1**
- `evals/uc02/cases.jsonl`, mỗi dòng: `case_id`, `profile` (TripProfile, ngày cụ thể), `weather_mode`, `start_weekday`,
  `expect`, tuỳ chọn `fixture` (đường dẫn file .sql hư cấu trong `evals/fixtures/`, chạy sau khi nạp dữ liệu).
- `evals/uc02/scorer.py`: `score(case, conn, run_id) -> {"passed": bool, "reasons": [str]}`; chỉ đọc DB.
