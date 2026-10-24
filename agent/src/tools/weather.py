"""Tool thời tiết (P4). Chỉ gọi host trong allowlist, timeout 10 s, retry ≤ 2.
Lỗi thì trả "không có dự báo", không bao giờ giả định trời đẹp."""

import os
from datetime import date as Date

import httpx

from agent.db import repo

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}  # mock-weather; Open-Meteo thêm ở Phase 2
TIMEOUT_S = 10
RETRIES = 2
FIELDS = ("temp_min_c", "temp_max_c", "precip_mm", "condition")


def _client():
    # 127.0.0.1 thay cho localhost: Windows thử IPv6 ::1 trước, mỗi lần gọi chậm thêm ~2 s
    return httpx.Client(base_url=os.environ.get("WEATHER_BASE_URL", "http://127.0.0.1:8081"), timeout=TIMEOUT_S)


def _no_forecast(date, reason):
    return {"forecast_date": date, "status": "no_forecast", "message": "không có dự báo", "reason": reason}


def get_weather_forecast(destination_id: str, date: str, run_id: str) -> dict:
    """Dự báo thời tiết 1 ngày tại điểm đến (date dạng YYYY-MM-DD): temp_min_c, temp_max_c, precip_mm, condition
    (vd heavy_rain = mưa lớn, không xếp hoạt động ngoài trời > 2 giờ). status = no_forecast nghĩa là không có dự báo:
    ghi rõ "không có dự báo" cho ngày đó, không được giả định trời đẹp."""
    date = Date.fromisoformat(date).isoformat()  # sai định dạng → ValueError trả về cho LLM
    with _client() as client:
        if client.base_url.host not in ALLOWED_HOSTS:
            return _no_forecast(date, f"host {client.base_url.host} không nằm trong allowlist")
        error = None
        for _ in range(1 + RETRIES):
            try:
                r = client.get("/forecast", params={"destination": destination_id, "date": date})
            except httpx.HTTPError as e:  # timeout, mất kết nối → thử lại
                error = f"{type(e).__name__}"
                continue
            if r.status_code >= 500:
                error = f"HTTP {r.status_code}"
                continue
            if r.status_code != 200:  # 404 = ngày/điểm đến không có dữ liệu, thử lại cũng vậy
                return _no_forecast(date, f"HTTP {r.status_code}")
            break
        else:
            return _no_forecast(date, f"lỗi sau {1 + RETRIES} lần gọi: {error}")

    data = {k: r.json().get(k) for k in FIELDS}
    snapshot_id = repo.query(
        """INSERT INTO weather_snapshots (destination_id, forecast_date, provider, temp_min_c, temp_max_c, precip_mm,
               condition, fetched_at, run_id) VALUES (?, ?, 'mock_weather', ?, ?, ?, ?, ?, ?) RETURNING snapshot_id""",
        (destination_id, date, *data.values(), repo.now(), run_id),
    )[0]["snapshot_id"]
    return {"forecast_date": date, "status": "ok", **data, "provider": "mock_weather", "snapshot_id": snapshot_id}
