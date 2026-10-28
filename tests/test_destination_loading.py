"""Kiểm thử CSV và loader bằng dữ liệu hư cấu, DB tạm."""

import csv
from datetime import date

import pytest

from agent.db import repo
from agent.db.init import init_db
from agent.schemas import POI
from scripts import load_destination
from scripts.check_destination import check_pois


@pytest.fixture
def sample_poi():
    """POI hư cấu chỉ phục vụ kiểm thử."""
    return POI(
        poi_id="test-poi",
        destination_id="hue",
        name_vi="Điểm kiểm thử hư cấu",
        category="attraction",
        lat=16.45,
        lon=107.58,
        source_url="https://example.org/test-poi",
        license="test-only",
        verified_at=date.today().isoformat(),
    )


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Tạo DB riêng, không tác động DB đang dùng trong terminal."""
    path = tmp_path / "destination-test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    init_db()
    return path


def write_csv(path, rows):
    """Ghi CSV kiểm thử với đúng các cột schema."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(POI.model_fields))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_csv_preserves_unknown_values(tmp_path, sample_poi):
    path = write_csv(tmp_path / "poi.csv", [sample_poi.model_dump()])
    pois = check_pois(path)

    assert len(pois) == 1
    assert pois[0].ticket_price_vnd is None
    assert pois[0].opening_hours is None
    assert pois[0].is_outdoor is None
    assert pois[0].tags == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", ""),
        ("license", ""),
        ("verified_at", ""),
        ("verified_at", "not-a-date"),
        ("lat", 91),
        ("category", "unknown"),
        ("ticket_price_vnd", -1),
        ("tags", "not-json"),
    ],
)
def test_csv_rejects_invalid_values(tmp_path, sample_poi, field, value):
    row = sample_poi.model_dump()
    row[field] = value
    path = write_csv(tmp_path / "poi.csv", [row])

    with pytest.raises(ValueError):
        check_pois(path)


def test_csv_rejects_duplicate_ids(tmp_path, sample_poi):
    row = sample_poi.model_dump()
    path = write_csv(tmp_path / "poi.csv", [row, row])

    with pytest.raises(ValueError, match="Trùng poi_id"):
        check_pois(path)


def test_csv_rejects_empty_dataset(tmp_path):
    path = write_csv(tmp_path / "poi.csv", [])

    with pytest.raises(ValueError, match="chưa có POI"):
        check_pois(path)


def test_save_preserves_null_and_updates_without_duplicates(fresh_db, sample_poi):
    assert repo.save_hue_pois([sample_poi]) == 1

    row = repo.query("SELECT * FROM pois WHERE poi_id = ?", (sample_poi.poi_id,))[0]
    assert row["ticket_price_vnd"] is None
    assert row["opening_hours"] is None
    assert row["tags"] == "[]"

    updated = sample_poi.model_copy(update={"name_vi": "Tên kiểm thử đã cập nhật"})
    repo.save_hue_pois([updated])

    assert repo.query("SELECT COUNT(*) AS total FROM pois")[0]["total"] == 1
    row = repo.query("SELECT name_vi FROM pois WHERE poi_id = ?", (sample_poi.poi_id,))[0]
    assert row["name_vi"] == updated.name_vi


def test_save_rolls_back_on_conflicting_destination(fresh_db, sample_poi):
    repo.query(
        "INSERT INTO destinations (destination_id, name_vi, name_en) VALUES (?, ?, ?)",
        ("other", "Điểm đến kiểm thử", "Test destination"),
    )
    repo.query(
        """INSERT INTO pois
           (poi_id, destination_id, name_vi, category, lat, lon, source_url, license, verified_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("conflict-poi", "other", "POI hư cấu", "attraction", 16.45, 107.58,
         "https://example.org", "test-only", date.today().isoformat()),
    )
    conflicting = sample_poi.model_copy(update={"poi_id": "conflict-poi"})

    with pytest.raises(ValueError, match="điểm đến khác"):
        repo.save_hue_pois([sample_poi, conflicting])

    assert repo.query("SELECT * FROM pois WHERE poi_id = ?", (sample_poi.poi_id,)) == []
    existing = repo.query("SELECT destination_id FROM pois WHERE poi_id = 'conflict-poi'")[0]
    assert existing["destination_id"] == "other"


def test_loader_connects_csv_to_db(fresh_db, tmp_path, monkeypatch, sample_poi):
    path = write_csv(tmp_path / "poi.csv", [sample_poi.model_dump()])
    monkeypatch.setattr(load_destination, "POI_PATH", path)
    monkeypatch.setattr("sys.argv", ["load_destination.py", "hue"])

    load_destination.main()
    load_destination.main()

    assert repo.query("SELECT COUNT(*) AS total FROM pois")[0]["total"] == 1