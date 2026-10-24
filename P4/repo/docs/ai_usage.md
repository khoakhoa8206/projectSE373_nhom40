# Minh bạch sử dụng AI

Mỗi lần dùng công cụ AI hỗ trợ code/tài liệu, ghi 1 dòng: ngày · người · công cụ · việc · phần đã tự kiểm tra.

| Ngày | Người | Công cụ | Việc | Đã kiểm tra |
|---|---|---|---|---|
| 23/10/2026 | P1 | Claude Code (Claude Opus 5.5) | Dựng khung repo Phase 1: tầng DB (`agent/db`), model Pydantic, graph LangGraph UC-02 + vòng gọi tool qua OpenRouter, API FastAPI, eval runner, CI, README/AGENTS.md | `ruff` + 7 test pytest xanh; chạy thử eval runner với mock giả; _P1 đọc lại trước khi push_ |
| 24/10/2026 | P4 | Claude Code (Claude Opus 5.5) | Phase 1 P4: `mocks/mock_weather/` (app + dữ liệu hư cấu 30 ngày), tool `get_weather_forecast` + `tests/test_weather.py`, khung PWA `web/` (chọn người dùng, form UC-02, lịch trình theo ngày, bản đồ Leaflet/OSM, panel log, manifest + service worker) | `ruff` + 13 test pytest xanh; chạy mock thật ở 4 chế độ; thử UI trên trình duyệt với backend dùng LLM/tool giả; _P4 đọc lại trước khi push_ |
