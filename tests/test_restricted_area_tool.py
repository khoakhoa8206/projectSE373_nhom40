"""Kiểm tool vùng hạn chế bằng DB tạm và hình học hư cấu."""

import json

import pytest

from agent.db import repo
from agent.src.graph.app import default_tools
from agent.src.graph.loop import tool_spec
from agent.src.tools.destination import check_restricted_area


@pytest.fixture
def zone(db):
    """Vùng hư cấu chứa POI seed Đại Nội, không chứa seed chợ Đông Ba."""
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [107.57, 16.46],
            [107.58, 16.46],
            [107.58, 16.48],
            [107.57, 16.48],
            [107.57, 16.46],
        ]],
    }
    repo.query(
        """INSERT INTO restricted_zones
        (zone_id, destination_id, name, zone_type, geometry,
         active_from, active_to, reason, source_url, license, verified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "test-zone", "hue", "Vùng kiểm thử hư cấu", "military",
            json.dumps(geometry), "2026-11-01", "2026-11-30",
            "Chỉ phục vụ unit test", "https://example.org/test-zone",
            "test-only", "2026-10-25",
        ),
    )


def test_inside_zone_returns_provenance(zone):
    result = check_restricted_area("hue-dai-noi", "2026-11-15")

    assert result["status"] == "ok"
    assert result["inside"] is True
    assert [item["zone_id"] for item in result["zones"]] == ["test-zone"]
    assert result["zones"][0]["source_url"] == "https://example.org/test-zone"
    assert result["zones"][0]["license"] == "test-only"
    assert "không phải xác nhận pháp lý" in result["note"]


def test_outside_zone(zone):
    result = check_restricted_area("hue-cho-dong-ba", "2026-11-15")

    assert result["status"] == "ok"
    assert result["inside"] is False
    assert result["zones"] == []


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2026-10-31", False),
        ("2026-11-01", True),
        ("2026-11-30", True),
        ("2026-12-01", False),
    ],
)
def test_zone_effective_dates(zone, day, expected):
    result = check_restricted_area("hue-dai-noi", day)

    assert result["inside"] is expected
    assert bool(result["zones"]) is expected


def test_missing_poi_is_not_reported_as_safe(db):
    result = check_restricted_area("missing-poi", "2026-11-15")

    assert result["status"] == "not_found"
    assert result["inside"] is None
    assert result["zones"] == []


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("not-a-date", ValueError),
        ("2026-02-30", ValueError),
        ("20261115", ValueError),
        (None, TypeError),
        (123, TypeError),
    ],
)
def test_invalid_date(db, value, error):
    with pytest.raises(error):
        check_restricted_area("hue-dai-noi", value)


@pytest.mark.parametrize("poi_id", ["", "   ", None, "x" * 161])
def test_invalid_poi_id(db, poi_id):
    with pytest.raises(ValueError):
        check_restricted_area(poi_id, "2026-11-15")


def test_point_on_polygon_boundary_is_inside(zone):
    repo.query("UPDATE pois SET lon = 107.57 WHERE poi_id = 'hue-dai-noi'")

    assert check_restricted_area("hue-dai-noi", "2026-11-15")["inside"] is True


def test_poi_missing_provenance_is_rejected(zone):
    repo.query("UPDATE pois SET license = '' WHERE poi_id = 'hue-dai-noi'")

    with pytest.raises(ValueError, match="POI thiếu"):
        check_restricted_area("hue-dai-noi", "2026-11-15")


def test_active_zone_missing_provenance_is_rejected(zone):
    repo.query("UPDATE restricted_zones SET source_url = ''")

    with pytest.raises(ValueError, match="thiếu metadata"):
        check_restricted_area("hue-dai-noi", "2026-11-15")


@pytest.mark.parametrize("field", ["source_url", "license", "verified_at"])
def test_active_zone_whitespace_provenance_is_rejected(zone, field):
    repo.query(f"UPDATE restricted_zones SET {field} = ?", (" \t ",))

    with pytest.raises(ValueError, match="thiếu metadata"):
        check_restricted_area("hue-dai-noi", "2026-11-15")


def test_tool_exposes_schema():
    spec = tool_spec(check_restricted_area)["function"]

    assert spec["name"] == "check_restricted_area"
    assert spec["description"]
    assert set(spec["parameters"]["required"]) == {"poi_id", "date"}


def test_tool_only_issues_select_queries(zone, monkeypatch):
    statements = []
    original_query = repo.query

    def record_query(sql, params=()):
        statements.append(sql.lstrip().split()[0].upper())
        return original_query(sql, params)

    monkeypatch.setattr(repo, "query", record_query)
    check_restricted_area("hue-dai-noi", "2026-11-15")

    assert statements
    assert set(statements) == {"SELECT"}


def test_default_tools_registers_restricted_area():
    tools = default_tools()
    names = [tool.__name__ for tool in tools]

    assert check_restricted_area in tools
    assert names.count("check_restricted_area") == 1
    assert {
        "search_poi", "get_poi", "get_opening_hours", "get_travel_time", "get_weather_forecast",
    }.issubset(names)


def test_no_zones_only_means_no_match(db):
    result = check_restricted_area("hue-dai-noi", "2026-11-15")

    assert result["inside"] is False
    assert result["zones"] == []
    assert "Không nằm trong vùng không đồng nghĩa an toàn" in result["note"]


def test_other_destination_zones_are_not_checked(zone):
    repo.query("INSERT INTO destinations (destination_id, name_vi, name_en) "
               "VALUES ('test-other', 'Điểm đến hư cấu', 'Fictional destination')")
    repo.query("UPDATE restricted_zones SET destination_id = 'test-other'")

    assert check_restricted_area("hue-dai-noi", "2026-11-15")["inside"] is False


def test_db_timeout_propagates_without_safe_result(db, monkeypatch):
    def unavailable(*args, **kwargs):
        raise TimeoutError("DB kiểm thử không phản hồi")

    monkeypatch.setattr(repo, "query", unavailable)
    with pytest.raises(TimeoutError):
        check_restricted_area("hue-dai-noi", "2026-11-15")
