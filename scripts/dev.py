"""make dev: chạy mock-weather (8081) + backend (8000) + web (5173). Ctrl+C để tắt cả 3.
Phần nào chưa có code (mocks/, web/) thì bỏ qua."""

import shutil
import subprocess
import sys
from pathlib import Path

SERVICES = [
    ("mock-weather", "mocks/mock_weather/app.py",
     [sys.executable, "-m", "uvicorn", "mocks.mock_weather.app:app", "--port", "8081"]),
    ("backend", "agent/src/api/server.py",
     [sys.executable, "-m", "uvicorn", "agent.src.api.server:app", "--reload", "--port", "8000"]),
    ("web", "web/package.json", [shutil.which("npm") or "npm", "--prefix", "web", "run", "dev", "--", "--host"]),
]  # fmt: skip

procs = []
for name, marker, cmd in SERVICES:
    if not Path(marker).exists():
        print(f"[dev] bỏ qua {name}: chưa có {marker}")
        continue
    print(f"[dev] chạy {name}")
    procs.append(subprocess.Popen(cmd))
try:
    for p in procs:
        p.wait()
except KeyboardInterrupt:
    for p in procs:
        p.terminate()
