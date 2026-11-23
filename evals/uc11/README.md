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

**Còn thiếu:** 3 câu riêng cho RAG (`docs/uc-11.md` mục 12.2) và ngày lễ hội "đúng" để kỳ vọng `contradicted`. Từ W10-P4-4
verifier đã lấy bằng chứng lễ hội qua `retrieve_knowledge` (test bằng retriever giả: `tests/test_uc11_festival.py`), nhưng
kho `kb/docs` (22/11/2026) **chưa có tài liệu nào ghi ngày lễ hội**, và DB của runner không nạp kho tri thức. Khi P3 thêm tài
liệu lễ hội có nguồn thì thêm câu vào đây và cho runner nạp kho (`python -m agent.src.rag.ingest`).

## Chạy

- `pytest tests/test_uc11_cases.py`: cả bộ trên dữ liệu Huế thật (DB tạm), mock-weather trong tiến trình, không mạng hay key
  LLM. Kiểm ngưỡng của đề: recall claim sai ≥ 85 %, báo nhầm ≤ 10 %, 0 claim sai lọt ra, thời tiết phi lý bị đánh dấu 100 %.
  Kết quả 08/11/2026: 24/24 câu pass, recall 100 %, báo nhầm 0 %, 0 lọt, 100 % thời tiết phi lý bị đánh dấu, ~94 ms/câu.
- Runner (khi P1 thêm plug-in, W9-P1-3): DB mới + mock-weather theo `weather_mode` → `scorer.run_case(case)` → `run_id` →
  `scorer.score(case, conn, run_id)`; `scorer.metrics([(case, kết quả)])` tổng hợp chỉ số mục 12.3. UC-11 **không chạy graph
  UC-02**: đầu vào là câu trả lời nháp.
- Mặc định tách claim bằng regex (tất định). `UC11_EXTRACTOR=llm` để đo bản LLM + lưới regex (cần key, kết quả dao động).

## Đo với LLM thật + chi phí verifier (W10-P4-2)

`run_case` đóng run với token / chi phí / độ trễ của **riêng verifier** cho mỗi câu trả lời (LLM tách claim qua skill
`fact-check-travel-info`; tra tool và gắn nhãn là code, không tốn token), nên `summary.csv` của runner có cột `tokens`, `cost`,
`latency_ms` đúng nghĩa. `score()["metrics"]` ghi đủ số để tổng hợp lại không cần chạy lại:

```bash
# cần LLM_API_KEY trong .env; tắt mock-weather / run.py đang chạy (runner tự bật mock ở cổng 8081)
UC11_EXTRACTOR=llm python -m evals.run --uc UC-11        # → results/uc11-<thời gian>/
python -m evals.uc11.report results/uc11-<thời gian>      # in bảng dưới đây + ghi metrics.json
```

| Lượt | Tách claim | Case pass | Recall claim sai | Báo nhầm | Lọt | Thời tiết bất thường | Token / câu (vào / ra) | Chi phí / câu | Độ trễ / câu |
|---|---|---|---|---|---|---|---|---|---|
| 22/11/2026, dữ liệu Huế thật, 24 câu | regex | 24/24 | 100 % | 0 % | 0 | 100 % | 0 / 0 | 0 USD | ~105 ms |
| run #1 (24/11) | llm + lưới regex | _chưa chạy_ | | | | | | | |

Hàng regex đo bằng đúng `run_case` + `score` + `report` trên DB tạm có dữ liệu Huế thật, mock-weather trong tiến trình (như
`tests/test_uc11_cases.py`). Hàng LLM **chưa có số**: máy soạn ticket chưa có `LLM_API_KEY`; chạy hai lệnh trên ở run #1 rồi điền
bảng. Số regex lạc quan vì câu và regex do cùng một người viết; số LLM mới cho biết verifier chịu được cách viết tự nhiên.
