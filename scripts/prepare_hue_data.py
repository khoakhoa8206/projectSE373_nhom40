"""Tái tạo dữ liệu tuyển chọn từ snapshot OSM công khai; không tự suy đoán giá/giờ."""

import argparse
import csv
import json
from pathlib import Path

from agent.schemas import POI

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "destinations" / "hue"
VERIFIED = "2026-10-25"
WIKI = "https://en.wikivoyage.org/w/index.php?title=Hue&oldid=5384053"
# Mã tương thích KB P3; phần còn lại là mã ổn định theo địa điểm, không theo thứ tự CSV.
WIKI_POIS = [
    ("hue-chua-thien-mu", "Chùa Thiên Mụ", "Thien Mu Pagoda", 16.45355, 107.54461, "See"),
    ("hue-dai-noi", "Đại Nội Huế", "Imperial City of Hue", 16.46955, 107.57782, "Imperial_Citadel"),
    ("hue-lang-tu-duc", "Lăng Tự Đức", "Tomb of Tu Duc", 16.4332, 107.5653, "Tombs_of_the_Emperors"),
    ("hue-lang-khai-dinh", "Lăng Khải Định", "Tomb of Khai Dinh", 16.39892, 107.59028, "Tombs_of_the_Emperors"),
]
OSM_POIS = [
    ("way", 240266284, "hue-bao-tang-ho-chi-minh", "attraction"),
    ("way", 695810710, "hue-bao-tang-co-vat", "attraction"),
    ("way", 118540998, "hue-diem-phung-thi", "attraction"),
    ("way", 1170979640, "hue-chua-bao-quoc", "attraction"),
    ("way", 771244228, "hue-chua-dieu-de", "attraction"),
    ("way", 683524977, "hue-cau-thanh-toan", "attraction"),
    ("way", 695810698, "hue-vien-co-mat", "attraction"),
    ("way", 1473275556, "hue-lang-huong-thuy-xuan", "attraction"),
    ("node", 5299153429, "hue-bia-quoc-hoc", "attraction"),
    ("way", 531031518, "hue-quoc-tu-giam", "attraction"),
    ("way", 531031566, "hue-dien-thai-hoa", "attraction"),
    ("node", 4693154298, "hue-quan-hanh", "food"),
    ("node", 5243743124, "hue-madam-thu", "food"),
    ("node", 4836391621, "hue-lac-thien", "food"),
    ("node", 5380973122, "hue-lac-thanh", "food"),
    ("node", 7223176485, "hue-com-hen-hoa-dong", "food"),
    ("node", 4634514389, "hue-chay-thanh-lieu", "food"),
    ("node", 6157857785, "hue-san-may", "food"),
    ("node", 7103878786, "hue-loving-hut", "food"),
    ("node", 11914764769, "hue-lien-hoa", "food"),
    ("node", 12412512101, "hue-spice-viet", "food"),
    ("way", 239566031, "hue-saigon-morin", "lodging"),
    ("way", 240131252, "hue-indochine-palace", "lodging"),
    ("way", 240266283, "hue-la-residence", "lodging"),
    ("way", 251616147, "hue-silk-path", "lodging"),
    ("way", 1280445132, "hue-senna", "lodging"),
]
ZONE_IDS = [1033694882, 1172668060, 1332926251, 1346325479, 1493416350]


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def prepare(snapshot: Path):
    raw = json.loads(snapshot.read_text(encoding="utf-8"))
    elements = {(e["type"], e["id"]): e for e in raw["elements"]}
    rows, provenance, selected = [], [], []
    for pid, vi, en, lat, lon, anchor in WIKI_POIS:
        row = POI(poi_id=pid, destination_id="hue", name_vi=vi, name_en=en, category="attraction",
                  lat=lat, lon=lon, source_url=f"{WIKI}#{anchor}", license="CC-BY-SA-4.0", verified_at=VERIFIED)
        rows.append(row.model_dump())
    for kind, eid, pid, category in OSM_POIS:
        e = elements[kind, eid]
        tags = e["tags"]
        if kind == "node":
            location = e
        else:
            bounds = e["bounds"]
            location = {"lat": (bounds["minlat"] + bounds["maxlat"]) / 2,
                        "lon": (bounds["minlon"] + bounds["maxlon"]) / 2}
        labels = ["food"] if category == "food" else (["history"] if category == "attraction" else ["lodging"])
        if tags.get("diet:vegetarian") == "only" or tags.get("diet:vegan") == "only":
            labels.append("vegetarian")
        # Không suy ra indoor/outdoor, walking_level hoặc thời lượng từ tên địa điểm.
        display_name = tags["name"] if pid == "hue-lang-huong-thuy-xuan" else tags.get("name:vi", tags["name"])
        row = POI(poi_id=pid, destination_id="hue", name_vi=display_name,
                  name_en=tags.get("name:en"), category=category, lat=location["lat"], lon=location["lon"],
                  opening_hours=tags.get("opening_hours"), tags=labels,
                  source_url=f"https://www.openstreetmap.org/{kind}/{eid}", license="ODbL-1.0", verified_at=VERIFIED)
        rows.append(row.model_dump())
        keep = {k: v for k, v in e.items() if k in ("type", "id", "lat", "lon", "center", "bounds", "geometry")}
        keep["tags"] = {k: v for k, v in tags.items() if k in (
            "name", "name:vi", "name:en", "tourism", "amenity", "opening_hours", "diet:vegetarian", "diet:vegan")}
        selected.append(keep)
    zones = []
    for eid in ZONE_IDS:
        e = elements["way", eid]
        coords = [[p["lon"], p["lat"]] for p in e["geometry"]]
        if coords[0] != coords[-1] or len(coords) < 4:
            raise ValueError(f"OSM way {eid} không phải polygon khép kín.")
        properties = {
            "zone_id": f"hue-osm-military-{eid}", "destination_id": "hue",
            "name": e["tags"].get("name", f"Vùng landuse=military OSM {eid}"), "zone_type": "military",
            "active_from": None, "active_to": None,
            "reason": "OSM gắn landuse=military: loại khỏi gợi ý du lịch; không phải xác nhận pháp lý thực địa.",
            "source_url": f"https://www.openstreetmap.org/way/{eid}", "license": "ODbL-1.0", "verified_at": VERIFIED,
        }
        zones.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]},
                      "properties": properties})
        selected.append({"type": "way", "id": eid, "geometry": e["geometry"],
                         "tags": {k: v for k, v in e["tags"].items() if k in ("name", "landuse", "military")}})
    OUT.mkdir(parents=True, exist_ok=True)
    for row in rows:
        provenance.append({"record_id": row["poi_id"], "source_url": row["source_url"], "license": row["license"],
                           "verified_at": VERIFIED, "attribution": "Wikivoyage contributors" if row["license"] ==
                           "CC-BY-SA-4.0" else "OpenStreetMap contributors"})
        row["tags"] = json.dumps(row["tags"], ensure_ascii=False)
    provenance.extend({k: p[k] for k in ("source_url", "license", "verified_at")} |
                      {"record_id": p["zone_id"], "attribution": "OpenStreetMap contributors"}
                      for p in (z["properties"] for z in zones))
    write_csv(OUT / "poi.csv", rows, list(POI.model_fields))
    write_csv(ROOT / "data" / "sources_licenses.csv", provenance,
              ["record_id", "source_url", "license", "verified_at", "attribution"])
    (OUT / "restricted_zones.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": zones}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "osm_snapshot.json").write_text(json.dumps({"osm3s": raw.get("osm3s"), "elements": selected},
                                                    ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã tạo {len(rows)} POI, {len(zones)} vùng từ nguồn, không điền giá chưa biết.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--osm-input", type=Path, required=True)
    prepare(parser.parse_args().osm_input)
