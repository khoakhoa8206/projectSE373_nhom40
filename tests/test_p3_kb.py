"""P3-4: kb/catalog.csv (60 tài liệu Huế) + 15 file kb/docs/*.md khớp bảng kb_documents của agent/db/schema.sql."""

import csv
import datetime as dt
import re
import warnings
from pathlib import Path

from agent.db import repo

ROOT = Path(__file__).resolve().parents[1]
KB_COLS = ["doc_id", "poi_id", "lang", "title", "doc_type", "is_fictional", "source_url", "license", "retrieved_at"]
CATALOG = list(csv.DictReader((ROOT / "kb" / "catalog.csv").read_text(encoding="utf-8-sig").splitlines()))
WRITTEN = [r for r in CATALOG if r["status"] == "written"]


def test_catalog_has_60_hue_documents():
    assert len(CATALOG) == 60 and len({r["doc_id"] for r in CATALOG}) == 60
    assert list(CATALOG[0])[:9] == KB_COLS  # 9 cột đầu = bảng kb_documents
    assert {r["lang"] for r in CATALOG} == {"vi", "en"} and {r["destination"] for r in CATALOG} == {"hue"}
    for r in CATALOG:
        assert r["doc_type"] in {"history", "culture", "situation", "emergency", "review"}, r["doc_id"]
        assert r["is_fictional"] in {"0", "1"} and r["license"] and r["source_url"], r["doc_id"]
        assert re.fullmatch(r"hue-[a-z0-9-]+-(vi|en)-\d{2}", r["doc_id"]) and r["doc_id"].split("-")[-2] == r["lang"]
        assert not r["poi_id"] or re.fullmatch(r"hue-[a-z0-9]+(-[a-z0-9]+)*", r["poi_id"]), r["doc_id"]
    text = "\n".join(p.read_text(encoding="utf-8-sig").lower() for p in (ROOT / "kb").rglob("*") if p.is_file())
    assert not re.search(r"hội an|hoi an|hoian|chùa cầu", text)  # kho chỉ gồm Huế


def test_written_docs_match_catalog():
    files = sorted(p.name for p in (ROOT / "kb" / "docs").glob("*.md"))
    assert len(WRITTEN) == 15 and sorted(Path(r["file"]).name for r in WRITTEN) == files
    for r in WRITTEN:
        text = (ROOT / "kb" / r["file"]).read_text(encoding="utf-8")
        head = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL).group(1)
        fm = {k.strip(): v.strip().strip('"') for k, _, v in (line.partition(":") for line in head.splitlines())}
        for col in KB_COLS:
            assert fm[col] == (r[col] or "null"), (r["doc_id"], col)
        assert dt.date.fromisoformat(r["retrieved_at"]) and re.search(r"^## ", text, re.MULTILINE), r["doc_id"]
        assert re.match(r"https?://|team://", r["source_url"]), r["doc_id"]
        assert r["license"].startswith(("CC BY-SA 4.0", "CC BY 4.0")), r["doc_id"]
        assert re.search(r"\n---\n\*.+\*\s*$", text, re.DOTALL), r["doc_id"]  # chú thích nguồn, giấy phép cuối bài


def test_written_rows_fit_kb_documents(db):
    """Dòng đã viết nạp được vào kb_documents (CHECK + khoá ngoại poi_id → pois). Khi đã có poi.csv của P2 mà
    thiếu poi_id thì cảnh báo (không chặn CI) để P3 sửa catalog trước khi nạp kho ở Phase 2."""
    poi_csv = ROOT / "data" / "destinations" / "hue" / "poi.csv"
    real = None
    if poi_csv.exists():
        real = {r["poi_id"] for r in csv.DictReader(poi_csv.read_text(encoding="utf-8-sig").splitlines())}
    for r in WRITTEN:
        if r["poi_id"]:
            if real is not None and r["poi_id"] not in real:
                warnings.warn(f"{r['doc_id']}: poi_id {r['poi_id']} chưa có trong {poi_csv.name} của P2", stacklevel=1)
            repo.query("""INSERT OR IGNORE INTO pois (poi_id, destination_id, name_vi, category, lat, lon, source_url,
                              license, verified_at) VALUES (?, 'hue', ?, 'attraction', 16.47, 107.58, 'https://example.org',
                              'test', '2026-10-24')""", (r["poi_id"], r["poi_id"]))  # fmt: skip
        repo.query(f"INSERT INTO kb_documents ({', '.join(KB_COLS)}) VALUES ({', '.join('?' * len(KB_COLS))})",
                   tuple(r[c] or None for c in KB_COLS))  # fmt: skip
    assert repo.query("SELECT COUNT(*) AS n FROM kb_documents")[0]["n"] == 15
