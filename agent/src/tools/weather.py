"""Tool thời tiết (P4). Chỉ gọi host trong allowlist, timeout 10 s, retry ≤ 2.
Lỗi thì trả "không có dự báo", không bao giờ giả định trời đẹp.

Kiểm miền giá trị (docs/uc-11.md mục 7), đánh dấu ngay lúc ghi weather_snapshots để validator UC-02 và verifier
UC-11 cùng thấy một cờ is_anomalous. Sai thì status = anomalous, KHÔNG sửa số liệu:
  1. miền vật lý, temp_min ≤ temp_max, mưa không âm, condition thuộc tập cho phép, ngày trả về = ngày hỏi
  2. kỷ lục khí hậu của điểm đến: nhiệt độ theo tháng, lượng mưa ngày
Open-Meteo là nguồn thứ hai (bật bằng WEATHER_SECOND_SOURCE=open-meteo, mặc định tắt): chỉ để so, kết quả có thêm
second_source + disagree. Không lấy trung bình, nguồn chính vẫn là mock_weather."""

import os
from datetime import date as Date

import httpx

from agent.db import repo

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "api.open-meteo.com"}
TIMEOUT_S = 10
RETRIES = 2
FIELDS = ("temp_min_c", "temp_max_c", "precip_mm", "condition")
TEMPS = ("temp_min_c", "temp_max_c")
# Tập condition của mock_data.json; validator UC-02 hiểu heavy_rain là mưa lớn
CONDITIONS = ("clear", "partly_cloudy", "cloudy", "light_rain", "rain", "heavy_rain")

# Lớp 1: ngoài miền này thì chắc chắn sai, ở bất kỳ đâu
PHYSICAL_TEMP_C = (-30, 60)

# Lớp 2: kỷ lục của điểm đến. Điểm đến chưa có kỷ lục thì chỉ kiểm lớp 1.
# - Nhiệt độ theo tháng (T1..T12, °C): Viện KH&CN Xây dựng, bảng "Climate data for Huế" trên
#   https://en.wikipedia.org/w/index.php?title=Hu%E1%BA%BF&oldid=1381279760 (CC BY-SA 4.0), retrieved_at 2026-10-30.
# - Mưa ngày: 1.739,6 mm ở trạm Bạch Mã (Huế), 26–27/10/2025, kỷ lục quan trắc của Việt Nam, vượt kỷ lục Huế 11/1999.
#   https://news.laodong.vn/moi-truong/ly-giai-mua-du-doi-pha-vo-ky-luc-o-hue-1740mm-trong-1-ngay-2785mm-trong-3-ngay-1599537.ldo
#   https://www.weatherzone.com.au/news/vietnam-deluge-close-to-world-record-for-highest-daily-rainfall/1890995
#   retrieved_at 2026-11-08. Đặt trần đúng bằng kỷ lục để không đánh dấu nhầm mưa lũ thật.
CLIMATE_RECORDS = {
    "hue": {
        "name": "Huế",
        "low": (8.8, 9.5, 10.7, 14.1, 17.7, 20.5, 19.8, 21.0, 19.1, 15.9, 12.9, 9.5),
        "high": (34.6, 36.3, 38.6, 42.2, 42.1, 40.7, 40.2, 40.2, 39.7, 36.1, 35.4, 32.2),
        "precip_day_mm": 1739.6,
    },
}
CLIMATE_MARGIN_C = 3  # biên an toàn: phá kỷ lục nhiệt ≤ 3 °C vẫn coi là có thể xảy ra

# Nguồn thứ hai: lệch quá mức này thì báo trong `disagree`
OPEN_METEO_URL = "https://api.open-meteo.com"
MAX_DIFF = {"temp_min_c": 8, "temp_max_c": 8, "precip_mm": 50}
# Mã thời tiết WMO của Open-Meteo → condition. Mã không có ở đây (tuyết…) thành None.
WMO_CONDITION = {
    0: "clear", 1: "partly_cloudy", 2: "partly_cloudy", 3: "cloudy", 45: "cloudy", 48: "cloudy",
    51: "light_rain", 53: "light_rain", 55: "light_rain", 56: "light_rain", 57: "light_rain",
    61: "light_rain", 63: "rain", 65: "heavy_rain", 66: "light_rain", 67: "rain",
    80: "light_rain", 81: "rain", 82: "heavy_rain", 95: "rain", 96: "heavy_rain", 99: "heavy_rain",
}  # fmt: skip
# So condition theo nhóm: "rain" với "light_rain" không tính là lệch, "clear" với "heavy_rain" thì có
RAIN_GROUP = {"clear": "khô", "partly_cloudy": "khô", "cloudy": "khô", "light_rain": "mưa", "rain": "mưa",
              "heavy_rain": "mưa lớn"}  # fmt: skip


def _anomaly(d, destination_id, day):
    """Các lý do số liệu bất thường, [] = hợp lệ. d có FIELDS + forecast_date; day = ngày đã hỏi."""
    reasons = []
    if d.get("forecast_date") != day.isoformat():
        reasons.append(f"ngày trả về {d.get('forecast_date')} khác ngày hỏi {day.isoformat()}")
    lo, hi = PHYSICAL_TEMP_C
    climate = CLIMATE_RECORDS.get(destination_id)
    for k in TEMPS:
        v = d[k]
        if v is None:
            continue
        if not lo <= v <= hi:
            reasons.append(f"{k} = {v} °C ngoài miền vật lý {lo}…{hi} °C")
        elif climate:
            c_lo = round(climate["low"][day.month - 1] - CLIMATE_MARGIN_C, 1)
            c_hi = round(climate["high"][day.month - 1] + CLIMATE_MARGIN_C, 1)
            if not c_lo <= v <= c_hi:
                reasons.append(f"{k} = {v} °C ngoài miền khí hậu {climate['name']} tháng {day.month} ({c_lo}…{c_hi} °C)")
    if None not in (d["temp_min_c"], d["temp_max_c"]) and d["temp_min_c"] > d["temp_max_c"]:
        reasons.append(f"temp_min_c {d['temp_min_c']} °C > temp_max_c {d['temp_max_c']} °C")
    if d["precip_mm"] is not None:
        if d["precip_mm"] < 0:
            reasons.append(f"lượng mưa âm ({d['precip_mm']} mm)")
        elif climate and d["precip_mm"] > climate["precip_day_mm"]:
            reasons.append(f"lượng mưa {d['precip_mm']} mm vượt kỷ lục mưa ngày {climate['name']} "
                           f"({climate['precip_day_mm']} mm)")  # fmt: skip
    if d["condition"] is not None and d["condition"] not in CONDITIONS:
        reasons.append(f"condition {d['condition']!r} không thuộc tập cho phép")
    return reasons


def _disagree(d, ref):
    """Các điểm nguồn chính lệch nguồn thứ hai (chỉ để báo, không sửa số liệu)."""
    out = [f"{k} lệch {abs(d[k] - ref[k]):.1f} so với open_meteo ({d[k]} vs {ref[k]}, ngưỡng {limit})"
           for k, limit in MAX_DIFF.items()
           if d[k] is not None and ref[k] is not None and abs(d[k] - ref[k]) > limit]  # fmt: skip
    a, b = RAIN_GROUP.get(d["condition"]), RAIN_GROUP.get(ref["condition"])
    if a and b and a != b:
        out.append(f"condition khác nhau: {d['condition']} vs open_meteo {ref['condition']}")
    return out


def _client():
    # 127.0.0.1 thay cho localhost: Windows thử IPv6 ::1 trước, mỗi lần gọi chậm thêm ~2 s
    return httpx.Client(base_url=os.environ.get("WEATHER_BASE_URL", "http://127.0.0.1:8081"), timeout=TIMEOUT_S)


def _open_meteo_client():
    return httpx.Client(base_url=OPEN_METEO_URL, timeout=TIMEOUT_S)


def _fetch(client, path, params):
    """GET qua allowlist + retry. Trả (json, None) hoặc (None, lý do lỗi)."""
    if client.base_url.host not in ALLOWED_HOSTS:
        return None, f"host {client.base_url.host} không nằm trong allowlist"
    error = None
    for _ in range(1 + RETRIES):
        try:
            r = client.get(path, params=params)
        except httpx.HTTPError as e:  # timeout, mất kết nối → thử lại
            error = f"{type(e).__name__}"
            continue
        if r.status_code >= 500:
            error = f"HTTP {r.status_code}"
            continue
        if r.status_code != 200:  # 404/400 = ngày/điểm đến không có dữ liệu, thử lại cũng vậy
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    return None, f"lỗi sau {1 + RETRIES} lần gọi: {error}"


def _city_coords(destination_id):
    """Bảng destinations chưa có toạ độ (không sửa schema khi chưa hỏi lead): lấy tâm các POI của điểm đến."""
    row = repo.query("SELECT AVG(lat) AS lat, AVG(lon) AS lon FROM pois WHERE destination_id = ?", (destination_id,))[0]
    return None if row["lat"] is None else (round(row["lat"], 4), round(row["lon"], 4))


def _open_meteo(client, destination_id, date):
    """Dự báo Open-Meteo (CC BY 4.0, open-meteo.com) cho 1 ngày. Chỉ dự báo ~16 ngày tới; ngoài tầm trả HTTP 400."""
    coords = _city_coords(destination_id)
    if coords is None:
        return None, f"chưa có toạ độ cho {destination_id}"
    body, error = _fetch(client, "/v1/forecast", {
        "latitude": coords[0], "longitude": coords[1], "start_date": date, "end_date": date,
        "timezone": "Asia/Ho_Chi_Minh",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"})  # fmt: skip
    if error:
        return None, error
    try:
        day = body["daily"]
        return {"forecast_date": day["time"][0], "temp_min_c": day["temperature_2m_min"][0],
                "temp_max_c": day["temperature_2m_max"][0], "precip_mm": day["precipitation_sum"][0],
                "condition": WMO_CONDITION.get(day["weather_code"][0])}, None  # fmt: skip
    except (KeyError, IndexError, TypeError):
        return None, "phản hồi Open-Meteo sai định dạng"


def _save(destination_id, date, provider, data, reasons, run_id):
    reason = "; ".join(reasons) or None
    return repo.query(
        """INSERT INTO weather_snapshots (destination_id, forecast_date, provider, temp_min_c, temp_max_c, precip_mm,
               condition, is_anomalous, anomaly_reason, fetched_at, run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING snapshot_id""",
        (destination_id, date, provider, *(data[k] for k in FIELDS), int(bool(reasons)), reason, repo.now(), run_id),
    )[0]["snapshot_id"]


def _second_source(destination_id, day, run_id):
    """None = tắt (mặc định, eval/CI chỉ dùng mock nên tất định). Bật: WEATHER_SECOND_SOURCE=open-meteo."""
    if os.environ.get("WEATHER_SECOND_SOURCE") != "open-meteo":
        return None
    date = day.isoformat()
    with _open_meteo_client() as client:
        ref, error = _open_meteo(client, destination_id, date)
    if error:  # ngoài tầm dự báo, lỗi mạng, host lạ
        return {"provider": "open_meteo", "status": "no_forecast", "reason": error}
    reasons = _anomaly(ref, destination_id, day)
    snapshot_id = _save(destination_id, date, "open_meteo", ref, reasons, run_id)
    if reasons:
        return {"provider": "open_meteo", "status": "anomalous", "reason": "; ".join(reasons), "snapshot_id": snapshot_id}
    return {"provider": "open_meteo", "status": "ok", **{k: ref[k] for k in FIELDS}, "snapshot_id": snapshot_id}


def _no_forecast(date, reason):
    return {"forecast_date": date, "status": "no_forecast", "message": "không có dự báo", "reason": reason}


def get_weather_forecast(destination_id: str, date: str, run_id: str) -> dict:
    """Dự báo thời tiết 1 ngày tại điểm đến (date dạng YYYY-MM-DD): temp_min_c, temp_max_c, precip_mm, condition
    (vd heavy_rain = mưa lớn, không xếp hoạt động ngoài trời > 2 giờ). status = no_forecast nghĩa là không có dự báo:
    ghi rõ "không có dự báo" cho ngày đó, không được giả định trời đẹp. status = anomalous nghĩa là số liệu phi lý:
    coi như không có dự báo, không dùng làm dữ kiện. disagree khác rỗng nghĩa là nguồn thứ hai (second_source) dự báo
    khác: vẫn dùng số của nguồn chính nhưng ghi rõ dự báo chưa chắc chắn."""
    day = Date.fromisoformat(date)  # sai định dạng → ValueError trả về cho LLM
    date = day.isoformat()
    with _client() as client:
        body, error = _fetch(client, "/forecast", {"destination": destination_id, "date": date})
    if error:
        return _no_forecast(date, error)

    data = {k: body.get(k) for k in FIELDS}
    reasons = _anomaly(data | {"forecast_date": body.get("forecast_date")}, destination_id, day)
    # Ghi nguồn thứ hai TRƯỚC: repo.weather_for_run() lấy dòng cuối mỗi ngày, dòng đó phải là nguồn chính
    second = _second_source(destination_id, day, run_id)
    snapshot_id = _save(destination_id, date, "mock_weather", data, reasons, run_id)
    extra = {}
    if second:
        extra["second_source"] = second
        if second["status"] == "ok" and not reasons:
            extra["disagree"] = _disagree(data, second)
    if reasons:  # snapshot vẫn lưu để truy vết, nhưng không đưa số phi lý cho LLM
        return {"forecast_date": date, "status": "anomalous", "message": "không có dự báo (số liệu bất thường)",
                "reason": "; ".join(reasons), "snapshot_id": snapshot_id, **extra}  # fmt: skip
    return {"forecast_date": date, "status": "ok", **data, "provider": "mock_weather", "snapshot_id": snapshot_id,
            **extra}  # fmt: skip
