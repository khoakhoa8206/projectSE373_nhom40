"""Validator trích dẫn UC-03 (P3 · W9-P3-2). Mỗi trích dẫn {doc_id, section, quote} hợp lệ khi: doc_id có trong
kb_documents, section có trong tài liệu đó, quote nằm trong kb_chunks.text của đúng doc_id + section (so khớp sau khi
chuẩn hoá khoảng trắng). Không gọi LLM; chỉ đọc DB, riêng save_citations ghi bảng citations.
Chính sách: có trích dẫn sai → cho LLM sửa 1 lần (callback `repair`), vẫn sai thì bỏ ý đó; không còn ý hợp lệ thì
node thuyết minh trả câu "ngoài kho"."""

import re
import unicodedata

from agent.db import repo

MIN_QUOTE_CHARS = 4  # quote quá ngắn (vd 1–2 ký tự) nằm trong mọi đoạn nên không chứng minh được gì


def normalize(text) -> str:
    """Chuẩn hoá để so khớp: Unicode NFC, bỏ dấu nhấn markdown (* `), gộp mọi khoảng trắng thành 1 dấu cách."""
    text = unicodedata.normalize("NFC", text or "").replace("*", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def validate_citations(citations: list[dict]) -> list[dict]:
    """Trả bản sao từng trích dẫn kèm `is_valid`, `reason` (None khi hợp lệ) và `chunk_id` (chunk chứa quote; quote sai
    thì chunk đầu của mục để vẫn ghi được is_valid = 0; None khi doc_id/section không tồn tại)."""
    chunks = repo.kb_chunks_for_docs({c.get("doc_id") for c in citations if c.get("doc_id")})
    docs = {c["doc_id"] for c in chunks}
    results = []
    for cit in citations:
        doc_id, section, quote = cit.get("doc_id"), cit.get("section"), normalize(cit.get("quote"))
        same = [c for c in chunks if c["doc_id"] == doc_id and c["section"] == section]
        hit = next((c for c in same if quote and quote in normalize(c["text"])), None)
        if doc_id not in docs:
            reason = "doc_id không có trong kb_documents"
        elif not same:
            reason = "section không có trong tài liệu"
        elif len(quote) < MIN_QUOTE_CHARS:
            reason = "quote rỗng hoặc quá ngắn"
        elif hit is None:
            reason = "quote không nằm trong nội dung của mục"
        else:
            reason = None
        chunk = hit or (same[0] if same else None)
        results.append(cit | {"is_valid": reason is None, "reason": reason, "chunk_id": chunk and chunk["chunk_id"]})
    return results


def enforce_citations(points: list[dict], repair) -> dict:
    """Áp chính sách trích dẫn cho các ý {text, doc_id, section, quote, ...}.
    `repair(points, invalid)` được gọi tối đa 1 lần khi có ý sai (LLM sửa), trả danh sách ý mới; ý vẫn sai bị bỏ.
    Trả {"valid": [...], "dropped": [...], "repaired": bool}; `valid` rỗng nghĩa là trả câu ngoài kho."""
    checked = validate_citations(points)
    repaired = False
    if any(not p["is_valid"] for p in checked):
        repaired = True
        checked = validate_citations(repair(points, [p for p in checked if not p["is_valid"]]) or [])
    return {"valid": [p for p in checked if p["is_valid"]], "dropped": [p for p in checked if not p["is_valid"]],
            "repaired": repaired}  # fmt: skip


def save_citations(message_id: str, checked: list[dict]) -> int:
    """Ghi các trích dẫn đã kiểm vào bảng citations (is_valid 1/0). Trích dẫn không trỏ được chunk nào thì bỏ qua."""
    rows = [(message_id, c["chunk_id"], c.get("quote"), int(c["is_valid"])) for c in checked if c.get("chunk_id")]
    return repo.save_citations(rows)
