"""Nạp kho tri thức UC-03 (P3): kb/catalog.csv + file markdown trong kb/ → bảng kb_documents, kb_chunks + vector.
Chạy sau `make db` (cần bảng pois vì kb_documents.poi_id là khoá ngoại): python -m agent.src.rag.ingest [--force]
- Chỉ nạp dòng catalog có cột `file`; thiếu source_url/license/retrieved_at hoặc poi_id không có trong pois → dừng.
- 1 chunk = 1 mục `## `; mục dài hơn MAX_CHARS cắt tiếp theo đoạn/câu nhưng giữ tên mục để trích dẫn [doc_id §mục].
- Vector chuẩn hoá L2 lưu kb/index/vectors.npy (gitignore), kb_chunks.vector_id = số dòng trong ma trận.
  Nội dung và model không đổi thì dùng lại vector cũ (nạp vào DB mới, vd DB eval, không phải chạy lại model)."""

import argparse
import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from agent.db import repo
from agent.src.rag.retriever import KB_DIR, embedder_name, get_embedder, index_dir, normalize, read_meta

REQUIRED = ("doc_id", "lang", "title", "doc_type", "source_url", "license", "retrieved_at")
DOC_TYPES = {"history", "culture", "situation", "emergency", "review"}
MAX_CHARS = 600  # model cắt ở 128 token: mục dài cắt nhỏ để phần sau của mục vẫn được embed
INTRO = {"vi": "Tổng quan", "en": "Overview"}  # tên mục cho đoạn nằm trước tiêu đề `## ` đầu tiên


def read_catalog(kb_dir=KB_DIR) -> list[dict]:
    """Các dòng catalog đã có file (tài liệu `planned` chưa viết thì bỏ qua), kiểm đủ metadata bắt buộc."""
    kb_dir = Path(kb_dir)
    rows = csv.DictReader(io.StringIO((kb_dir / "catalog.csv").read_text(encoding="utf-8-sig")))
    docs = []
    for row in rows:
        row = {k: (v or "").strip() for k, v in row.items() if k}
        if not row.get("file"):
            continue
        doc_id = row.get("doc_id") or "?"
        missing = [c for c in REQUIRED if not row.get(c)]
        if missing:
            raise ValueError(f"{doc_id}: thiếu {', '.join(missing)} → không nạp")
        if row["lang"] not in INTRO or row["doc_type"] not in DOC_TYPES or row.get("is_fictional") not in ("0", "1"):
            raise ValueError(f"{doc_id}: lang/doc_type/is_fictional không hợp lệ")
        path = (kb_dir / row["file"]).resolve()
        if not path.is_relative_to(kb_dir.resolve()) or not path.is_file():
            raise ValueError(f"{doc_id}: không tìm thấy file {row['file']} trong {kb_dir}")
        docs.append(row | {"path": path})
    return docs


def parse_sections(text: str, lang: str = "vi") -> list[tuple[str, str]]:
    """[(tên mục, nội dung)] của 1 file: bỏ front matter, tiêu đề `# `, chú thích nguồn sau dòng `---` cuối bài."""
    body = re.sub(r"\A---\n.*?\n---\n", "", text.replace("\r\n", "\n"), count=1, flags=re.DOTALL)
    head, sep, tail = body.rpartition("\n---\n")
    if sep and tail.lstrip().startswith("*") and not re.search(r"^## ", tail, re.MULTILINE):
        body = head
    sections, name, lines = [], INTRO.get(lang, "Overview"), []
    for line in body.split("\n"):
        if line.startswith("## "):
            sections.append((name, "\n".join(lines).strip()))
            name, lines = line[3:].strip(), []
        elif not (line.startswith("# ") and not sections):  # tiêu đề tài liệu không phải nội dung
            lines.append(line)
    sections.append((name, "\n".join(lines).strip()))
    return [(n, t) for n, t in sections if t]


def split_long(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Cắt mục dài theo đoạn/dòng danh sách rồi theo câu, ghép lại thành các phần ≤ max_chars (câu đơn quá dài giữ
    nguyên). Mục ngắn trả nguyên văn."""
    if len(text) <= max_chars:
        return [text]
    units = []
    for block in re.split(r"\n\s*\n|\n(?=[-*] |\d+\. )", text):
        block = block.strip()
        units.extend([block] if len(block) <= max_chars else re.split(r"(?<=[.!?…;])\s+", block))
    parts, current = [], ""
    for unit in filter(None, (u.strip() for u in units)):
        if current and len(current) + 1 + len(unit) > max_chars:
            parts.append(current)
            current = unit
        else:
            current = f"{current}\n{unit}" if current else unit
    return [*parts, current] if current else parts


def build_chunks(doc: dict, sections: list[tuple[str, str]]) -> list[dict]:
    """Chunk của 1 tài liệu; chunk_id = '<doc_id>:c<chunk_index>' nên nạp lại cùng nội dung thì id không đổi."""
    chunks = []
    for section, text in sections:
        for part in split_long(text):
            index = len(chunks)
            chunks.append({"chunk_id": f"{doc['doc_id']}:c{index}", "doc_id": doc["doc_id"], "section": section,
                           "chunk_index": index, "text": part})  # fmt: skip
    return chunks


def ingest(kb_dir=KB_DIR, embedder=None, force=False) -> dict:
    """Nạp lại toàn bộ kho vào DB ở DB_PATH và dựng (hoặc dùng lại) vector index ở index_dir()."""
    docs = read_catalog(kb_dir)
    known = {r["poi_id"] for r in repo.query("SELECT poi_id FROM pois")}
    unknown = sorted({d["poi_id"] for d in docs if d.get("poi_id") and d["poi_id"] not in known})
    if unknown:
        raise ValueError(f"poi_id chưa có trong bảng pois: {', '.join(unknown)} (chạy `make db` hoặc sửa catalog)")

    chunks, passages = [], []
    for doc in docs:
        doc_chunks = build_chunks(doc, parse_sections(doc["path"].read_text(encoding="utf-8-sig"), doc["lang"]))
        if not doc_chunks:
            raise ValueError(f"{doc['doc_id']}: không có mục `## ` nào có nội dung")
        for chunk in doc_chunks:
            chunk["vector_id"] = str(len(chunks))
            chunks.append(chunk)
            passages.append(f"{doc['title']} — {chunk['section']}\n{chunk['text']}")  # tiêu đề giúp mục ngắn rõ nghĩa

    name = embedder_name(embedder)
    chunk_ids = [c["chunk_id"] for c in chunks]
    fingerprint = hashlib.sha256(json.dumps([name, chunk_ids, passages], ensure_ascii=False).encode()).hexdigest()
    folder = index_dir()
    reuse = not force and read_meta(folder).get("fingerprint") == fingerprint and (folder / "vectors.npy").exists()
    tmp = folder / "vectors.tmp.npy"
    if chunks and not reuse:
        vectors = normalize((embedder if embedder is not None else get_embedder())(passages))
        if len(vectors) != len(chunks):
            raise RuntimeError(f"embedder trả {len(vectors)} vector cho {len(chunks)} chunk")
        folder.mkdir(parents=True, exist_ok=True)
        np.save(tmp, vectors)

    rows = [{c: d.get(c) or None for c in repo.KB_DOC_COLS} | {"is_fictional": int(d.get("is_fictional") or 0)}
            for d in docs]  # fmt: skip
    result = repo.save_kb(rows, chunks)
    if chunks and not reuse:  # DB đã ghi xong mới thay index, lỗi giữa chừng thì index cũ vẫn khớp DB cũ
        os.replace(tmp, folder / "vectors.npy")
        meta = {"model": name, "dim": int(vectors.shape[1]), "count": len(chunks), "fingerprint": fingerprint,
                "built_at": repo.now(), "chunk_ids": chunk_ids}  # fmt: skip
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return result | {"model": name, "reused": reuse or not chunks, "index": str(folder)}


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Nạp kho tri thức vào DB ở DB_PATH và dựng vector index (kb/index)")
    ap.add_argument("--force", action="store_true", help="tính lại vector dù nội dung không đổi")
    result = ingest(force=ap.parse_args().force)
    how = "dùng lại vector cũ" if result["reused"] else f"đã tính vector bằng {result['model']}"
    print(f"Đã nạp {result['documents']} tài liệu, {result['chunks']} chunk → {result['index']} ({how})")


if __name__ == "__main__":
    main()
