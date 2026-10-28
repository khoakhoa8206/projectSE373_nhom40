"""Tool chỉ đọc, kiểm tham số và xử lý dữ kiện chưa biết."""

import pytest

from agent.db import repo
from agent.src.graph.loop import tool_spec
from agent.src.tools.destination import get_opening_hours, get_poi, get_travel_time, search_poi


def test_detail_and_search_keep_unknown(db):
    poi = get_poi("hue-dai-noi")
    assert poi["ticket_price_vnd"] is None and poi["opening_hours"] is None
    assert poi["license"] == "test" and poi["source_url"]
    assert [p["poi_id"] for p in search_poi("hue", category="food")] == ["hue-cho-dong-ba"]
    assert len(search_poi("hue", limit=1)) == 1
    assert search_poi("unsupported") == []


def test_search_filters_and_unknown_metadata(db):
    # metadata null không bị loại (planner ghi "chưa xác minh"); chỉ loại khi dữ liệu cho thấy không hợp
    assert len(search_poi("hue", child_age=6, outdoor=False, max_walking_level="low")) == 2
    repo.query("UPDATE pois SET min_age=3, walking_level='low', is_outdoor=0, tags='[\"history\",\"craft\"]' "
               "WHERE poi_id='hue-dai-noi'")
    assert len(search_poi("hue", child_age=6, max_walking_level="low", outdoor=False, tags=["history", "craft"])) == 1
    assert [p["poi_id"] for p in search_poi("hue", child_age=2)] == ["hue-cho-dong-ba"]
    assert [p["poi_id"] for p in search_poi("hue", outdoor=True)] == ["hue-cho-dong-ba"]
    assert search_poi("hue", tags=["history", "missing"]) == []


@pytest.mark.parametrize("kwargs", [
    {"limit": 0}, {"limit": 21}, {"limit": True}, {"limit": 1.5}, {"category": "other"},
    {"child_age": -1}, {"child_age": True}, {"max_walking_level": "tiny"},
    {"outdoor": "false"}, {"tags": "history"}, {"tags": [""]},
])
def test_search_rejects_bad_args(db, kwargs):
    with pytest.raises(ValueError):
        search_poi("hue", **kwargs)


def test_missing_source_is_not_public(db):
    repo.query("UPDATE pois SET license='' WHERE poi_id='hue-dai-noi'")
    assert len(search_poi("hue")) == 1
    with pytest.raises(ValueError):
        get_poi("hue-dai-noi")
    with pytest.raises(ValueError):
        get_poi("missing")


def test_hours_unknown_closed_and_split_day(db):
    assert get_opening_hours("hue-dai-noi", "2026-10-26")["open_intervals"] is None
    repo.query("UPDATE pois SET opening_hours='Tu-Su 08:00-12:00,13:00-17:00; Mo off' WHERE poi_id='hue-dai-noi'")
    assert get_opening_hours("hue-dai-noi", "2026-10-26")["closed"] is True
    assert get_opening_hours("hue-dai-noi", "2026-10-27")["open_intervals"] == [(480, 720), (780, 1020)]
    with pytest.raises(ValueError):
        get_opening_hours("hue-dai-noi", "not-date")


def test_travel_is_directed_mode_specific(db):
    repo.query("INSERT INTO travel_matrix VALUES (?, ?, 'drive', 7, 1200, 'osrm', '2026-10-25T00:00:00Z')",
               ("hue-dai-noi", "hue-cho-dong-ba"))
    result = get_travel_time("hue-dai-noi", "hue-cho-dong-ba", "drive")
    assert result["minutes"] == 7 and result["cached"] is True
    assert get_travel_time("hue-cho-dong-ba", "hue-dai-noi", "drive")["minutes"] is None
    assert get_travel_time("hue-dai-noi", "hue-cho-dong-ba", "walk")["status"] == "unavailable"
    with pytest.raises(ValueError):
        get_travel_time("hue-dai-noi", "hue-cho-dong-ba", "teleport")


def test_tools_expose_json_schema():
    for fn in (get_poi, search_poi, get_opening_hours, get_travel_time):
        spec = tool_spec(fn)["function"]
        assert spec["description"] and spec["parameters"]["type"] == "object"
