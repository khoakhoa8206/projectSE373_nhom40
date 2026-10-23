# Tour Guide Agent — Huế (SE373 · Đề tài 08)

Agent lập lịch trình du lịch Huế: PWA có bản đồ (`web/`) gọi backend FastAPI + LangGraph (`agent/`).
Phase 1 chạy UC-02: form hồ sơ → agent lên lịch trình (≥ 2 tool, skill `itinerary-planning`, log từng bước) → bản đồ.

## Cài đặt trên máy mới

Cần: Python 3.13, Git, Node 20+ (cho `web/`), `make` (Windows: `winget install ezwinports.make`, chạy trong Git Bash).

```bash
git clone <repo> && cd tour-guide-agent
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash; PowerShell: .venv\Scripts\Activate.ps1; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # điền LLM_API_KEY (key OpenRouter), KHÔNG commit .env
make db                              # tạo tourguide.db
make test                            # ruff + pytest, phải xanh
```

Không có `make` thì gõ thẳng lệnh tương ứng:

| Lệnh | Tương đương | Làm gì |
|---|---|---|
| `make db` | `python -m agent.db.init` | Tạo lại `tourguide.db` từ `agent/db/schema.sql` (xoá DB cũ) + 3 người dùng hư cấu |
| `make dev` | `python scripts/dev.py` | mock-weather :8081 + backend :8000 + web :5173 |
| `make test` | `ruff check . && pytest -q` | Lint + test (CI chạy đúng 2 lệnh này + gitleaks) |
| `make eval` | `python -m evals.run --uc UC-02` | Chạy toàn bộ eval case, ghi `results/<id>/summary.csv` |
| `make openapi` | xem Makefile | Sinh lại `docs/openapi.json` |

Windows mà in tiếng Việt bị lỗi encoding thì đặt `PYTHONUTF8=1` (Makefile đã đặt sẵn).

## API (Phase 1)

Chạy `make dev` rồi mở http://localhost:8000/docs. Chi tiết: `docs/openapi.json`.

| Endpoint | Mô tả |
|---|---|
| `GET /api/users` | 3 người dùng hư cấu cho màn hình chọn |
| `POST /api/session` `{user_id}` | Chọn người dùng (lưu vào cookie session) |
| `POST /api/trips` (body = TripProfile) | Tạo chuyến đi + hồ sơ v1, trả `trip_id` |
| `POST /api/trips/{trip_id}/plan` | Chạy agent UC-02, trả `run_id`, `itinerary_id`, `status` |
| `GET /api/trips/{trip_id}/itinerary` | Lịch trình mới nhất: slot + tên/toạ độ POI + vi phạm còn lại |
| `GET /api/runs/{run_id}/trace` | Các bước của agent (node, tool, skill, LLM) cho panel log |
| `GET /api/pois?category=` | POI để vẽ bản đồ |

## Cấu trúc repo

```
agent/db/            schema.sql (25 bảng), init.py, repo.py                       P1
agent/schemas/       TripProfile, Slot, Itinerary, POI, Violation                  P1
agent/src/graph/     app.py (graph UC-02), loop.py (gọi LLM qua OpenRouter + tool + skill) P1
agent/src/obs/       trace.py (mask_coords, trace JSONL)                           P1
agent/src/api/       server.py (FastAPI)                                           P1
agent/src/nodes/     plan.py                                                       P2
agent/src/tools/     destination.py (P2) · weather.py (P4)
agent/src/validation/ validator.py                                                 P2
skills/              itinerary-planning/ (P2)
data/destinations/hue/  poi.csv, restricted_zones.geojson, travel_matrix.csv      P2
mocks/mock_weather/  mock-weather FastAPI, cổng 8081                               P4
evals/               run.py (P1) · trip_requests.jsonl, uc02/cases.jsonl, uc02/scorer.py (P3)
web/                 PWA Vite + React + TS + Leaflet                               P4
docs/                team.md, uc-xx.md, ai_usage.md, openapi.json
```

Quy ước làm việc và hợp đồng giữa các thành viên: xem [AGENTS.md](AGENTS.md).
