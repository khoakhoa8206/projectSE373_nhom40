# Minh bạch sử dụng AI

Mỗi lần dùng công cụ AI hỗ trợ code/tài liệu, ghi 1 dòng: ngày · người · công cụ · việc · phần đã tự kiểm tra.

| Ngày | Người | Công cụ | Việc | Đã kiểm tra |
|---|---|---|---|---|
| 23/10/2026 | P1 | Claude Code (Claude Opus 5.5) | Dựng khung repo Phase 1: tầng DB (`agent/db`), model Pydantic, graph LangGraph UC-02 + vòng gọi tool qua OpenRouter, API FastAPI, eval runner, CI, README/AGENTS.md | `ruff` + 7 test pytest xanh; chạy thử eval runner với mock giả; _P1 đọc lại trước khi push_ |
| 24/10/2026 | P3 | Claude (Claude Opus 5.5) | Soạn `evals/trip_requests.jsonl`, `evals/uc02/` (10 case, fixture `.sql`, `scorer.py`), test `tests/test_p3_*.py` + `tests/test_uc02_scorer.py`, `kb/` (catalog 60 tài liệu + 15 tài liệu), `docs/uc-03.md`, `docs/uc-09.md` | `ruff` + pytest xanh ở từng nhánh (đủ 4 nhánh: 37 passed); nguồn Wikipedia ghi URL + ngày truy cập; _P3 đọc lại nội dung tài liệu trước khi push_ |
| 24/10/2026 | P4 | Claude Code (Claude Opus 5.5) | Thiết kế UC-11 `docs/uc-11.md` | đối chiếu `schema.sql` (bảng `claims`, `weather_snapshots`) và hợp đồng AGENTS.md; _P4 đọc lại trước khi push_ |
| 24/10/2026 | P4 | Claude Code (Claude Opus 5.5) | P4-3 khung PWA `web/` (Vite + React + TS, manifest + service worker), bản đồ Leaflet/OSM, màn hình chọn người dùng | `npm run build` qua; _P4 đọc lại trước khi push_ |
| 24/10/2026 | P4 | Claude Code (Claude Opus 5.5) | P4-4 màn hình UC-02 trên PWA: form hồ sơ, lịch trình theo ngày, marker + tuyến trên bản đồ, panel log, loading + thông báo lỗi | `npm run build` qua; thử UI trên trình duyệt với backend dùng LLM/tool giả; _P4 đọc lại trước khi push_ |
| 24/10/2026 | P4 | Claude Code (Claude Opus 5.5) | P4-1 mock-weather: `mocks/mock_weather/` (FastAPI cổng 8081, 4 chế độ lỗi, dữ liệu hư cấu 01–30/11/2026) | chạy mock thật ở 4 chế độ; `ruff` xanh; _P4 đọc lại trước khi push_ |
| 24/10/2026 | P4 | Claude Code (Claude Opus 5.5) | P4-2 tool `get_weather_forecast` (allowlist, timeout 10 s, retry ≤ 2, ghi `weather_snapshots`) + `tests/test_weather.py` | `ruff` + 13 test pytest xanh; _P4 đọc lại trước khi push_ |
| 25/10/2026 | P1 | Claude Code (Claude Opus 5.5) | Sửa P4-2: tool thời tiết đánh dấu `is_anomalous`/`anomaly_reason` (ngoài −10…45 °C, mưa âm) và không đưa số phi lý cho LLM, mock timeout 15 s; sửa P4-3: bản đồ hiện mọi POI từ `GET /api/pois` | `ruff` + pytest xanh (thêm test chế độ abnormal); `npm run build` qua; gọi thử `/api/pois`; _P1 đọc lại trước khi push_ |
| 25/10/2026 | P1 | Claude Code (Claude Opus 5.5) | Sửa `run_uc02`: tạo run trước khi dựng client/tool, lỗi khởi tạo vẫn ghi trace `setup` + trả `run_id` | test mới `test_setup_error_still_returns_run_id` (rớt trước khi sửa); `ruff` + 44 test xanh |
