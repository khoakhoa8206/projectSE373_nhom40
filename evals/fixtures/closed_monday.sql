-- C04 · POI đóng cửa thứ Hai. Dữ liệu HƯ CẤU, chỉ chạy trên DB tạm của case:
-- evals/run.py chạy file này SAU khi scripts/load_destination.py nạp dữ liệu Huế.
-- Đại Nội được đổi thành nghỉ thứ Hai để kiểm agent không xếp Đại Nội vào thứ Hai 30/11/2026.
-- Cần P2 dùng poi_id 'hue-dai-noi' (như tests/conftest.py); nếu không khớp, scorer báo "fixture chưa có tác dụng".
UPDATE pois
   SET opening_hours = 'Tu-Su 07:00-17:30; Mo off',
       source_url = 'fixture://evals/fixtures/closed_monday.sql',
       license = 'hư cấu – chỉ dùng cho eval',
       verified_at = '2026-10-24'
 WHERE poi_id = 'hue-dai-noi';
