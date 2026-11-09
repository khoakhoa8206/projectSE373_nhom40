# Eval UC-01 · W9-P2-2

## Kết quả thật để review PR · 09/11/2026

User tự chạy Gemini `gemini-3.5-flash-lite` sau sửa intake. Đối chiếu evidence local
`results/uc01-20261109-214953/cases.jsonl`: **23/23 PASS**, cả23run succeeded,
schema23/23=100%, trườngcứng90/90=100%, conflict5/5=100%, unsupported3/3=100%, missingmetrics0.
Bản tổng hợp từng case không chứa hội thoại/trace thô ở `docs/evidence/uc01_sau_sua.json` của repo.

Giữ nguyên lần đầu `results/uc01-20261109-213211`:18/23PASS, schema95,65%,hard91,11%,
conflict80%,unsupported100%. I11lầnđầu là APIConnectionError, không bỏ case đó khỏi mẫu số.
Không sửa gold/scorer để khớp output. Metric100% chỉ trên bộ case/lượt này, không bảo đảm mọi hội thoại.

Transport vẫn gọi node intake nhiều lượt với messages chuẩn bị sẵn, chưa benchmark API/resume/checkpointer
P1 hoặc PWA end-to-end. Các ghi chú “chưa chạy/chờ key” bên dưới là lịch sử trước lần user chạy thật.
Kết quả được đưa vào nhánh nộp W9-P2-2 cùng evidence đã chọn trường; không đưa results/DB/key lên Git.
Các nhánh nguồn ban đầu giữ nguyên; không sửa gold/scorer để khớp đầu ra sau khi thấy kết quả.

---

23 case: R01–R15 tham chiếu gold/text gốc (không sửa file P3) + 8 case mới, trong đó 2 case nhiều lượt.
`expand_case` nạp gold **ở evaluator**, `run_case` chỉ gửi messages hội thoại vào intake/LLM, không gửi gold/expect.
Runtime agent không được đọc thư mục evals/.

## Lệnh user chạy sau khi có key

Từ worktree `nhom-40-p2-work`, dùng Python venv repo gốc:

```powershell
& 'D:\SE373_Agentic-ai_tourguide_hue\nhom-40\.venv\Scripts\python.exe' -X utf8 -m evals.run --uc UC-01
# Sau đó thay đường dẫn bằng results thật vừa tạo:
# python -m evals.uc01.report results/uc01-.../cases.jsonl
```

LLM_API_KEY/LLM_BASE_URL/LLM_MODEL thiết lập trong môi trường hoặc .env riêng của worktree (không commit key).
Không cần gửi key vào chat. Lệnh này gọi provider thật và có thể tốn phí; trợ lý **chưa chạy**.
Mỗi case có DB mới/results/traces; không dùng DB chuyến đi thật.

## Metric và giới hạn
- `schema_valid`: đủ output mỗi turn, profile hợp Pydantic, route nhất quán, tối đa 3 câu có field/text.
- `hard_correct/hard_total`: số field cứng đúng/số field cứng được chấm (ngày, đoàn, ngân sách, constraints, pace).
  Chuẩn hoá chữ hoa/thường/khoảng trắng, list không phụ thuộc thứ tự; **không đoán đồng nghĩa bằng LLM**.
  Cộng correct/total toàn bộ case khi báo accuracy, không lấy trung bình các mẫu có mẫu số khác nhau.
- Conflict phải hỏi lại kèm conflict; unsupported phải đúng route. Metric không thay thế passed/reasons.
- Mục tiêu: schema100%, hard≥90%, conflict100%, unsupported đúng; **chưa có số đo LLM thật**.
- Adapter hiện chạy node intake nhiều lượt với messages/answers cố định, không chạy LangGraph resume/API của P1
  vì chưa có trong clone. Không báo đây là test persistence hoặc end-to-end interrupt. Khi P1 có runner,
  thay phần transport trong run_case bằng messages/resume theo cùng cases/scorer, giữ nguyên gold.
- Một số gold P3 có constraints văn bản tự do; so literal có thể đánh trượt cách diễn đạt tương đương.
  Không sửa gold sau khi thấy output để làm đẹp tỷ lệ; reviewer có thể bổ sung quy tắc chấm minh bạch trước lần chạy sau.

## Kết quả thật
**Chưa chạy — user chờ API key.** Sau khi chạy, ghi results/<run>/, tổng case, metric và lỗi thực vào đây;
không dùng kết quả unit test/mock làm tỷ lệ trích xuất của LLM thật.

Kiểm thử local của bộ chấm: Ruff pass; **29 tests evaluator/report pass in 0.98s**.
Full suite trước khi thêm test report: 284 passed, 1 skipped in 47.39s (không phải kết quả eval live).
Report luôn hiện cases_missing_metrics; nếu số này >0, không dùng tỷ lệ trên các case còn lại để tuyên bố đạt mục tiêu.
