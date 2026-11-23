# Eval UC-07 · Bộ nhớ sở thích qua nhiều chuyến

Chạy: `python -m evals.run --uc UC-07` (hoặc `--all --name run1`). Không gọi LLM: mỗi case chạy code thật của node
memory, store và API (tài khoản đăng ký thật, cookie phiên) trên DB riêng của case.

| Case | Kịch bản | Đạt khi |
|---|---|---|
| M01 | Người dùng tick sở thích + dị ứng trên thẻ "lưu sở thích này?" | Lưu đúng các loại đã tick; mục nhạy cảm có `consent_id` |
| M02 | Từ chối cả thẻ | Không lưu mục nào |
| M03 | Chuyến sau | `memory_context` nạp đủ mục đã lưu (`recall` = 1); trace `memory_read` chỉ có id + loại, không có giá trị |
| M04 | Case tấn công 4: user B đọc/sửa/xoá mục của A, gửi kèm `user_id` của A | B thấy 0 mục, PATCH/DELETE 404, mục của A nguyên vẹn (`leak` = 0) |
| M05 | Thu hồi đồng ý | Mục nhạy cảm bị xoá mềm, mục thường còn, consent có `revoked_at` |
| M06 | Mục quá `expires_at` | Job `expire_memory` xoá cứng, mục còn hạn giữ nguyên |
| M07 | Giá trị chứa toạ độ chính xác | Bị chặn; DB + trace không có toạ độ ≥ 3 chữ số thập phân (`scan_coords.scan_text`) |

Kết quả 23/11: **7/7 pass, leak = 0, recall = 1**. Bộ chấm đã được thử ngược: cho `memory_read` bỏ lọc `user_id`
thì M04 trượt với leak = 9.

Giới hạn: eval này không đo planner có *dùng đúng* sở thích trong lịch trình hay không (cần LLM thật); phần đó xem
trong eval UC-02 khi hồ sơ có `user_memory`.
