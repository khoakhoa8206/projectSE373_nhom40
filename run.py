"""Chạy toàn bộ: mock-weather :8081 + backend thật :8000 + web :5173. Ctrl+C để tắt.
    .venv/Scripts/python run.py           giữ nguyên dữ liệu cũ (tắt/bật lại vẫn chạy tiếp đúng điểm dừng)
    .venv/Scripts/python run.py --reset   xoá dữ liệu, tạo lại 3 tài khoản demo"""

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
if "--reset" in sys.argv:
    shutil.rmtree(RUNTIME, ignore_errors=True)
RUNTIME.mkdir(exist_ok=True)
secret_file = RUNTIME / "session.secret"  # giữ cookie phiên qua lần khởi động lại, không commit
if not secret_file.exists():
    secret_file.write_text(secrets.token_hex(32))
os.environ.update(PYTHONUTF8="1", DB_PATH=str(RUNTIME / "tourguide.db"), TRACE_DIR=str(RUNTIME / "traces"),
                  SESSION_SECRET=secret_file.read_text(), FASTEMBED_CACHE_PATH=str(ROOT / ".fastembed"))  # fmt: skip
os.environ.setdefault("WEATHER_BASE_URL", "http://127.0.0.1:8081")


def wait_port(port):
    for _ in range(150):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise SystemExit(f"Cổng {port} không mở được")


procs = [subprocess.Popen([sys.executable, "-m", "uvicorn", "mocks.mock_weather.app:app", "--port", "8081", "--log-level", "warning"])]
try:
    wait_port(8081)
    if not Path(os.environ["DB_PATH"]).exists():
        print("[run] Tạo dữ liệu demo lần đầu...")
        from agent.db.init import init_db
        from scripts import load_destination

        init_db()
        sys.argv = ["load_destination.py", "hue", "--complete"]
        load_destination.main()
        subprocess.run([sys.executable, "-m", "agent.src.rag.ingest"], check=True)
        from fullstack import seed

        seed.run()
    else:  # ponytail: DB tạo trước 18/11 chưa có bảng credentials; bỏ khi cả nhóm đã chạy run.py --reset
        from agent.db import repo

        repo.query("""CREATE TABLE IF NOT EXISTS credentials (
            user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")
    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "fullstack.api:app", "--port", "8000", "--log-level", "warning"]))
    wait_port(8000)
    npm = shutil.which("npm") or "npm"
    procs.append(subprocess.Popen([npm, "--prefix", "web", "run", "dev", "--", "--host", "--port", "5173"]))
    print("[run] Mở http://localhost:5173")
    for p in procs:
        p.wait()
except KeyboardInterrupt:
    pass
finally:
    for p in procs:
        p.terminate()
