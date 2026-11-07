"""Embedder giả cho test RAG: không tải model, không gọi mạng, kết quả cố định.
Túi từ đã bỏ dấu, băm vào DIM chiều; vài từ Anh được quy về từ Việt cùng nghĩa để test được truy xuất xuyên ngôn ngữ
của pipeline (model thật làm việc này bằng embedding đa ngôn ngữ)."""

import re
import unicodedata
import zlib

import numpy as np

SYNONYMS = {
    "pagoda": "chua", "temple": "chua", "tomb": "lang", "mausoleum": "lang", "palace": "dien", "hall": "dien",
    "gate": "mon", "emergency": "khancap", "police": "congan", "ambulance": "capcuu", "fire": "chay",
    "built": "xay", "build": "xay", "rebuilt": "xay", "construction": "xay", "emperor": "vua", "king": "vua",
    "tower": "thap", "bell": "chuong", "number": "so", "numbers": "so", "call": "goi",
}  # fmt: skip
PHRASES = {"khan cap": "khancap", "cong an": "congan", "cap cuu": "capcuu", "xay dung": "xay"}
STOPWORDS = {"the", "a", "an", "of", "is", "was", "who", "what", "when", "where", "which", "how", "in", "to", "and",
             "la", "cua", "va", "o", "co", "nao", "gi", "khi", "nhung", "cac", "duoc", "mot"}  # fmt: skip


def fold(text: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt (đ → d)."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


class FakeEmbedder:
    model_name = "fake-bow-512"

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.calls = 0  # số lần được gọi, để test kiểm tra có dùng lại index không

    def __call__(self, texts):
        self.calls += 1
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            folded = fold(text)
            for phrase, token in PHRASES.items():
                folded = folded.replace(phrase, token)
            for word in re.findall(r"[a-z0-9]+", folded):
                if word not in STOPWORDS:
                    out[row, zlib.crc32(SYNONYMS.get(word, word).encode()) % self.dim] += 1.0
        return out
