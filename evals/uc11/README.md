# Eval UC-11 · Kiểm chứng thông tin

`cases.jsonl`: 24 câu trả lời nháp có lỗi cài sẵn (31 claim cần kiểm). `scorer.py`: plug-in `run_case` + `score`. Thiết kế:
`docs/uc-11.md` mục 12. Tên file theo hợp đồng runner (`evals/<uc>/cases.jsonl`); đề W9-P4-2 gọi là `seeded_answers.jsonl`.

## Định dạng 1 câu

```json
{"case_id": "uc11-006", "group": "wrong_hours", "lang": "vi", "target_type": "message",
 "context": {"destination_id": "hue", "trip_dates": ["2026-11-25", "2026-11-27"]}, "weather_mode": "normal",
 "text": "Bảo tàng Hồ Chí Minh mở cửa 8h–17h.", "poi_ids": ["hue-bao-tang-ho-chi-minh"],
 "seeded": [{"claim_type": "opening_hours", "wrong": "17h", "correct": "16:45",
             "source": "data/destinations/hue/poi.csv#hue-bao-tang-ho-chi-minh opening_hours"}],
 "expected": [{"claim_type": "opening_hours", "status": "verified", "span": "8h"},
              {"claim_type": "opening_hours", "status": "contradicted", "span": "17h"}]}
```

- `seeded`: mỗi lỗi cài sẵn, kèm giá trị đúng và nguồn. Giá trị đúng lấy từ `poi.csv`, `travel_matrix.csv` (P2) và
  `mock_data.json`, không lấy số ngoài dữ liệu nhóm. Dữ liệu không có thì `correct = null`, kỳ vọng `unverified`.
- `expected`: nhãn mong đợi của mọi claim trong câu (cả claim đúng, để đo báo nhầm). `span` phải trùng nguyên văn
  `claims.claim_text` mà verifier ghi (đúng đoạn bị thay khi sửa). Dữ liệu P2 đổi thì phải rà lại câu.
- `weather_mode`: chế độ mock-weather runner bật cho câu đó (`abnormal` = 48 °C, mưa âm).

## Bộ câu

| Nhóm | Số câu | Case tối thiểu của đề |
|---|---|---|
| `correct` | 5 | ✔ câu trả lời đúng hoàn toàn (đo báo nhầm) |
| `wrong_hours` (gồm "đóng cửa thứ Ba" sai) | 4 | ✔ giờ mở cửa sai |
| `wrong_price` | 3 | |
| `price_not_in_data` | 3 | ✔ giá vé không có trong dữ liệu (kỳ vọng `unverified`, không phải `contradicted`) |
| `abnormal_weather` | 3 | ✔ dự báo thời tiết giả |
| `wrong_festival_date` (sai năm) | 2 | ✔ ngày lễ hội sai năm (chưa có nguồn nên kỳ vọng `unverified`) |
| `wrong_distance` | 2 | |
| `wrong_weather`, `entity_not_found` | 2 | |

**Còn thiếu:** 3 câu riêng cho RAG (`docs/uc-11.md` mục 12.2) và ngày lễ hội "đúng" để kỳ vọng `contradicted`: cần
`retrieve_knowledge` của P3 + tài liệu lễ hội có nguồn.

## Chạy

- `pytest tests/test_uc11_cases.py`: cả bộ trên dữ liệu Huế thật (DB tạm), mock-weather trong tiến trình, không mạng hay key
  LLM. Kiểm ngưỡng của đề: recall claim sai ≥ 85 %, báo nhầm ≤ 10 %, 0 claim sai lọt ra, thời tiết phi lý bị đánh dấu 100 %.
  Kết quả 08/11/2026: 24/24 câu pass, recall 100 %, báo nhầm 0 %, 0 lọt, 100 % thời tiết phi lý bị đánh dấu, ~94 ms/câu.
- Runner (khi P1 thêm plug-in, W9-P1-3): DB mới + mock-weather theo `weather_mode` → `scorer.run_case(case)` → `run_id` →
  `scorer.score(case, conn, run_id)`; `scorer.metrics([(case, kết quả)])` tổng hợp chỉ số mục 12.3. UC-11 **không chạy graph
  UC-02**: đầu vào là câu trả lời nháp.
- Mặc định tách claim bằng regex (tất định). `UC11_EXTRACTOR=llm` để đo bản LLM + lưới regex (cần key, kết quả dao động).
