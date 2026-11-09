# Kho tri thức Huế (P3-4 · UC-03)

- `catalog.csv` (UTF-8 có BOM để Excel hiển thị đúng dấu; trong Python đọc bằng `encoding="utf-8-sig"`): 60 tài liệu, chỉ gồm Huế: 15 cặp Việt–Anh, 8 chỉ tiếng Việt, 5 chỉ tiếng Anh, 5 tổng quan, 10 tình huống,
  2 tài liệu cài chỉ dẫn (hư cấu). `status = written` (15 tài liệu, có file trong `docs/`) hoặc `planned` (45 tài liệu).
- 9 cột đầu của catalog trùng tên và thứ tự cột bảng `kb_documents` (`agent/db/schema.sql`): `doc_id`, `poi_id`, `lang`,
  `title`, `doc_type`, `is_fictional` (0/1), `source_url`, `license`, `retrieved_at`. `poi_id` rỗng = NULL. Các cột sau
  (`destination`, `translation_group`, `group`, `eval_purpose`, `source_title`, `status`, `file`, `notes`) phục vụ nạp kho và eval.
- `docs/*.md`: front matter cùng các trường trên; mỗi tiêu đề `##` là một `section` (dùng trong trích dẫn `[doc_id §section]`).
  Cuối mỗi file ghi nguồn, ngày truy cập, giấy phép.
- Quy ước id: `poi_id` kiểu `hue-dai-noi` (`hue-` + tên không dấu, nối gạch ngang), phải có trong `pois` vì
  `kb_documents.poi_id` là khoá ngoại; `doc_id` = `<chủ đề>-<lang>-<số>`, ví dụ `hue-dien-kien-trung-vi-01`.
- Giấy phép: bài phỏng theo/dịch từ Wikipedia ghi CC BY-SA 4.0 kèm URL bài nguồn; tài liệu nhóm tự viết ghi CC BY 4.0.
  Bản tiếng Việt của các cặp được nhóm dịch và tóm lược từ bài tiếng Anh (ghi ở cuối file).
- Tài liệu `is_fictional = 1` (review “Nhà hàng Sông Hương Xanh”, thông báo bão giả) chỉ dùng kiểm thử chống injection,
  không bao giờ được trích làm dữ kiện.

## Nạp kho và truy xuất (UC-03 · RAG)

- Nạp: `make db` (cần bảng `pois` vì `kb_documents.poi_id` là khoá ngoại) rồi `python -m agent.src.rag.ingest`.
  Lệnh đọc `catalog.csv` + các file có cột `file` → ghi `kb_documents`, `kb_chunks` (1 mục `##` = 1 chunk, mục dài hơn
  600 ký tự cắt tiếp theo đoạn/câu, giữ tên mục) → tính embedding → `kb/index/vectors.npy` + `kb/index/meta.json`
  (gitignore, chạy lại lệnh là dựng lại). `kb_chunks.vector_id` = số dòng trong ma trận vector.
- Embedding: `fastembed` + `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (ONNX, 384 chiều, không cần
  torch). Lần đầu tự tải model ~220 MB vào cache của fastembed (đổi thư mục bằng biến `FASTEMBED_CACHE_PATH`).
  Nội dung kho không đổi thì lần chạy sau dùng lại vector cũ (nạp vào DB mới không chạy lại model); `--force` để tính lại.
- Thử truy xuất: `python -m agent.src.rag.retriever "When was Kien Trung Palace rebuilt?"` (thêm `--lang vi|en`,
  `--poi hue-dai-noi`, `-k 5`). Tool cho agent: `retrieve_knowledge(query, lang=None, poi_id=None, k=5)` trong
  `agent/src/rag/retriever.py`; mặc định không lọc ngôn ngữ nên câu hỏi tiếng Anh vẫn tìm ra tài liệu tiếng Việt.
- Test (`tests/test_rag.py`) dùng embedder giả `tests/fake_embedder.py`: không tải model, không gọi mạng.
