# P4 — các file đã làm (24/10/2026)

## `repo/` — chép đè vào gốc repo (giữ nguyên đường dẫn)

| File | Task |
|---|---|
| `mocks/mock_weather/app.py`, `mock_data.json` | P4-1 mock-weather (cổng 8081, 4 chế độ, dữ liệu hư cấu 01–30/11/2026) |
| `agent/src/tools/weather.py`, `tests/test_weather.py` | P4-2 tool `get_weather_forecast` + test 4 chế độ |
| `web/` (trừ `node_modules/`, `dist/`) | P4-3, P4-4 PWA: chọn người dùng, form UC-02, lịch trình theo ngày, bản đồ, panel log |
| `docs/uc-11.md` | Thiết kế UC-11 |

**File chung có sửa — ghi rõ trong PR để P1 duyệt:**

| File | Sửa gì |
|---|---|
| `pyproject.toml` | Thêm `[tool.ruff.lint.isort] known-first-party` (không có thì ruff báo lỗi import ở `agent/src/graph/app.py` khi chưa có `destination.py`) |
| `.env.example` | `WEATHER_BASE_URL` đổi `localhost` → `127.0.0.1` (Windows chậm thêm ~2 s mỗi lần gọi vì thử IPv6 trước) |
| `docs/ai_usage.md` | Thêm dòng khai báo dùng AI của P4 |

Sau khi chép: `pip install -r requirements.txt`, `cd web && npm install`, rồi `make test` phải xanh.

## `demo/` — KHÔNG đưa vào repo

Chạy backend thật với LLM giả + 2 POI giả (lấy từ `tests/`) để thử giao diện khi chưa có `destination.py` của P2.
Chạy từ gốc repo (sau khi đã đưa file trong `repo/` về đúng chỗ):

- `PYTHONPATH=. python P4/demo/fake_backend.py` → backend :8000 (cần mock :8081 và `npm --prefix web run dev` chạy song song)
- `PYTHONPATH=. python P4/demo/modes_via_backend.py` → gọi luồng `/plan` qua backend với từng chế độ mock (cần backend demo đang chạy, cổng 8081 trống)

## Còn lại

- P4-5: quay video (nên quay khi đã chạy được agent thật: cần `destination.py` + dữ liệu POI của P2, `.env` có key LLM).
- Báo P1: trong `run_uc02`, `default_tools()` nằm ngoài `try` → tool lỗi thì `/plan` trả 500 không có `run_id`.
- Các việc cần chốt cho UC-11: mục 16 trong `docs/uc-11.md`.
