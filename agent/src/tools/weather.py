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
TEMP_RANGE_C = (-10, 45)  # ngoài miền này = số liệu phi lý


def _anomaly(d):
    """Lý do số liệu bất thường, None = hợp lệ. Chỉ đánh dấu, không sửa số liệu."""
    lo, hi = TEMP_RANGE_C
    reasons = [f"{k} = {d[k]} °C ngoài miền {lo}…{hi} °C" for k in ("temp_min_c", "temp_max_c")
               if d[k] is not None and not lo <= d[k] <= hi]  # fmt: skip
    if d["precip_mm"] is not None and d["precip_mm"] < 0:
        reasons.append(f"lượng mưa âm ({d['precip_mm']} mm)")
    return "; ".join(reasons) or None


def _client():
    # 127.0.0.1 thay cho localhost: Windows thử IPv6 ::1 trước, mỗi lần gọi chậm thêm ~2 s
    return httpx.Client(base_url=os.environ.get("WEATHER_BASE_URL", "http://127.0.0.1:8081"), timeout=TIMEOUT_S)


def _no_forecast(date, reason):
    return {"forecast_date": date, "status": "no_forecast", "message": "không có dự báo", "reason": reason}


def get_weather_forecast(destination_id: str, date: str, run_id: str) -> dict:
    """Dự báo thời tiết 1 ngày tại điểm đến (date dạng YYYY-MM-DD): temp_min_c, temp_max_c, precip_mm, condition
    (vd heavy_rain = mưa lớn, không xếp hoạt động ngoài trời > 2 giờ). status = no_forecast nghĩa là không có dự báo:
    ghi rõ "không có dự báo" cho ngày đó, không được giả định trời đẹp. status = anomalous nghĩa là số liệu phi lý:
    coi như không có dự báo, không dùng làm dữ kiện."""
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
    anomaly = _anomaly(data)
    snapshot_id = repo.query(
        """INSERT INTO weather_snapshots (destination_id, forecast_date, provider, temp_min_c, temp_max_c, precip_mm,
               condition, is_anomalous, anomaly_reason, fetched_at, run_id)
           VALUES (?, ?, 'mock_weather', ?, ?, ?, ?, ?, ?, ?, ?) RETURNING snapshot_id""",
        (destination_id, date, *data.values(), int(anomaly is not None), anomaly, repo.now(), run_id),
    )[0]["snapshot_id"]
    if anomaly:  # snapshot vẫn lưu để truy vết, nhưng không đưa số phi lý cho LLM
        return {"forecast_date": date, "status": "anomalous", "message": "không có dự báo (số liệu bất thường)",
                "reason": anomaly, "snapshot_id": snapshot_id}  # fmt: skip
    return {"forecast_date": date, "status": "ok", **data, "provider": "mock_weather", "snapshot_id": snapshot_id}
