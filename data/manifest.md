# Manifest dữ liệu Huế v1

Lập manifest: 09/11/2026.
Đây là kiểm kê dữ liệu đã có, không phải ngày thu thập lại hoặc khảo sát thực địa.

## Quy ước

- Đường dẫn trong các bảng tính từ `data/destinations/hue/`.
- CSV đếm bản ghi, không tính header.
- GeoJSON đếm Feature; snapshot đếm element; provenance là một object JSON.
- SHA256 tính trên byte sau khi chuyển CRLF thành LF, giữ nguyên mọi byte khác.
  Quy ước này tránh khác hash giữa checkout Windows và Linux.
- Ngày xác minh, ngày lấy nguồn và thời điểm bản đồ cập nhật là các khái niệm khác nhau.

## Danh mục

| File | Nguồn | Giấy phép/quyền sử dụng | Ngày lấy hoặc tính theo tài liệu hiện có | Số bản ghi | Script tạo |
|---|---|---|---|---|---|
| poi.csv | OSM, Wikivoyage; nguồn giá theo từng trường trong sources_licenses.csv | ODbL-1.0 và CC-BY-SA-4.0 theo từng dòng; giá là dữ kiện trích dẫn | 25/10/2026 theo data/README.md; verified_at 2026-10-25 | 30 POI: 15 attraction, 10 food, 5 lodging | scripts/prepare_hue_data.py; bổ sung thủ công 3 giá, nguồn giá và tag riverside có nguồn sau đó |
| restricted_zones.geojson | Polygon OSM landuse=military | ODbL-1.0 | 25/10/2026 theo data/README.md; verified_at 2026-10-25 | 5 Feature | scripts/prepare_hue_data.py |
| osm_snapshot.json | Trích xuất tuyển chọn từ Overpass/OSM | ODbL-1.0 | 25/10/2026 theo data/README.md | 31 element: 26 POI OSM và 5 vùng | scripts/prepare_hue_data.py, từ dữ liệu Overpass tải trước |
| travel_matrix.csv | OSRM, routing trên dữ liệu OSM | ODbL-1.0, dữ liệu dẫn xuất OSM | computed_at 2026-10-24T18:54:30+00:00 | 900 cặp có hướng, mode drive | scripts/build_travel_matrix.py |
| routing_provenance.json | Metadata lần lấy ma trận OSRM | Attribution OSM/OSRM; dữ liệu dẫn xuất OSM theo ODbL-1.0 | computed_at 2026-10-24T18:54:30+00:00 | 1 object; 30 sources, 30 destinations | scripts/build_travel_matrix.py |
| poi_images.csv | Wikimedia Commons, tác giả và link từng ảnh | CC0, Public domain, CC BY, CC BY-SA theo từng dòng | retrieved_at 2026-11-09 | 25 dòng ảnh POI cho web/public/poi | P4 chọn thủ công, ảnh quán ăn ghi illustrative=1 |

Thời điểm routing trên tương ứng 01:54:30 ngày 25/10/2026 tại Việt Nam.
Snapshot OSM có `timestamp_osm_base=2026-06-01T08:52:28Z`;
không coi ngày tải 25/10 là ngày bản đồ được cập nhật.

## SHA256 — chuẩn xuống dòng LF

| File | SHA256 |
|---|---|
| osm_snapshot.json | e2b86d2e4cc6160ac67438affbfd752aacd11ccb53decf87d49318fc6c89fdc4 |
| poi_images.csv | 9cf24d9b05bad0ae8c47379cd8c23d8fea087467f50cd6a8aa591464f3b1b60e |
| poi.csv | da52d3e1818bba690e51d6da3144eb920b11c3de66a45b4abb599ca479324faf |
| restricted_zones.geojson | b90942a95adb6c3743a749b98b5456b089a0bcd8de4f45d993d1d6fe739e2920 |
| routing_provenance.json | 0a1b4bb9ff94a4843c0b5fab65ca3368e7b7bf5cfc0d97a3aded108d68d823db |
| travel_matrix.csv | 8f9cf8ad2557e3239231551f6ea239a75bf13c43bfa72e46a005359c2a33dd2e |

## Nguồn và attribution

- © OpenStreetMap contributors:
  https://www.openstreetmap.org/copyright
- ODbL 1.0:
  https://opendatacommons.org/licenses/odbl/1-0/
- Overpass dùng trong lần thu thập:
  https://overpass.kumi.systems/api/interpreter
- Wikivoyage contributors, bản Hue đã lưu:
  https://en.wikivoyage.org/w/index.php?title=Hue&oldid=5384053
- CC BY-SA 4.0:
  https://creativecommons.org/licenses/by-sa/4.0/
- OSRM endpoint:
  https://router.project-osrm.org
- Nguồn từng POI, từng vùng và từng trường giá:
  `data/sources_licenses.csv`.

Giữ giấy phép/attribution theo từng nguồn, không tự gán một giấy phép
chung cho toàn bộ nội dung tổng hợp. Trích dẫn dữ kiện giá không đồng
nghĩa có quyền tái sử dụng toàn bài báo.

## Chất lượng và giới hạn

- Checker hiện báo 30 POI hợp lệ; 22 POI chưa có giờ, 27 POI chưa có giá.
- Các giá chưa biết giữ NULL, không coi là miễn phí.
- Ba giá đã có nguồn trích dẫn trong sources_licenses.csv;
  ticket lập manifest này chưa kiểm chứng lại giá trực tuyến.
- Thiếu giá khiến tổng chi phí chuyến đi có thể chưa đầy đủ.
- Vùng quân sự lấy từ OSM là policy loại khỏi gợi ý,
  không phải xác nhận hạn chế pháp lý chính thức.
- Kiểm vùng hiện xét điểm POI, không chứng minh toàn tuyến tránh vùng.
- Ma trận chỉ có drive, không phải walk/bike, không có traffic realtime
  và không xác nhận vị trí cổng vào.

## Cache và tái tạo

`get_travel_time` đọc ma trận đã nạp vào DB từ travel_matrix.csv,
không gọi OSRM trong mỗi lượt demo. Phần tra thời gian di chuyển
hoạt động offline; điều này không có nghĩa toàn bộ app/LLM hoạt động offline.

Không chạy lại script thu thập chỉ để kiểm thử manifest.
prepare_hue_data.py hiện không tái tạo phần bổ sung thủ công:
chạy lại sẽ mất 3 giá, các dòng nguồn giá và tag riverside bổ sung.
Nếu chủ động tái tạo, phải bảo toàn các bổ sung có nguồn,
kiểm tra lại dữ liệu và cập nhật manifest/hash.

---

## Nguồn bổ sung cho W8-P2-2 · chính sách mùa lũ Huế

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

## Ghi chú bản bàn giao tổng hợp

Bản xuất này ghép kiểm kê W8-P2-3 với nguồn policy W8-P2-2, giữ cả hai nội dung. Hash poi.csv đã cập nhật sau tag riverside; bốn file còn lại giữ nguyên byte gốc. Không merge/reset/sửa các nhánh Git nguồn và không chạy lại script chuẩn bị dữ liệu.
