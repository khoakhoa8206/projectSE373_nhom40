"""W10-P4-4: claim ngày lễ hội lấy bằng chứng từ kho tri thức qua retrieve_knowledge. Retriever giả tiêm vào
`verify.retrieve`: các đoạn "kho" dưới đây là dữ liệu TEST hư cấu, không phải ngày Festival Huế thật."""

import pytest

from agent.db import repo
from agent.src.nodes import verify

CTX = {"destination_id": "hue", "trip_dates": ["2026-06-05", "2026-06-07"], "lang": "vi"}


def chunk(text, fictional=False, lang="vi", chunk_id="c1"):
    return {"chunk_id": chunk_id, "doc_id": "test-doc", "section": "Lễ hội", "text": text, "lang": lang,
            "source_url": "https://example.org/le-hoi", "doc_type": "review" if fictional else "culture",
            "is_fictional": fictional, "score": 0.8, "title": "Tài liệu test", "poi_id": None}  # fmt: skip


@pytest.fixture
def kb(db, monkeypatch):
    """Kho giả: trả các đoạn trong `kb.chunks`, ghi lại câu hỏi để kiểm."""

    class Kb:
        chunks, queries = [], []

    def fake_retrieve(query: str, lang: str | None = None, poi_id: str | None = None, k: int = 5) -> dict:
        Kb.queries.append({"query": query, "poi_id": poi_id, "k": k})
        return {"status": "ok", "results": Kb.chunks[:k]}

    monkeypatch.setattr(verify, "retrieve", fake_retrieve)
    Kb.run_id = repo.create_run("UC-11", repo.create_trip("u-ha"), "u-ha")
    return Kb


def check(kb, text, lang="vi"):
    res = verify.verify_and_fix(text, kb.run_id, ctx=CTX | {"lang": lang}, extractor=verify.extract_regex)
    rows = repo.query("SELECT * FROM claims WHERE run_id = ? AND claim_type = 'festival_date'", (kb.run_id,))
    return res, {r["claim_text"]: dict(r) for r in rows}


def test_matching_date_is_verified_from_kb(kb):
    kb.chunks = [chunk("Festival Huế 2026 diễn ra từ 6/6 đến 11/6/2026 tại nhiều di tích.")]
    res, rows = check(kb, "Festival Huế 2026 khai mạc ngày 6/6/2026.")
    assert res["text"] == "Festival Huế 2026 khai mạc ngày 6/6/2026."  # ngày bắt đầu lấy năm từ cùng câu
    assert rows["6/6/2026"].items() >= {"status": "verified", "evidence_kind": "kb", "evidence_ref": "c1",
                                        "source_url": "https://example.org/le-hoi"}.items()  # fmt: skip
    assert kb.queries == [{"query": "Festival Huế 2026 khai mạc ngày 6/6/2026.", "poi_id": None, "k": 5}]


def test_wrong_year_is_corrected(kb):
    kb.chunks = [chunk("Festival Huế 2026 diễn ra từ 6/6 đến 11/6/2026.")]
    res, rows = check(kb, "Festival Huế 2026 khai mạc ngày 6/6/2025.")  # case "sai năm" của đề
    assert rows["6/6/2025"]["status"] == "contradicted" and rows["6/6/2025"]["corrected_text"] == "6/6/2026"
    assert res["text"] == "Festival Huế 2026 khai mạc ngày 6/6/2026." and not res["blocked"]


def test_date_of_other_festival_is_not_evidence(kb):
    kb.chunks = [chunk("Lễ hội Điện Hòn Chén năm 2026 diễn ra ngày 15/3/2026."),
                 chunk("Festival Huế 2026 khai mạc 1/6/2026, theo một bạn đọc.", fictional=True)]  # review = ý kiến
    res, rows = check(kb, "Festival Huế 2026 khai mạc ngày 6/6/2026.")
    assert rows["6/6/2026"]["status"] == "unverified" and "(chưa xác minh)" in res["text"]


def test_month_only_source(kb):
    kb.chunks = [chunk("Festival Huế 2026 được tổ chức vào tháng 6/2026.")]
    _, rows = check(kb, "Festival Huế 2026 khai mạc ngày 6/6/2026.")
    assert rows["6/6/2026"]["status"] == "verified"


def test_english_answer_vietnamese_source(kb):
    kb.chunks = [chunk("Hue Festival 2026 runs from June 6 to 11, 2026.", lang="en")]
    res, rows = check(kb, "The Hue Festival 2026 opens on June 5th.", lang="en")
    assert rows["June 5th"]["status"] == "contradicted" and res["text"] == "The Hue Festival 2026 opens on June 6, 2026."


def test_retriever_error_is_unverified(kb, monkeypatch):
    def broken(query: str, lang: str | None = None, poi_id: str | None = None, k: int = 5) -> dict:
        raise RuntimeError("chưa có index")

    monkeypatch.setattr(verify, "retrieve", broken)
    _, rows = check(kb, "Festival Huế 2026 khai mạc ngày 6/6/2026.")
    assert rows["6/6/2026"]["status"] == "unverified"
    err = repo.query("SELECT error FROM trace_events WHERE run_id = ? AND kind = 'tool_call' AND name = 'broken'", (kb.run_id,))
    assert "chưa có index" in err[0]["error"]
