"""Gọi luồng /plan qua backend :8000 (giống thao tác trên Swagger) với mock-weather bật lần lượt từng chế độ.
Cần backend demo đang chạy và cổng 8081 trống. Chạy từ gốc repo: PYTHONPATH=. python P4/demo/modes_via_backend.py"""

import json
import time

import httpx

from evals.run import start_mock

API = "http://127.0.0.1:8000/api"

for mode in ["normal", "heavy_rain", "abnormal", "timeout", "heavyrain"]:  # heavyrain: cố tình gõ sai
    mock = start_mock(mode)
    try:
        c = httpx.Client(timeout=120)
        c.post(f"{API}/session", json={"user_id": "u-ha"})
        trip = c.post(f"{API}/trips", json={"start_date": "2026-11-27", "end_date": "2026-11-27", "adults": 2}).json()
        t0 = time.time()
        plan = c.post(f"{API}/trips/{trip['trip_id']}/plan")
        trace = c.get(f"{API}/runs/{plan.json()['run_id']}/trace").json()
        weather = next(e for e in trace if e["name"] == "get_weather_forecast")
        print(f"\n=== MOCK_WEATHER_MODE={mode}  ({time.time() - t0:.0f}s)")
        print("POST /plan     ->", plan.status_code, json.dumps(plan.json(), ensure_ascii=False))
        print("trace weather  ->", json.dumps(weather["result"], ensure_ascii=False))
    finally:
        mock.terminate()
        mock.wait()
