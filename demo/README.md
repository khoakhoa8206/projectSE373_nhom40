# Video Phase 2

**Link video:** _(dán link Drive sau khi quay, sáng T3 10/11, trên bản đã tag `phase-2`)_ · Dài 3–5 phút.
File > 50 MB không đẩy lên Git, chỉ để link ở đây.

Quay trên PWA (bản `npm run build && npm run preview`, mở qua HTTPS theo `docs/pwa.md`), backend chạy thật, mock-weather chế độ
`normal`. Mỗi đoạn cần thấy được `run_id` để đối chiếu trace.

## Kịch bản (phải thấy đủ 4 yêu cầu của môn + ≥ 3 UC chạy từ PWA)

| # | Đoạn | Cần thấy trên màn hình | Clip của |
|---|---|---|---|
| 1 | UC-01 | Gõ "chị Thu Hà đi Huế 3 ngày, 8 triệu" → agent hỏi lại qua interrupt (thẻ câu hỏi, trả lời rồi gửi 1 lần) | P2 |
| 2 | Lưu state, resume | Đang chờ người dùng trả lời thì **tắt backend** → bật lại → trả lời → agent **chạy tiếp đúng chỗ**, không hỏi lại từ đầu | P1 |
| 3 | UC-02 | Lịch trình theo ngày + bản đồ + nhãn "chưa xác minh" (giá, giờ) → **bước người duyệt** (Duyệt / Sửa / Từ chối) | P2, P4 |
| 4 | UC-03 | Du khách tiếng Anh hỏi → trả lời có **trích dẫn** từ tài liệu tiếng Việt; hỏi câu ngoài kho → agent nói không có nguồn | P3 |
| 5 | UC-09 | Số **token trước → sau** khi tóm tắt (nén context) | P3 |
| 6 | Trace | Panel tiến trình theo `run_id`: từng node, tool, thời gian | P4 |

## Gom clip

- Tối T2 09/11: mỗi người gửi P4 clip hoặc kịch bản bấm từng bước của đoạn mình (cột "Clip của").
- Sáng T3 10/11, sau freeze 12:00: P4 quay lại toàn bộ trên bản đã freeze, dựng, dán link ở trên, nộp.
