# Dữ liệu Huế · P2

Đối chiếu nguồn: 25/10/2026. **Không phải dữ liệu khảo sát thực địa, không phải chứng nhận giá/giờ hiện tại.**

## Nội dung và nguồn
| File | Nội dung | Quyền sử dụng / nguồn |
|---|---|---|
| `destinations/hue/poi.csv` | 30 POI: 15 attraction, 10 food, 5 lodging; 17 cột theo POI | 4 bản ghi Wikivoyage, 26 OSM; license theo từng dòng |
| `destinations/hue/restricted_zones.geojson` | 5 polygon gốc OSM `landuse=military` | © OpenStreetMap contributors, ODbL-1.0 |
| `destinations/hue/osm_snapshot.json` | Trích xuất yếu tố nguồn dùng để tái tạo | © OpenStreetMap contributors, ODbL-1.0 |
| `destinations/hue/travel_matrix.csv` | 900 cặp có hướng, **drive**; gồm 30 cặp cùng điểm | OSRM, routing trên OSM; dữ liệu dẫn xuất ODbL |
| `destinations/hue/routing_provenance.json` | Endpoint, thời điểm, profile, snap points, số cặp thiếu | Cùng nguồn ma trận |
| `sources_licenses.csv` | 35 dòng attribution/source/license/date tương ứng POI + vùng | Không thay thế điều khoản giấy phép gốc |

### Attribution và license
- **© OpenStreetMap contributors**, https://www.openstreetmap.org/copyright ; dữ liệu OSM/trích xuất/vùng
  và dữ liệu routing dẫn xuất được cung cấp theo **Open Database License 1.0**:
  https://opendatacommons.org/licenses/odbl/1-0/ . Giữ attribution và nghĩa vụ share-alike khi phân phối database dẫn xuất.
- **Wikivoyage contributors, “Hue”**, revision
  https://en.wikivoyage.org/w/index.php?title=Hue&oldid=5384053 ; **CC BY-SA 4.0**:
  https://creativecommons.org/licenses/by-sa/4.0/ . Các dòng Thiên Mụ/Đại Nội/Tự Đức/Khải Định được tuyển chọn,
  chuẩn hoá tên/ID và chuyển thành CSV; phần chuyển đổi các dòng này giữ CC BY-SA 4.0.
- Giữ các nhãn quyền riêng theo nguồn, không xem giấy phép code repo là giấy phép cho dữ liệu.
  Các nguồn không xác nhận/ủng hộ ứng dụng. Nếu phát hành database tổng hợp bên ngoài lớp học,
  cần kiểm tra cách phân phối/tách nguồn và nghĩa vụ của cả hai giấy phép; đây không phải tư vấn pháp lý.
- Không sao chép ảnh, review người dùng, số điện thoại/email/cá nhân từ dữ liệu trả về.

## Cách thu thập / chuyển đổi
- Overpass đã dùng: `https://overpass.kumi.systems/api/interpreter`, GET với query dạng dưới.
  Snapshot báo `timestamp_osm_base=2026-06-01T08:52:28Z`; ngày tải/đối chiếu là 25/10/2026.
  **Không đồng nhất ngày đối chiếu với ngày bản đồ cập nhật**. Đây là hạn chế freshness cần báo nhóm.
- Query tuyển chọn (không chạy trong runtime):
```text
[out:json][timeout:60];(
nwr["tourism"~"attraction|museum|hotel|guest_house"]["name"](16.34,107.50,16.52,107.68);
nwr["amenity"="restaurant"]["name"](16.43,107.53,16.49,107.64);
way["landuse"="military"](16.2,107.3,16.7,107.9);
way["access"="no"](16.43,107.53,16.49,107.64);
);out center geom;
```
- Chọn 26 POI và 5 polygon theo danh sách ID ổn định trong `scripts/prepare_hue_data.py`.
  Way POI dùng **tâm bounding box**, node dùng toạ độ nguồn, Wikivoyage dùng listing point.
  Đây **không phải cổng vào được xác minh**; OSRM snap lên mạng đường, có thể cho tuyến tiếp cận chưa phù hợp thực địa.
  Lần cache hiện tại có 3 snap point lệch >100m, lớn nhất khoảng 334m: không dùng để dẫn đường tới đúng cổng.
- `name_vi` ưu tiên name:vi rồi name; nếu nguồn không có dấu/tiếng Việt, không tự sửa thành dữ kiện mới.
  Làng hương Thủy Xuân dùng name do name:vi bất nhất. Tags history/food/lodging là nhãn tuyển chọn;
  vegetarian chỉ gắn khi OSM có diet:vegetarian=only hoặc diet:vegan=only.
- Không suy ra is_outdoor/min_age/walking_level/avg_visit_minutes từ tên. Tất cả giá hiện **NULL**.
  Chỉ giữ opening_hours thật có trong nguồn; một số cú pháp chưa hỗ trợ sẽ trả unverified.
  Điện Thái Hoà là điểm con Đại Nội: không coi là vé độc lập hoặc đếm như một lần ghé riêng khi xếp lịch.

## Vùng hạn chế
5 way nguồn: `1033694882`, `1172668060`, `1332926251`, `1346325479`, `1493416350`.
Giữ nguyên toạ độ polygon, không vẽ vòng tròn/tăng bán kính để đủ số lượng.
`zone_type=military` là cách ứng dụng loại vùng landuse=military khỏi gợi ý du lịch, **không phải quyết định cấm
chính thức**, không khẳng định có cảnh báo đang có hiệu lực. active_from/active_to=NULL vì nguồn không có ngày;
policy thận trọng coi vùng này cần tránh khi không có giới hạn thời gian. Không đầy đủ mọi vùng nguy hiểm ở Huế.
Validator chỉ xét **điểm POI nằm trong vùng**, không xét giao cắt toàn bộ tuyến đường vì ma trận không lưu route geometry.

## Nạp và kiểm tra (PowerShell, trong repo)
```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.check_destination
# Chọn DB mới, KHÔNG dùng init trên DB chuyến đi cần giữ.
$env:DB_PATH = Join-Path $env:TEMP ("hue-p2-" + [guid]::NewGuid().ToString("N") + ".db")
.\.venv\Scripts\python.exe -X utf8 -m agent.db.init
.\.venv\Scripts\python.exe -X utf8 scripts/load_destination.py hue --complete
```
Loader dùng repo/DB_PATH, kiểm toàn bộ file trước khi ghi, 1 transaction, upsert, không xoá POI cũ/trips.
Nếu từng dùng ID underscore cũ, nạp vào DB mới hoặc thống nhất migration với lead (upsert không tự xoá mã cũ).

## Tái tạo (chỉ khi cần, có thể ghi đè file data)
```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.prepare_hue_data --osm-input data/destinations/hue/osm_snapshot.json
# Lệnh dưới gọi mạng OSRM công khai: timeout 10s, tối đa 2 retry, không cần key.
.\.venv\Scripts\python.exe -X utf8 -m scripts.build_travel_matrix
```
Không tự chạy lại API routing trong mỗi request/demo; cache CSV/DB hoạt động offline.
Ma trận ceil(seconds/60), ceil(metres), profile driving; không traffic realtime, không walking/bike,
không mặc định đối xứng. OSRM trả null → không tạo dòng, ghi missing_pairs; không thay bằng thời gian ước đoán.
