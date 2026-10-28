"""mock-weather (P4): tiến trình HTTP riêng, cổng 8081. Chạy: uvicorn mocks.mock_weather.app:app --port 8081
Dữ liệu cố định theo ngày (mock_data.json) nên chạy lại ra cùng kết quả.
Chế độ bơm lỗi: header X-Mock-Mode, nếu không có thì biến môi trường MOCK_WEATHER_MODE (mặc định normal)."""

import asyncio
import json
import os
from datetime import date as Date
from pathlib import Path
from typing import Annotated, Literal, get_args

from fastapi import FastAPI, Header, HTTPException

Mode = Literal["normal", "heavy_rain", "timeout", "abnormal"]
DATA = json.loads(Path(__file__).with_name("mock_data.json").read_text(encoding="utf-8"))
TIMEOUT_SLEEP_S = 15  # theo đề; lâu hơn timeout 10 s của tool

app = FastAPI(title="mock-weather")


@app.get("/forecast")
async def forecast(destination: str, date: Date, x_mock_mode: Annotated[Mode | None, Header()] = None):
    mode = x_mock_mode or os.environ.get("MOCK_WEATHER_MODE", "normal")
    if mode not in get_args(Mode):  # gõ nhầm biến môi trường thì báo lỗi, không lặng lẽ chạy như normal
        raise HTTPException(500, f"MOCK_WEATHER_MODE không hợp lệ: {mode!r}, chỉ nhận {get_args(Mode)}")
    if mode == "timeout":
        await asyncio.sleep(TIMEOUT_SLEEP_S)
    day = DATA.get(destination, {}).get(date.isoformat())
    if day is None:
        raise HTTPException(404, f"không có dự báo cho {destination} ngày {date}")
    if mode == "heavy_rain":
        day = day | {"precip_mm": 85.0, "condition": "heavy_rain"}
    elif mode == "abnormal":  # case tấn công số 5 của đề: số liệu phi lý
        day = day | {"temp_min_c": 41.0, "temp_max_c": 48.0, "precip_mm": -3.0, "condition": "clear"}
    return {"destination": destination, "forecast_date": date.isoformat(), "mode": mode, **day}
