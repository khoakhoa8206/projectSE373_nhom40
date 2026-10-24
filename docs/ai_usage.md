# Minh bạch sử dụng AI

Mỗi lần dùng công cụ AI hỗ trợ code/tài liệu, ghi 1 dòng: ngày · người · công cụ · việc · phần đã tự kiểm tra.

| Ngày | Người | Công cụ | Việc | Đã kiểm tra |
|---|---|---|---|---|
| 23/10/2026 | P1 | Claude Code (Claude Opus 5.5) | Dựng khung repo Phase 1: tầng DB (`agent/db`), model Pydantic, graph LangGraph UC-02 + vòng gọi tool qua OpenRouter, API FastAPI, eval runner, CI, README/AGENTS.md | `ruff` + 7 test pytest xanh; chạy thử eval runner với mock giả; _P1 đọc lại trước khi push_ |
| 24/10/2026 | P4 | Claude Code (Claude Opus 5.5) | P4-1 mock-weather: `mocks/mock_weather/` (FastAPI cổng 8081, 4 chế độ lỗi, dữ liệu hư cấu 01–30/11/2026) | chạy mock thật ở 4 chế độ; `ruff` xanh; _P4 đọc lại trước khi push_ |
