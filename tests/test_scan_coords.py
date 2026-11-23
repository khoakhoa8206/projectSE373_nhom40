import sqlite3
from contextlib import closing

from scripts.scan_coords import scan_db, scan_files, scan_text


def test_scan_text_finds_precise_coords_but_not_masked_or_scores():
    assert scan_text('{"lat": 16.469812, "lon": 107.58}') == ['"lat": 16.469812']
    assert scan_text("đang ở 16.4698, 107.5786") == ["16.4698, 107.5786"]
    assert scan_text('{"lat": 16.47, "coordinates": [107.58, 16.47], "scores": [0.7083, 0.8125]}') == []


def test_scan_files_and_db(tmp_path):
    (tmp_path / "traces" / "samples").mkdir(parents=True)
    (tmp_path / "traces" / "samples" / "r-1.jsonl").write_text('{"args": {"lat": 16.469812}}\n', encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.log").write_text("16.4698, 107.5786", encoding="utf-8")  # dữ liệu nguồn: được phép
    assert len(scan_files(tmp_path)) == 1

    db = tmp_path / "t.db"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE pois (lat REAL, lon REAL)")
        conn.execute("INSERT INTO pois VALUES (16.469812, 107.578612)")  # toạ độ POI công khai: được phép
        conn.execute("CREATE TABLE messages (content TEXT, lat REAL)")
        conn.execute("INSERT INTO messages VALUES ('tôi ở 16.4698, 107.5786', 16.47)")
        conn.execute("CREATE TABLE sessions (lat REAL)")
        conn.execute("INSERT INTO sessions VALUES (16.4698)")
    hits = scan_db(db)
    assert len(hits) == 2 and any("messages.content" in h for h in hits) and any("sessions.lat" in h for h in hits)
