"""Kiểm metadata POI và tính toàn vẹn manifest; không gọi mạng."""

import csv
import hashlib
import re
from pathlib import Path

import pytest

from scripts.check_destination import POI_PATH, check_pois

ROOT = Path(__file__).resolve().parents[1]
METADATA = ("source_url", "license", "verified_at")


def test_all_real_pois_have_provenance():
    """Mọi dòng POI thật phải qua checker và có đủ metadata."""
    with POI_PATH.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    pois = check_pois(POI_PATH)

    assert len(pois) == len(rows) >= 30
    for row in rows:
        for field in METADATA:
            assert row[field].strip(), f"{row['poi_id']} thiếu {field}"


@pytest.mark.parametrize("field", METADATA)
@pytest.mark.parametrize("value", ["", " \t "])
def test_checker_rejects_blank_provenance(tmp_path, field, value):
    """Metadata rỗng hoặc toàn khoảng trắng đều phải bị từ chối."""
    with POI_PATH.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames
        row = next(reader)

    row[field] = value
    path = tmp_path / "invalid_poi.csv"

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    with pytest.raises(ValueError):
        check_pois(path)


def test_manifest_covers_files_and_matches_hashes():
    """Manifest phải ghi đủ file, không trùng và khớp SHA256 chuẩn LF."""
    manifest = (ROOT / "data" / "manifest.md").read_text(
        encoding="utf-8"
    )
    entries = re.findall(
        r"^\|\s*([\w.-]+)\s*\|\s*([0-9a-fA-F]{64})\s*\|[ \t]*$",
        manifest,
        flags=re.MULTILINE,
    )
    hashes = dict(entries)

    assert entries, "Manifest chưa có bảng SHA256"
    assert len(entries) == len(hashes), "Trùng tên file trong bảng SHA256"

    files = {
        path.name: path
        for path in POI_PATH.parent.iterdir()
        if path.is_file()
    }
    assert set(hashes) == set(files), "Manifest thiếu hoặc thừa file"

    for name, path in files.items():
        content = path.read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(content).hexdigest()
        assert actual == hashes[name].lower(), f"Hash không khớp: {name}"