"""Lấy ma trận driving OSRM thật, lưu CSV nguyên tử để demo offline."""

import argparse
import csv
import json
import math
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from scripts.check_destination import POI_PATH, check_pois

HOSTS = {"router.project-osrm.org", "routing.openstreetmap.de"}
FIELDS = ["from_poi_id", "to_poi_id", "mode", "minutes", "distance_m", "provider", "computed_at"]


def fetch_table(pois, base_url="https://router.project-osrm.org", client=None):
    if urlparse(base_url).scheme != "https" or urlparse(base_url).hostname not in HOSTS:
        raise ValueError("Routing URL không nằm trong HTTPS allowlist.")
    coords = ";".join(f"{p.lon},{p.lat}" for p in pois)
    url = f"{base_url.rstrip('/')}/table/v1/driving/{coords}"
    own = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=False)
    try:
        for attempt in range(3):
            try:
                response = client.get(url, params={"annotations": "duration,distance"})
                response.raise_for_status()
                data = response.json()
                if data.get("code") != "Ok":
                    raise ValueError(f"OSRM không có kết quả hợp lệ: {data.get('code')}")
                return data
            except httpx.HTTPError:
                if attempt == 2:
                    raise
    finally:
        if own:
            client.close()


def build(pois, data):
    n = len(pois)
    for key in ("durations", "distances"):
        matrix = data.get(key)
        if not isinstance(matrix, list) or len(matrix) != n or any(len(r) != n for r in matrix):
            raise ValueError(f"OSRM {key} không đúng kích thước.")
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    rows, missing = [], []
    for i, origin in enumerate(pois):
        for j, target in enumerate(pois):
            seconds, meters = data["durations"][i][j], data["distances"][i][j]
            if seconds is None or meters is None:
                missing.append([origin.poi_id, target.poi_id])
                continue
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in (seconds, meters)):
                raise ValueError("OSRM trả thời gian/khoảng cách không hợp lệ.")
            rows.append(dict(zip(FIELDS, (origin.poi_id, target.poi_id, "drive", math.ceil(seconds / 60),
                                          math.ceil(meters), "osrm", stamp), strict=True)))
    return rows, missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://router.project-osrm.org")
    args = parser.parse_args()
    pois = check_pois(POI_PATH)
    data = fetch_table(pois, args.base_url)
    rows, missing = build(pois, data)
    output = POI_PATH.with_name("travel_matrix.csv")
    temp = output.with_suffix(".csv.tmp")
    with temp.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(output)
    POI_PATH.with_name("routing_provenance.json").write_text(json.dumps({
        "endpoint": args.base_url, "profile": "driving", "license": "ODbL-1.0 (OSM-derived)",
        "attribution": "OpenStreetMap contributors; OSRM", "poi_count": len(pois), "row_count": len(rows),
        "missing_pairs": missing, "rounding": "ceil(seconds / 60), ceil(distance_m)",
        "computed_at": rows[0]["computed_at"] if rows else None,
        "sources": data.get("sources"), "destinations": data.get("destinations"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Cached {len(rows)} directed drive pairs; {len(missing)} unreachable pairs (not invented).")


if __name__ == "__main__":
    main()
