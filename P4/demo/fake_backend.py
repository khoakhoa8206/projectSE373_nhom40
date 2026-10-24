"""Backend thật + LLM/tool giả (lấy từ tests/test_uc02.py) để thử giao diện khi chưa có destination.py của P2.
Chạy từ gốc repo: PYTHONPATH=. python P4/demo/fake_backend.py  → backend :8000, DB tạm trong thư mục TEMP."""

import os
import time

import uvicorn

from agent.db import repo
from agent.db.init import init_db
from agent.src.api import server
from agent.src.graph import app
from tests import test_uc02 as t

os.environ["DB_PATH"] = os.path.join(os.environ.get("TEMP", "."), "ui_demo.db")
os.environ["TRACE_DIR"] = os.path.join(os.environ.get("TEMP", "."), "ui_traces")

# LLM giả gọi thêm tool thời tiết thật để thấy mock-weather trong panel log
t.GET_DATA = {"content": None, "tool_calls": t.GET_DATA["tool_calls"] + [
    t.call("c4", "get_weather_forecast", {"destination_id": "hue", "date": "2026-11-27"})]}  # fmt: skip


class SlowFake(t.FakeLLM):
    """Chậm 2 s mỗi lượt để thấy màn hình loading."""

    def create(self, **kw):
        time.sleep(2)
        return super().create(**kw)


init_db()
repo.query("INSERT INTO destinations (destination_id, name_vi, name_en) VALUES ('hue', 'Huế', 'Hue')")
repo.query(
    """INSERT INTO pois (poi_id, destination_id, name_vi, category, lat, lon, source_url, license, verified_at)
       VALUES ('hue-dai-noi', 'hue', 'Đại Nội', 'attraction', 16.4698, 107.5786, 'https://example.org', 'test', '2026-10-23'),
              ('hue-cho-dong-ba', 'hue', 'Chợ Đông Ba', 'food', 16.4727, 107.5880, 'https://example.org', 'test', '2026-10-23')"""
)


def tools():
    from agent.src.tools.weather import get_weather_forecast  # có sau khi đưa file trong P4/repo về đúng chỗ

    return t.TOOLS + [get_weather_forecast]


app.make_client = SlowFake
app.default_tools = tools
uvicorn.run(server.app, host="127.0.0.1", port=8000)
