# Giao diện mới trên agent thật (P4 Phase 2)

Thư mục này ghép hai phần: code của nhóm từ `Prj/ghep-thu` (mọi nhánh W8/W9 của P1, P3, P4, kèm 3 sửa lỗi khi ghép) và giao diện mới trong `web/`. `fullstack/api.py` chỉ thêm các route `/api/ui/*` để hiển thị, phần lập lịch, duyệt, bộ nhớ, thuyết minh, nhật ký đều đi qua API thật. Chưa push lên đâu. Bản demo cũ nằm ở `Prj/backup-app-demo`.

## Chạy

Mở terminal tại thư mục này:

```bash
.venv/Scripts/python run.py           # giữ dữ liệu cũ
.venv/Scripts/python run.py --reset   # xoá dữ liệu, tạo lại 3 tài khoản demo
```

Mở http://localhost:5173. Máy mới thì cài trước: `python -m venv .venv`, `.venv/Scripts/pip install -r requirements.txt`, `npm --prefix web ci`. Lần đầu sẽ tải model embedding khoảng 220 MB nếu chưa có `.fastembed/`.

Có key thật: tạo file `.env` với `LLM_API_KEY=...` rồi chạy lại. Không commit `.env`.

## Cái gì thật, cái gì chưa

| Phần | Không có key | Có key |
|---|---|---|
| UC-02 lập lịch | Planner giả; tool, validator, checkpoint, duyệt là thật | LLM thật (chưa thử trên máy này) |
| UC-03 thuyết minh | Báo cần key; RAG thật đã dựng | LLM thật (chưa thử) |
| UC-09 nhật ký | Ghi sự kiện được; tóm tắt cần key | LLM thật (chưa thử) |
| UC-07 bộ nhớ, tắt/bật rồi chạy tiếp | Thật | Thật |
| UC-11 kiểm chứng | Thật, tách claim bằng regex | Thêm LLM ở trang Kiểm chứng |
| UC-01 hội thoại | Chưa có, P2 chưa có nhánh W8/W9. Mục "Hoặc kể bằng lời" đọc bằng luật, thiếu thông tin thì báo điền form | Như bên trái |
| UC-06 review | Phase 3, tab Review tự ẩn khi chưa có dữ liệu | Như bên trái |

## 3 tài khoản demo (hư cấu, đăng nhập một chạm)

| Tài khoản | Có sẵn |
|---|---|
| Nguyễn Thu Hà | Chuyến 3 ngày đã duyệt, vài sự kiện nhật ký, bộ nhớ |
| Trần Quang Minh | Lịch trình đang chờ duyệt, dùng để thử tắt/bật backend |
| Emma Carter | Chuyến 2 ngày tiếng Anh đã duyệt |

Các chuyến có sẵn do planner giả tạo, kể cả khi đã có key, để không tốn token.

**Thử tắt rồi bật lại:** đăng nhập Minh, mở chuyến đang chờ duyệt, Ctrl+C ở terminal, chạy lại `run.py` không có `--reset`, tải lại trang rồi bấm Duyệt.

## Ảnh

Ảnh lấy từ Wikimedia Commons, chỉ giấy phép CC0, Public domain, CC BY, CC BY-SA. Tác giả và giấy phép ở `data/destinations/hue/poi_images.csv`, hiện ở trang "Nguồn ảnh và giấy phép". 10 quán ăn dùng ảnh minh hoạ món Huế và có ghi chú. 6 nơi chưa có ảnh được phép dùng thì để trống.
