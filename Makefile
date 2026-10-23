# Windows: chạy trong Git Bash sau khi cài make (winget install ezwinports.make), hoặc gõ thẳng lệnh python bên dưới.
# Nhớ kích hoạt .venv trước.
export PYTHONUTF8 := 1
PY ?= python

.PHONY: db dev eval test openapi

db:  ## tạo lại tourguide.db (xoá DB cũ). P2 thêm dòng nạp dữ liệu: $(PY) scripts/load_destination.py hue
	$(PY) -m agent.db.init

dev:  ## mock-weather :8081 + backend :8000 + web :5173
	$(PY) scripts/dev.py

eval:
	$(PY) -m evals.run --uc UC-02

test:
	$(PY) -m ruff check .
	$(PY) -m pytest -q

openapi:
	$(PY) -c "import json; from agent.src.api.server import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > docs/openapi.json
