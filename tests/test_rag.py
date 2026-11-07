"""W8-P3-2: ingest + retrieve_knowledge chạy với embedder giả (không tải model, không gọi mạng, không cần key)."""

import csv
import io
import json
import re
from pathlib import Path

import numpy as np
import pytest

from agent.db import repo
from agent.db.init import init_db
from agent.src.graph.loop import tool_spec
from agent.src.rag import ingest as ing
from agent.src.rag import retriever
from scripts.check_destination import POI_PATH, check_pois
from tests.fake_embedder import FakeEmbedder

ROOT = Path(__file__).resolve().parents[1]
CATALOG = list(csv.DictReader(io.StringIO((ROOT / "kb" / "catalog.csv").read_text(encoding="utf-8-sig"))))
WRITTEN = [r for r in CATALOG if r["file"]]
FIELDS = {"chunk_id", "doc_id", "section", "text", "source_url", "lang", "doc_type", "is_fictional", "score"}
HEADER = ["doc_id", "poi_id", "lang", "title", "doc_type", "is_fictional", "source_url", "license", "retrieved_at",
          "file"]  # fmt: skip


def _no_model():
    raise AssertionError("test không được nạp model thật")


@pytest.fixture
def fake(db, tmp_path, monkeypatch):
    """DB tạm có POI thật của P2, index ở thư mục tạm, embedder giả; lỡ nạp model thật thì test fail."""
    monkeypatch.setenv("KB_INDEX_DIR", str(tmp_path / "index"))
    embedder = FakeEmbedder()
    monkeypatch.setattr(retriever, "EMBEDDER", embedder)
    monkeypatch.setattr(retriever, "_default_embedder", _no_model)
    repo.save_hue_pois(check_pois(POI_PATH))
    return embedder


@pytest.fixture
def real_kb(fake):
    """Kho thật trong kb/ (các tài liệu đã có file) nạp bằng embedder giả."""
    return ing.ingest()


def row(doc_id, **kw):
    base = {"doc_id": doc_id, "poi_id": "", "lang": doc_id.split("-")[-2], "title": doc_id, "doc_type": "history",
            "is_fictional": "0", "source_url": f"https://example.org/{doc_id}", "license": "CC BY 4.0",
            "retrieved_at": "2026-11-07", "file": f"docs/{doc_id}.md"}  # fmt: skip
    return base | kw


def write_kb(tmp_path, docs):
    """Kho nhỏ trong thư mục tạm: docs = [(dòng catalog, nội dung markdown hoặc None = không tạo file)]."""
    kb = tmp_path / "kb"
    (kb / "docs").mkdir(parents=True, exist_ok=True)
    with open(kb / "catalog.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, HEADER)
        writer.writeheader()
        for line, text in docs:
            if text is not None:
                (kb / line["file"]).write_text(text, encoding="utf-8")
            writer.writerow(line)
    return kb


def test_parse_sections_skips_front_matter_title_and_footer():
    text = ('---\ndoc_id: "hue-x-vi-01"\n---\n\n# Tiêu đề\n\nMở đầu.\n\n## Lịch sử\nXây năm 1601.\n\n'
            "## Kiến trúc\n- Tháp 7 tầng.\n- Cao 21 m.\n\n---\n*Nguồn: ví dụ, CC BY-SA 4.0.*\n")  # fmt: skip
    assert ing.parse_sections(text, "vi") == [
        ("Tổng quan", "Mở đầu."), ("Lịch sử", "Xây năm 1601."), ("Kiến trúc", "- Tháp 7 tầng.\n- Cao 21 m."),
    ]  # fmt: skip


def test_long_section_split_keeps_section_name():
    long_text = " ".join(f"Câu số {i} kể về lịch sử chùa Thiên Mụ bên bờ sông Hương." for i in range(40))
    chunks = ing.build_chunks({"doc_id": "hue-x-vi-01"}, [("Lịch sử", long_text), ("Ngắn", "Một câu.")])
    parts = [c for c in chunks if c["section"] == "Lịch sử"]
    assert len(parts) > 1 and all(len(c["text"]) <= ing.MAX_CHARS for c in parts)
    assert " ".join(c["text"] for c in parts).split() == long_text.split()  # không mất chữ nào
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert chunks[-1] | {"text": None} == {"chunk_id": f"hue-x-vi-01:c{len(chunks) - 1}", "doc_id": "hue-x-vi-01",
                                           "section": "Ngắn", "chunk_index": len(chunks) - 1, "text": None}


def test_ingest_repo_kb(real_kb, tmp_path):
    docs = repo.query("SELECT * FROM kb_documents")
    assert real_kb["documents"] == len(docs) == len(WRITTEN) >= 15
    assert all(d["source_url"] and d["license"] and d["retrieved_at"] for d in docs)
    chunks = repo.query("SELECT * FROM kb_chunks ORDER BY CAST(vector_id AS INTEGER)")
    assert real_kb["chunks"] == len(chunks) and [c["vector_id"] for c in chunks] == [str(i) for i in range(len(chunks))]
    for r in WRITTEN:  # mỗi tiêu đề `##` thành (ít nhất) 1 chunk cùng tên mục
        headings = re.findall(r"^## (.+?)\s*$", (ROOT / "kb" / r["file"]).read_text(encoding="utf-8"), re.MULTILINE)
        assert set(headings) == {c["section"] for c in chunks if c["doc_id"] == r["doc_id"]}, r["doc_id"]
    assert not any(c["text"].startswith(("---", "*Nguồn", "# ")) or "doc_id:" in c["text"] for c in chunks)
    meta = json.loads((tmp_path / "index" / "meta.json").read_text(encoding="utf-8"))
    vectors = np.load(tmp_path / "index" / "vectors.npy")
    assert vectors.shape == (len(chunks), 512) and meta["chunk_ids"] == [c["chunk_id"] for c in chunks]
    assert meta["model"] == FakeEmbedder.model_name and np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)


def test_cross_lingual_english_question_finds_vietnamese_doc(real_kb):
    out = retriever.retrieve_knowledge("When was Kien Trung Palace rebuilt?")
    assert out["status"] == "ok" and len(out["results"]) == 5
    assert "hue-dien-kien-trung-vi-01" in {r["doc_id"] for r in out["results"]}  # tài liệu chỉ có bản tiếng Việt
    only_en = retriever.retrieve_knowledge("When was Kien Trung Palace rebuilt?", lang="en")["results"]
    assert only_en and {r["lang"] for r in only_en} == {"en"}


def test_poi_filter(real_kb):
    expected = {r["doc_id"] for r in WRITTEN if r["poi_id"] == "hue-chua-thien-mu"}
    results = retriever.retrieve_knowledge("lịch sử xây dựng", poi_id="hue-chua-thien-mu", k=20)["results"]
    assert results and {r["poi_id"] for r in results} == {"hue-chua-thien-mu"}
    assert {r["doc_id"] for r in results} <= expected
    assert retriever.retrieve_knowledge("chợ", poi_id="hue-cho-dong-ba")["results"] == []  # POI có, chưa có tài liệu


def test_empty_kb_returns_no_results(fake, tmp_path):
    assert retriever.retrieve_knowledge("Đại Nội xây năm nào?") == {"status": "ok", "results": []}
    assert ing.ingest(write_kb(tmp_path, []))["chunks"] == 0  # catalog chưa có tài liệu nào được viết
    assert retriever.retrieve_knowledge("Huế") == {"status": "ok", "results": []}
    assert fake.calls == 0  # kho rỗng: không cần index, không gọi embedder


def test_results_shape_order_and_fictional_flag(real_kb):
    results = retriever.retrieve_knowledge("nhà hàng Sông Hương Xanh bún bò", k=3)["results"]
    assert len(results) == 3 and all(FIELDS <= set(r) for r in results)
    assert [r["score"] for r in results] == sorted((r["score"] for r in results), reverse=True)
    review = next(r for r in results if r["doc_id"] == "hue-review-song-huong-xanh-vi-01")
    assert review["is_fictional"] is True and review["doc_type"] == "review"
    assert all(r["is_fictional"] is False for r in results if r["doc_id"] != review["doc_id"])


def test_reingest_reuses_index_also_for_new_db(real_kb, fake, tmp_path, monkeypatch):
    calls = fake.calls
    assert ing.ingest()["reused"] is True and fake.calls == calls  # nội dung không đổi: không chạy lại embedder
    monkeypatch.setenv("DB_PATH", str(tmp_path / "eval.db"))  # DB mới (vd DB của eval) dùng lại index có sẵn
    init_db()
    repo.save_hue_pois(check_pois(POI_PATH))
    assert ing.ingest()["reused"] is True and fake.calls == calls
    assert retriever.retrieve_knowledge("Ngọ Môn")["results"] and fake.calls == calls + 1  # chỉ embed câu hỏi


def test_reingest_keeps_cited_chunk_without_vector(fake, tmp_path):
    a = (row("hue-a-vi-01", title="Tài liệu A"), "## Mục A\nĐiện Thái Hòa là nơi đăng quang.")
    b = (row("hue-b-vi-01", title="Tài liệu B"), "## Mục B\nChùa Thiên Mụ có tháp Phước Duyên.")
    c = (row("hue-c-en-01", title="Doc C"), "## Section C\nThe Perfume River flows through Huế.")
    kb = write_kb(tmp_path, [a, b, c])
    assert ing.ingest(kb)["chunks"] == 3
    trip_id = repo.create_trip("u-ha")
    message_id = repo.add_message(trip_id, "u-ha", "assistant", "Tháp Phước Duyên ...", "vi")
    repo.query("INSERT INTO citations (message_id, chunk_id, quote, is_valid) VALUES (?, ?, ?, 1)",
               (message_id, "hue-b-vi-01:c0", "tháp Phước Duyên"))  # fmt: skip
    write_kb(tmp_path, [a])  # bỏ B (đã được trích dẫn) và C khỏi kho
    assert ing.ingest(kb)["chunks"] == 1
    assert repo.query("SELECT chunk_id, vector_id FROM kb_chunks ORDER BY chunk_id") == [
        {"chunk_id": "hue-a-vi-01:c0", "vector_id": "0"}, {"chunk_id": "hue-b-vi-01:c0", "vector_id": None},
    ]  # fmt: skip
    assert {d["doc_id"] for d in repo.query("SELECT doc_id FROM kb_documents")} == {"hue-a-vi-01", "hue-b-vi-01"}
    results = retriever.retrieve_knowledge("Chùa Thiên Mụ tháp Phước Duyên")["results"]
    assert [r["doc_id"] for r in results] == ["hue-a-vi-01"]  # chunk giữ lại cho lịch sử không còn được tìm thấy


@pytest.mark.parametrize("field", ["source_url", "license", "retrieved_at"])
def test_ingest_rejects_missing_metadata(fake, tmp_path, field):
    kb = write_kb(tmp_path, [(row("hue-a-vi-01", **{field: ""}), "## A\nNội dung.")])
    with pytest.raises(ValueError, match=field):
        ing.ingest(kb)
    assert repo.query("SELECT COUNT(*) AS n FROM kb_documents") == [{"n": 0}]


def test_ingest_rejects_unknown_poi_and_file_outside_kb(fake, tmp_path):
    kb = write_kb(tmp_path, [(row("hue-a-vi-01", poi_id="hue-khong-co"), "## A\nNội dung.")])
    with pytest.raises(ValueError, match="hue-khong-co"):
        ing.ingest(kb)
    (tmp_path / "secret.md").write_text("## Bí mật\nkhông thuộc kho", encoding="utf-8")
    kb = write_kb(tmp_path, [(row("hue-b-vi-01", file="../secret.md"), None)])
    with pytest.raises(ValueError, match="không tìm thấy file"):
        ing.ingest(kb)


def test_index_built_with_other_model_is_rejected(real_kb, monkeypatch):
    other = FakeEmbedder()
    other.model_name = "another-model"
    monkeypatch.setattr(retriever, "EMBEDDER", other)
    with pytest.raises(RuntimeError, match="ingest"):
        retriever.retrieve_knowledge("Ngọ Môn")


def test_missing_index_file_is_reported(real_kb, tmp_path):
    (tmp_path / "index" / "vectors.npy").unlink()  # DB có chunk nhưng chưa có file vector
    with pytest.raises(RuntimeError, match="ingest"):
        retriever.retrieve_knowledge("Ngọ Môn")


def test_invalid_arguments_and_blank_filters(real_kb):
    with pytest.raises(ValueError, match="lang"):
        retriever.retrieve_knowledge("Ngọ Môn", lang="fr")
    with pytest.raises(ValueError, match="k"):
        retriever.retrieve_knowledge("Ngọ Môn", k=0)
    assert retriever.retrieve_knowledge("Ngọ Môn", lang="", poi_id="")["results"]  # LLM gửi chuỗi rỗng = không lọc
    assert retriever.retrieve_knowledge("   ")["results"] == []


def test_tool_schema_for_agent_loop():
    spec = tool_spec(retriever.retrieve_knowledge)["function"]
    assert spec["name"] == "retrieve_knowledge" and "xuyên ngôn ngữ" in spec["description"]
    assert set(spec["parameters"]["properties"]) == {"query", "lang", "poi_id", "k"}
    assert spec["parameters"]["required"] == ["query"]
