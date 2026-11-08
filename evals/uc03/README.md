# Eval UC-03 · Thuyết minh có trích dẫn (P3)

## Bộ câu hỏi `narration_qa.jsonl` (W8-P3-3)

44 câu, mỗi dòng: `case_id`, `question`, `lang` (ngôn ngữ câu hỏi = ngôn ngữ phải trả lời), `poi_id` (UI “Đang ở đây”
gửi kèm, có thể null), `gold` = danh sách `{doc_id, section}` cần có trong top-5, `answer_keywords` (từ khoá câu trả
lời nên có), thêm `category` và, với câu có tài liệu cài chỉ dẫn, `must_not_contain`.

| Nhóm (`category`) | Số câu | Ý nghĩa |
|---|---|---|
| `same_lang` | 16 | Hỏi tiếng Việt về tài liệu tiếng Việt / tiếng Anh về tài liệu tiếng Anh |
| `cross_en_vi` | 6 | Hỏi tiếng Anh, đáp án chỉ có trong tài liệu tiếng Việt (Điện Kiến Trung, Quốc Học, Từ Đàm, bánh bèo, cơm hến) |
| `cross_vi_en` | 6 | Hỏi tiếng Việt, đáp án chỉ có trong tài liệu tiếng Anh (Điềm Phùng Thị, Bạch Mã, bún bò Huế, nhà Nguyễn, tổng quan Huế) |
| `poi` | 3 | Câu hỏi chung chung + `poi_id` (chế độ “Đang ở đây”) |
| `comparison` | 1 | Cần 2 đoạn của 2 tài liệu |
| `emergency` | 3 | Số khẩn cấp 112–115, đường dây nóng du lịch Huế |
| `injection` | 3 | Review/thông báo hư cấu có câu lệnh chèn: không làm theo, không trích làm dữ kiện (2 câu `gold = []`) |
| `out_of_kb` | 6 | Kho không có thông tin: phải trả đúng câu mẫu, không bịa (`gold = []`) |

Tổng cộng 8 câu `gold = []`. Đáp án và tên mục khớp tiêu đề `##` trong `kb/` (kiểm bằng `tests/test_uc03_qa.py`).

## Đo Recall@5

```bash
make db                                   # DB có POI (khoá ngoại của kb_documents)
python -m agent.src.rag.ingest            # lần đầu tải model ~220 MB
python -m evals.uc03.recall --write-readme
```

- Truy xuất giống node thuyết minh: có `poi_id` thì lọc tài liệu của POI trước, không có kết quả thì tìm toàn kho; không
  lọc ngôn ngữ (để câu hỏi tiếng Anh vẫn ra tài liệu tiếng Việt).
- Recall@5 = trung bình `|gold ∩ top-5| / |gold|` trên các câu có gold, khớp theo `(doc_id, section)`; Hit@5 = tỉ lệ câu
  có ít nhất 1 gold trong top-5. Câu `gold = []` không tính recall; điểm top-1 của chúng dùng để chọn ngưỡng out-of-KB.
- Mục tiêu Phase 3: Recall@5 ≥ 0,8. Phase 2: chạy được và ghi số thật bên dưới (script tự ghi khi có `--write-readme`).

## Kết quả đo

<!-- recall:start -->
Đo lúc 2026-11-08 18:07 · model `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` · 83 tài liệu, 387 chunk · 36 câu có gold + 8 câu ngoài kho.

- **Recall@5 = 0.7083**, Hit@5 = 0.7222
- Recall theo nhóm: comparison 0.5, cross_en_vi 0.5, cross_vi_en 0.3333, emergency 1.0, injection 1.0, poi 0.6667, same_lang 0.875
- Điểm top-1: câu có gold {'n': 36, 'min': 0.4479, 'median': 0.7163}; câu ngoài kho {'n': 8, 'max': 0.8174, 'median': 0.6721}

Câu chưa lấy đủ gold trong top-5:

- `uc03-qa-01` (same_lang) Chùa Thiên Mụ được xây dựng năm nào và do ai cho xây? → thiếu hue-chua-thien-mu-vi-01 §Khởi dựng và truyền thuyết; top-1: hue-tu-cam-thanh-vi-01 §Các công trình
- `uc03-qa-09` (same_lang) Chùa Báo Quốc do ai dựng và vào năm nào? → thiếu hue-chua-bao-quoc-vi-01 §Khởi dựng; top-1: hue-tu-cam-thanh-vi-01 §Các công trình
- `uc03-qa-17` (cross_en_vi) When was Kiến Trung Palace rebuilt after it was destroyed? → thiếu hue-dien-kien-trung-vi-01 §Bị phá hủy và xây dựng lại; top-1: hue-dien-kien-trung-vi-01 §Xây dựng thời Khải Định
- `uc03-qa-21` (cross_en_vi) What toppings are put on Huế bánh bèo? → thiếu hue-banh-beo-vi-01 §Nhân phủ và nước chấm; top-1: hue-bun-bo-hue-en-01 §How it is served
- `uc03-qa-22` (cross_en_vi) What is cơm hến usually served with? → thiếu hue-com-hen-vi-01 §Cách ăn; top-1: hue-com-hen-vi-01 §Thành phần
- `uc03-qa-23` (cross_vi_en) Nhà điêu khắc Điềm Phùng Thị sinh năm nào và mất năm nào? → thiếu hue-diem-phung-thi-en-01 §Overview; top-1: hue-dien-kien-trung-vi-01 §Xây dựng thời Khải Định
- `uc03-qa-24` (cross_vi_en) “Bảy mô-đun” trong điêu khắc của Điềm Phùng Thị là gì? → thiếu hue-diem-phung-thi-en-01 §The seven modules; top-1: hue-lang-khai-dinh-vi-01 §Cung Thiên Định
- `uc03-qa-25` (cross_vi_en) Vườn quốc gia Bạch Mã được thành lập năm nào và rộng bao nhiêu? → thiếu hue-vuon-quoc-gia-bach-ma-en-01 §Protection history, hue-vuon-quoc-gia-bach-ma-en-01 §Overview; top-1: hue-ky-dai-vi-01 §Phần đài
- `uc03-qa-26` (cross_vi_en) Nước dùng bún bò Huế được nấu từ những gì? → thiếu hue-bun-bo-hue-en-01 §Broth; top-1: hue-am-thuc-vi-01 §Bún bò Huế
- `uc03-qa-29` (poi) Giới thiệu ngắn về ngôi chùa này. → thiếu hue-chua-bao-quoc-vi-01 §Tổng quan; top-1: hue-chua-bao-quoc-en-01 §Architecture
- `uc03-qa-32` (comparison) Lăng Tự Đức và lăng Khải Định, lăng nào được khởi công trước? → thiếu hue-lang-khai-dinh-vi-01 §Xây dựng; top-1: hue-lang-tu-duc-vi-01 §Bố cục
<!-- recall:end -->
