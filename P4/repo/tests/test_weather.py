"""Tool thời tiết + mock-weather ở 4 chế độ (mock chạy trong tiến trình qua TestClient, không cần mở cổng 8081)."""

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
    ("abnormal", {"temp_max_c": 48.0, "precip_mm": -3.0, "condition": "clear"}),
])  # fmt: skip
def test_modes_write_snapshot(run_id, monkeypatch, mode, expect):
    use_mock(monkeypatch, mode)
    res = weather.get_weather_forecast("hue", DAY, run_id)
    assert res["status"] == "ok" and res.items() >= expect.items()
    assert snapshots(run_id) == [expect | {"provider": "mock_weather"}]
    assert repo.weather_for_run(run_id)[DAY]["snapshot_id"] == res["snapshot_id"]  # validator đọc lại được


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
