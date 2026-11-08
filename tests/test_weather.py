"""Tool thời tiết + mock-weather ở 4 chế độ (mock chạy trong tiến trình qua TestClient, không cần mở cổng 8081)."""

from datetime import date as Date

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.db import repo
from agent.src.tools import weather
from mocks.mock_weather import app as mock

DAY = "2026-11-27"


@pytest.fixture
def run_id(db):
    return repo.create_run("UC-02", repo.create_trip("u-ha"), "u-ha")


def use_mock(monkeypatch, mode):
    monkeypatch.setattr(weather, "_client", lambda: TestClient(mock.app, base_url="http://localhost:8081",
                                                               headers={"X-Mock-Mode": mode}))  # fmt: skip


def snapshots(run_id):
    return repo.query("SELECT temp_max_c, precip_mm, condition, provider FROM weather_snapshots WHERE run_id = ?",
                      (run_id,))  # fmt: skip


@pytest.mark.parametrize("mode, expect", [
    ("normal", {"temp_max_c": 26.4, "precip_mm": 2.6, "condition": "light_rain"}),
    ("heavy_rain", {"temp_max_c": 26.4, "precip_mm": 85.0, "condition": "heavy_rain"}),
])  # fmt: skip
def test_modes_write_snapshot(run_id, monkeypatch, mode, expect):
    use_mock(monkeypatch, mode)
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "ok" and res.items() >= expect.items()
    assert snapshots(run_id) == [expect | {"provider": "mock_weather"}]
    row = repo.weather_for_run(run_id)[DAY]  # validator đọc lại được
    assert row["snapshot_id"] == res["snapshot_id"] and row["is_anomalous"] == 0


def test_abnormal_flagged_and_hidden_from_llm(run_id, monkeypatch):
    use_mock(monkeypatch, "abnormal")
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "anomalous" and "temp_max_c" not in res and "precip_mm" not in res
    row = repo.weather_for_run(run_id)[DAY]
    assert row["is_anomalous"] == 1 and row["temp_max_c"] == 48.0  # snapshot giữ số gốc để truy vết
    assert "48.0 °C" in row["anomaly_reason"] and "mưa âm" in row["anomaly_reason"]


def test_timeout_retries_then_no_forecast(run_id, monkeypatch):
    calls = []

    def slow(request):
        calls.append(request)
        raise httpx.ReadTimeout("quá 10 s", request=request)

    monkeypatch.setattr(weather, "_client", lambda: httpx.Client(base_url="http://localhost:8081",
                                                                 transport=httpx.MockTransport(slow)))  # fmt: skip
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "no_forecast" and res["message"] == "không có dự báo"
    assert len(calls) == 1 + weather.RETRIES and snapshots(run_id) == []


def test_mode_from_env(monkeypatch):
    get = lambda: TestClient(mock.app).get("/forecast", params={"destination": "hue", "date": DAY})
    monkeypatch.setenv("MOCK_WEATHER_MODE", "heavy_rain")
    assert get().json()["mode"] == "heavy_rain"
    monkeypatch.setenv("MOCK_WEATHER_MODE", "heavyrain")  # gõ nhầm → lỗi rõ, không lặng lẽ thành normal
    assert get().status_code == 500


def test_no_data_and_disallowed_host(run_id, monkeypatch):
    use_mock(monkeypatch, "normal")
    assert weather.get_weather_forecast("hue", "2027-01-01", run_id)["reason"] == "HTTP 404"
    monkeypatch.setattr(weather, "_client", lambda: httpx.Client(base_url="https://evil.example.com"))
    assert "allowlist" in weather.get_weather_forecast("hue", DAY, run_id)["reason"]
    assert snapshots(run_id) == []
    with pytest.raises(ValueError):
        weather.get_weather_forecast("hue", "27/11/2026", run_id)


# --- W8-P4-2: kiểm miền giá trị + Open-Meteo làm nguồn thứ hai ---

def day(tmin=22.0, tmax=27.0, rain=1.0, condition="light_rain", date="2026-11-27"):
    return {"forecast_date": date, "temp_min_c": tmin, "temp_max_c": tmax, "precip_mm": rain, "condition": condition}


NOV, MAY = Date(2026, 11, 27), Date(2026, 5, 27)


def test_physical_and_climate_bounds():
    assert weather._anomaly(day(), "hue", NOV) == []
    assert "miền vật lý" in weather._anomaly(day(tmin=-40), "hue", NOV)[0]
    assert "> temp_max_c" in weather._anomaly(day(tmin=30, tmax=25), "hue", NOV)[0]
    # 40 °C: phi lý ở Huế tháng 11 (kỷ lục 35,4) nhưng có thể xảy ra tháng 5 (kỷ lục 42,1)
    assert "khí hậu Huế tháng 11" in weather._anomaly(day(tmax=40), "hue", NOV)[0]
    assert weather._anomaly(day(tmax=40, date="2026-05-27"), "hue", MAY) == []
    assert weather._anomaly(day(tmax=40), "da-nang", NOV) == []  # chưa có kỷ lục → chỉ kiểm lớp 1


def test_rain_cap_condition_and_date():
    assert weather._anomaly(day(rain=900.0, condition="heavy_rain"), "hue", NOV) == []  # lũ 1999 cỡ này là thật
    assert "vượt kỷ lục mưa ngày Huế" in weather._anomaly(day(rain=2000.0), "hue", NOV)[0]
    assert "không thuộc tập cho phép" in weather._anomaly(day(condition="sunny"), "hue", NOV)[0]
    assert "khác ngày hỏi" in weather._anomaly(day(date="2026-11-28"), "hue", NOV)[0]


def test_wrong_date_from_server_is_anomalous(run_id, monkeypatch):
    body = {"forecast_date": "2026-11-28", "temp_min_c": 21.0, "temp_max_c": 26.0, "precip_mm": 1.0, "condition": "cloudy"}
    monkeypatch.setattr(weather, "_client", lambda: httpx.Client(
        base_url="http://localhost:8081", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body))))
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "anomalous" and "khác ngày hỏi" in res["reason"]
    assert repo.weather_for_run(run_id)[DAY]["temp_max_c"] == 26.0  # không sửa số liệu


def use_open_meteo(monkeypatch, handler, base_url="https://api.open-meteo.com"):
    calls = []

    def transport(request):
        calls.append(request)
        return handler(request)

    monkeypatch.setenv("WEATHER_SECOND_SOURCE", "open-meteo")
    monkeypatch.setattr(weather, "_open_meteo_client", lambda: httpx.Client(
        base_url=base_url, transport=httpx.MockTransport(transport)))  # fmt: skip
    return calls


def om_day(tmin, tmax, rain, code=3, date=DAY):
    return lambda request: httpx.Response(200, json={"daily": {
        "time": [date], "temperature_2m_min": [tmin], "temperature_2m_max": [tmax], "precipitation_sum": [rain],
        "weather_code": [code]}})  # fmt: skip


def test_open_meteo_agrees(run_id, monkeypatch):
    use_mock(monkeypatch, "normal")  # mock: 21.1 / 26.4 °C, 2.6 mm, light_rain
    calls = use_open_meteo(monkeypatch, om_day(22.0, 28.0, 5.0, code=63))
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "ok" and res["disagree"] == []
    assert res["second_source"] | {"snapshot_id": 0} == {"provider": "open_meteo", "status": "ok", "temp_min_c": 22.0,
        "temp_max_c": 28.0, "precip_mm": 5.0, "condition": "rain", "snapshot_id": 0}  # fmt: skip
    q = calls[0].url.params
    assert (q["start_date"], q["timezone"], q["latitude"]) == (DAY, "Asia/Ho_Chi_Minh", "16.4712")  # tâm POI trong DB
    assert "weather_code" in q["daily"]
    assert [s["provider"] for s in snapshots(run_id)] == ["open_meteo", "mock_weather"]
    assert repo.weather_for_run(run_id)[DAY]["provider"] == "mock_weather"  # validator vẫn đọc nguồn chính


def test_open_meteo_disagrees_is_reported_not_averaged(run_id, monkeypatch):
    use_mock(monkeypatch, "heavy_rain")  # mock 85 mm heavy_rain, Open-Meteo 1 mm trời quang → lệch
    use_open_meteo(monkeypatch, om_day(22.0, 27.0, 1.0, code=0))
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "ok" and res["precip_mm"] == 85.0  # nguồn chính giữ nguyên, không lấy trung bình
    assert len(res["disagree"]) == 2 and "precip_mm" in res["disagree"][0] and "condition" in res["disagree"][1]
    row = repo.weather_for_run(run_id)[DAY]
    assert row["provider"] == "mock_weather" and row["is_anomalous"] == 0 and row["precip_mm"] == 85.0


@pytest.mark.parametrize("handler, status, reason", [
    (lambda r: httpx.Response(400, json={"error": True, "reason": "out of allowed range"}), "no_forecast", "HTTP 400"),
    (om_day(41.0, 48.0, 0.0), "anomalous", "khí hậu Huế"),  # nguồn thứ hai phi lý thì không dùng để so
])  # fmt: skip
def test_open_meteo_unusable_keeps_mock(run_id, monkeypatch, handler, status, reason):
    use_mock(monkeypatch, "normal")
    use_open_meteo(monkeypatch, handler)
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "ok" and "disagree" not in res
    assert res["second_source"]["status"] == status and reason in res["second_source"]["reason"]


def test_open_meteo_host_outside_allowlist(run_id, monkeypatch):
    use_mock(monkeypatch, "normal")
    calls = use_open_meteo(monkeypatch, om_day(22.0, 27.0, 1.0), base_url="https://evil.example.com")
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert "allowlist" in res["second_source"]["reason"] and calls == []


def test_open_meteo_off_by_default(run_id, monkeypatch):
    monkeypatch.delenv("WEATHER_SECOND_SOURCE", raising=False)
    use_mock(monkeypatch, "normal")
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert "second_source" not in res and [s["provider"] for s in snapshots(run_id)] == ["mock_weather"]
