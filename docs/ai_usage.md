# Minh bạch sử dụng AI

Mỗi lần dùng công cụ AI hỗ trợ code/tài liệu, ghi 1 dòng: ngày · người · công cụ · việc · phần đã tự kiểm tra.

| Ngày | Người | Công cụ | Việc | Đã kiểm tra |
|---|---|---|---|---|
| 23/10/2026 | P1 | Claude Code (Claude Opus 5.5) | Dựng khung repo Phase 1: tầng DB (`agent/db`), model Pydantic, graph LangGraph UC-02 + vòng gọi tool qua OpenRouter, API FastAPI, eval runner, CI, README/AGENTS.md | `ruff` + 7 test pytest xanh; chạy thử eval runner với mock giả; _P1 đọc lại trước khi push_ |
| 24/10/2026 | P3 | Claude (Claude Opus 5.5) | Soạn `evals/trip_requests.jsonl`, `evals/uc02/` (10 case, fixture `.sql`, `scorer.py`), test `tests/test_p3_*.py` + `tests/test_uc02_scorer.py`, `kb/` (catalog 60 tài liệu + 15 tài liệu), `docs/uc-03.md`, `docs/uc-09.md` | `ruff` + pytest xanh ở từng nhánh (đủ 4 nhánh: 37 passed); nguồn Wikipedia ghi URL + ngày truy cập; _P3 đọc lại nội dung tài liệu trước khi push_ |
