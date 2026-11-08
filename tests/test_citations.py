"""W9-P3-2: validator trích dẫn (doc_id có thật, section có thật, quote nằm trong chunk của đúng mục) và chính sách
sửa 1 lần / bỏ ý còn sai / không còn ý nào thì ngoài kho. Không gọi LLM: `repair` là hàm giả."""

import pytest

from agent.db import repo
from agent.src.validation import citations as cv

DOC = {"doc_id": "hue-a-vi-01", "poi_id": None, "lang": "vi", "title": "Cầu A", "doc_type": "history",
       "is_fictional": 0, "source_url": "https://example.org/a", "license": "CC BY 4.0", "retrieved_at": "2026-11-07"}
CHUNKS = [
    {"chunk_id": "hue-a-vi-01:c0", "doc_id": "hue-a-vi-01", "section": "Xây dựng", "chunk_index": 0,
     "text": "Cầu khởi công tháng 5/1899 và\nkhánh thành ngày 18/12/1900.", "vector_id": "0"},
    {"chunk_id": "hue-a-vi-01:c1", "doc_id": "hue-a-vi-01", "section": "Các số", "chunk_index": 1,
     "text": "- **115:** Cấp cứu y tế.", "vector_id": "1"},
]  # fmt: skip


@pytest.fixture
def kb(db):
    repo.save_kb([DOC], CHUNKS)


def cit(quote, section="Xây dựng", doc_id="hue-a-vi-01", text="ý"):
    return {"text": text, "doc_id": doc_id, "section": section, "quote": quote}


def test_valid_quotes_after_whitespace_and_markdown_normalisation(kb):
    checked = cv.validate_citations([cit("khánh thành   ngày\n18/12/1900"), cit("115: Cấp cứu y tế", "Các số")])
    assert [c["is_valid"] for c in checked] == [True, True]
    assert [c["chunk_id"] for c in checked] == ["hue-a-vi-01:c0", "hue-a-vi-01:c1"]
    assert checked[0]["text"] == "ý" and checked[0]["reason"] is None  # giữ nguyên các trường khác của ý


@pytest.mark.parametrize(("citation", "reason", "chunk_id"), [
    (cit("khánh thành ngày 18/12/1900", doc_id="hue-khong-co-vi-01"), "doc_id", None),
    (cit("khánh thành ngày 18/12/1900", section="Lịch sử"), "section", None),
    (cit("Cấp cứu y tế"), "quote không nằm", "hue-a-vi-01:c0"),  # có trong tài liệu nhưng ở mục khác
    (cit("cầu được khánh thành cuối năm 1900"), "quote không nằm", "hue-a-vi-01:c0"),  # diễn giải, không phải trích
    (cit("  "), "quá ngắn", "hue-a-vi-01:c0"),
])  # fmt: skip
def test_invalid_citations(kb, citation, reason, chunk_id):
    [checked] = cv.validate_citations([citation])
    assert checked["is_valid"] is False and reason in checked["reason"] and checked["chunk_id"] == chunk_id


def test_no_repair_call_when_all_valid(kb):
    def repair(points, invalid):
        raise AssertionError("không được gọi LLM sửa khi mọi trích dẫn đều đúng")

    out = cv.enforce_citations([cit("khởi công tháng 5/1899")], repair)
    assert out["repaired"] is False and len(out["valid"]) == 1 and out["dropped"] == []


def test_repair_once_then_drop_still_invalid(kb):
    calls = []

    def repair(points, invalid):
        calls.append([p["quote"] for p in invalid])
        return [points[0], cit("khánh thành ngày 18/12/1900", text="sửa đúng"), cit("vẫn bịa", text="vẫn sai")]

    out = cv.enforce_citations([cit("khởi công tháng 5/1899"), cit("khánh thành năm 1901"), cit("bịa")], repair)
    assert calls == [["khánh thành năm 1901", "bịa"]]  # đúng 1 lần, chỉ gửi các ý sai
    assert out["repaired"] is True and [p["text"] for p in out["valid"]] == ["ý", "sửa đúng"]
    assert [p["text"] for p in out["dropped"]] == ["vẫn sai"]


def test_no_valid_point_left_means_out_of_kb(kb):
    out = cv.enforce_citations([cit("bịa")], lambda points, invalid: points)
    assert out["valid"] == [] and out["repaired"] is True and len(out["dropped"]) == 1


def test_save_citations_writes_is_valid(kb):
    trip_id = repo.create_trip("u-ha")
    message_id = repo.add_message(trip_id, "u-ha", "assistant", "...", "vi")
    checked = cv.validate_citations([cit("khởi công tháng 5/1899"), cit("bịa"), cit("x y z", doc_id="hue-khong-co")])
    assert cv.save_citations(message_id, checked) == 2  # trích dẫn không trỏ được chunk nào thì không ghi
    rows = repo.query("SELECT chunk_id, quote, is_valid FROM citations WHERE message_id = ? ORDER BY citation_id",
                      (message_id,))  # fmt: skip
    assert rows == [{"chunk_id": "hue-a-vi-01:c0", "quote": "khởi công tháng 5/1899", "is_valid": 1},
                    {"chunk_id": "hue-a-vi-01:c0", "quote": "bịa", "is_valid": 0}]
