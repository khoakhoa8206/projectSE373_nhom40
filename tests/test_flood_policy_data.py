"""Giữ tag có nguồn và dấu vết sửa dữ liệu mùa lũ; không truy cập mạng."""

import csv
import hashlib
import json
from pathlib import Path

from agent.src.validation.validator import HUE_FLOOD_MONTHS

DATA = Path(__file__).resolve().parents[1] / "data"


def test_riverside_tag_has_field_level_source():
    with (DATA / "destinations/hue/poi.csv").open(encoding="utf-8-sig", newline="") as file:
        pois = {row["poi_id"]: row for row in csv.DictReader(file)}
    with (DATA / "sources_licenses.csv").open(encoding="utf-8-sig", newline="") as file:
        sources = {row["record_id"]: row for row in csv.DictReader(file)}

    assert "riverside" in json.loads(pois["hue-chua-thien-mu"]["tags"])
    source = sources["hue-chua-thien-mu#tags"]
    assert source["source_url"] == "https://vietnam.travel/plan-your-trip/recommended-trip/vietnam-highlights/"
    assert all(source[field].strip() for field in ("license", "verified_at", "attribution"))


def test_flood_months_have_documented_source():
    manifest = (DATA / "manifest.md").read_text(encoding="utf-8")

    assert HUE_FLOOD_MONTHS == {9, 10, 11, 12}
    assert "3279/QĐ-UBND" in manifest
    assert "https://hue.gov.vn/" in manifest
    assert "2026-11-09" in manifest


def test_policy_manifest_records_updated_poi_hash():
    content = (DATA / "destinations/hue/poi.csv").read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256(content).hexdigest()

    assert digest in (DATA / "manifest.md").read_text(encoding="utf-8")
