"""W8-P3-1: kho tri thức Huế ≥ 60 tài liệu. Catalog ↔ file khớp 1–1, 100% có source_url/license/retrieved_at,
poi_id có trong poi.csv của P2, số điện thoại chỉ lấy từ nguồn chính thức (ghi URL ở cuối file)."""

import csv
import datetime as dt
import io
import re
from pathlib import Path

from agent.db import repo
from scripts.check_destination import POI_PATH, check_pois

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "kb"
KB_COLS = ["doc_id", "poi_id", "lang", "title", "doc_type", "is_fictional", "source_url", "license", "retrieved_at"]
CATALOG = list(csv.DictReader(io.StringIO((KB / "catalog.csv").read_text(encoding="utf-8-sig"))))
DOCS = [r for r in CATALOG if r["doc_type"] != "review"]  # review hư cấu (W8-P3-3) đếm riêng
POIS = {r["poi_id"] for r in csv.DictReader(io.StringIO(POI_PATH.read_text(encoding="utf-8-sig")))}
EMERGENCY = {"112", "113", "114", "115"}  # đã đối chiếu nguồn .gov.vn ghi trong tài liệu khẩn cấp
OFFICIAL_NUMBERS = {"0234.3828288": "https://visithue.vn/ho-tro/"}  # đường dây nóng du lịch Huế
SHORT = re.compile(r"(?<![\d.,])11\d(?!\d|[.,]\d)")
LONG = re.compile(r"\b0\d{2,3}[.\s-]?\d{3,4}[.\s-]?\d{3,4}\b")


def read(row):
    """(front matter, nội dung, chú thích nguồn) của file trong catalog."""
    text = (KB / row["file"]).read_text(encoding="utf-8")
    head, body = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL).groups()
    fm = {k.strip(): v.strip().strip('"') for k, _, v in (line.partition(":") for line in head.splitlines())}
    body, _, footer = body.rpartition("\n---\n")
    return fm, body, footer


def test_catalog_has_at_least_60_hue_documents():
    assert len(DOCS) >= 60 and len({r["doc_id"] for r in CATALOG}) == len(CATALOG)
    assert list(CATALOG[0])[:9] == KB_COLS  # 9 cột đầu = bảng kb_documents
    assert {r["lang"] for r in DOCS} == {"vi", "en"} and {r["destination"] for r in CATALOG} == {"hue"}
    for r in CATALOG:
        assert r["doc_type"] in {"history", "culture", "situation", "emergency", "review"}, r["doc_id"]
        assert r["is_fictional"] in {"0", "1"}, r["doc_id"]
        assert re.fullmatch(r"hue-[a-z0-9-]+-(vi|en)-\d{2}", r["doc_id"]) and r["doc_id"].split("-")[-2] == r["lang"]
    mono = [r["lang"] for r in DOCS if not r["translation_group"] and r["is_fictional"] == "0"]
    assert mono.count("vi") >= 5 and mono.count("en") >= 5  # chỉ có 1 thứ tiếng: đích của câu hỏi xuyên ngôn ngữ
    assert {"emergency", "situation"} <= {r["doc_type"] for r in DOCS}
    # Chỉ đọc file văn bản của kho: bỏ qua kb/index/ (vector nhị phân do ingest tạo, đã gitignore).
    files = [p for p in KB.rglob("*") if p.is_file() and p.suffix in {".md", ".csv"}]
    text = "\n".join(p.read_text(encoding="utf-8-sig").lower() for p in files)
    assert not re.search(r"hội an|hoi an|hoian|chùa cầu", text)  # kho chỉ gồm Huế


def test_catalog_matches_files():
    files = {p.relative_to(KB).as_posix() for p in KB.glob("*/*.md")}
    assert {r["file"] for r in CATALOG} == files and len(files) == len(CATALOG)
    assert {r["status"] for r in CATALOG} == {"written"}


def test_every_document_has_source_license_date_and_sections():
    for r in CATALOG:
        fm, body, footer = read(r)
        for col in KB_COLS:
            assert fm[col] == (r[col] or "null"), (r["doc_id"], col)
        assert r["source_url"] and r["license"] and dt.date.fromisoformat(r["retrieved_at"]), r["doc_id"]
        assert re.match(r"https://|team://", r["source_url"]), r["doc_id"]
        assert r["license"].startswith(("CC BY-SA 4.0", "CC BY 4.0")), r["doc_id"]
        sections = re.findall(r"^## (.+)$", body, re.MULTILINE)
        assert sections and len(sections) == len(set(sections)), r["doc_id"]  # [doc_id §mục] không nhập nhằng
        assert re.fullmatch(r"\*.+\*\s*", footer, re.DOTALL), r["doc_id"]  # chú thích nguồn, giấy phép cuối bài
        if r["source_url"].startswith("https://"):
            assert r["source_url"] in footer, r["doc_id"]


def test_poi_ids_exist_in_p2_poi_csv():
    for r in CATALOG:
        assert not r["poi_id"] or r["poi_id"] in POIS, r["doc_id"]


def test_phone_numbers_only_from_official_sources():
    covered = set()
    for r in CATALOG:
        _, body, footer = read(r)
        shorts, longs = set(SHORT.findall(body)), set(LONG.findall(body))
        if r["is_fictional"] == "1":
            assert not shorts and not longs, r["doc_id"]  # tài liệu hư cấu không chứa số điện thoại
            continue
        assert shorts <= EMERGENCY and (not shorts or ".gov.vn/" in footer), r["doc_id"]
        for number in longs:
            assert number in OFFICIAL_NUMBERS and OFFICIAL_NUMBERS[number] in footer, (r["doc_id"], number)
        if r["doc_type"] == "emergency":
            covered |= shorts
    assert covered == EMERGENCY  # có tài liệu khẩn cấp nêu đủ 112–115


def test_documents_fit_kb_documents_table(db):
    """Mọi dòng nạp được vào kb_documents (CHECK + khoá ngoại poi_id → pois với POI thật của P2)."""
    repo.save_hue_pois(check_pois(POI_PATH))
    for r in CATALOG:
        repo.query(f"INSERT INTO kb_documents ({', '.join(KB_COLS)}) VALUES ({', '.join('?' * len(KB_COLS))})",
                   tuple(r[c] or None for c in KB_COLS))  # fmt: skip
    assert repo.query("SELECT COUNT(*) AS n FROM kb_documents")[0]["n"] == len(CATALOG)
