# Nguồn bổ sung cho W8-P2-2 · chính sách mùa lũ Huế

Đối chiếu: **09/11/2026**. Đây là nguồn chính sách lập lịch, không phải dự báo thời tiết hay lệnh cấm thực địa.

## Mùa lũ chính vụ

- Cơ quan: **UBND thành phố Huế**.
- Văn bản: **Quyết định 3279/QĐ-UBND ngày 06/10/2026**, phê duyệt Kế hoạch phòng, chống thiên tai
  thành phố Huế giai đoạn 2026–2030.
- [Quyết định ký số](https://hue.gov.vn/Portals/0/Uploads/VBPL/Nam2026/Thang10/00.00.H57-3279-QD-UBND-2026-PL2_signed.pdf).
- [Kế hoạch kèm theo](https://hue.gov.vn/Portals/0/Uploads/VBPL/Nam2026/Thang10/00.00.H57-3279-QD-UBND-2026-PL3_signed.pdf),
  trang đánh số **5**, mục hệ thống sông Hương: “lũ chính vụ tập trung từ tháng 9 đến tháng 12”.
- Tháng dùng trong code: **9, 10, 11, 12**. Đây là chính vụ, **không phải** khẳng định ngoài các tháng này không có lũ;
  văn bản cũng nêu lũ tiểu mãn tháng 5–6 và các đợt trái mùa.
- Quyền sử dụng: dẫn nguồn văn bản hành chính; không gán CC/ODbL cho văn bản, không phân phối lại toàn bộ PDF.

### Cách áp dụng trong rule `weather`

Ngày thuộc tháng chính vụ **và** dự báo hợp lệ cho ngày đó là `heavy_rain` (hoặc `precip_mm >= 50`,
giữ cách nhận diện mưa lớn có sẵn của nhóm) → báo vi phạm từng slot ở POI Huế có `is_outdoor=true`
hoặc tag `river` / `riverside` / `boat_trip`, kể cả slot ngắn hơn 120 phút.
Không suy tag từ tên điểm hoặc chuỗi `activity`. Tags lấy từ dữ liệu POI (list hoặc JSON trong DB).
Không có dự báo hoặc forecast anomalous/no_forecast → không suy ra thời tiết tốt hay mưa lớn từ tháng.

Ngoài chính vụ vẫn giữ rule cũ: mưa lớn và tổng ngoài trời/điểm tham quan chưa rõ outdoor >120 phút/ngày thì lỗi.
Ngưỡng 50 mm, 120 phút và quyết định loại slot là **policy dự án**, không phải ngưỡng do văn bản UBND quy định.
Không thay các rule overload, budget, overlap, opening_hours hay restricted_area đã có.

## Nguồn tag `riverside`

- POI: `hue-chua-thien-mu`.
- Nguồn: [Vietnam Tourism · Vietnam Highlights · ngày 7](https://vietnam.travel/plan-your-trip/recommended-trip/vietnam-highlights/).
  Mô tả Thiên Mụ là “pagoda overlooking the Perfume River”.
- Tag `riverside` là nhãn tuyển chọn thận trọng từ vị trí ven sông trong nguồn; không khẳng định POI đang ngập,
  không xác nhận mọi khu vực của chùa đều ngoài trời và không tạo hoạt động đi thuyền mới.
- Lưu nguồn theo trường tại `sources_licenses.csv`, record `hue-chua-thien-mu#tags`, verified_at `2026-11-09`.
  Chỉ trích dữ kiện vị trí, không sao chép bài/ảnh hoặc nhận định có giấy phép mở.
- Giữ nguyên source_url/license/verified_at của bản ghi gốc vì các trường khác vẫn lấy từ nguồn cũ.
  Không sửa giá, giờ, tọa độ hay ma trận tuyến.

## Dấu vết thay đổi dữ liệu và ghép manifest v1

`W8-P2-3` có manifest kiểm kê 5 file và checker trên nhánh riêng; không mang code/test của ticket đó vào đây.
Khi merge cả hai PR, **giữ nguyên phần kiểm kê W8-P2-3 và nối thêm các mục nguồn ở trên**, không chọn bỏ một bên.
Do bổ sung duy nhất tag Thiên Mụ, cập nhật SHA256 của `poi.csv` trong bảng v1 thành:

| File (từ data/destinations/hue/) | Số bản ghi | SHA256 sau CRLF→LF |
|---|---|---|
| poi.csv | 30 | da52d3e1818bba690e51d6da3144eb920b11c3de66a45b4abb599ca479324faf |

Các file vùng/snapshot/routing không thay đổi. Thay tag thủ công có nguồn;
**không chạy lại `prepare_hue_data.py`** vì sẽ mất tag bổ sung và ba giá đã nhập kèm nguồn.
`get_travel_time` vẫn chỉ đọc cache, không cần mạng lúc demo.
