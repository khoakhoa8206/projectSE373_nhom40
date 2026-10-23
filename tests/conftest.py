import pytest

from agent.db import repo
from agent.db.init import init_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB tạm có schema, 3 người dùng hư cấu và 2 POI (dữ liệu test, không phải dữ liệu thật)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    init_db()
    repo.query("INSERT INTO destinations (destination_id, name_vi, name_en) VALUES ('hue', 'Huế', 'Hue')")
    repo.query(
        """INSERT INTO pois (poi_id, destination_id, name_vi, category, lat, lon, source_url, license, verified_at)
           VALUES ('hue-dai-noi', 'hue', 'Đại Nội', 'attraction', 16.4698, 107.5786, 'https://example.org', 'test', '2026-10-23'),
                  ('hue-cho-dong-ba', 'hue', 'Chợ Đông Ba', 'food', 16.4727, 107.5880, 'https://example.org', 'test', '2026-10-23')"""
    )
    return tmp_path
