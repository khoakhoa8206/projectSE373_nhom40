# Eval UC-02 (P3)

Chạy: `make eval` (= `python -m evals.run --uc UC-02`). Bộ chấm nằm trong `evals/`, agent không được đọc thư mục này.

## File

| File | Nội dung |
|---|---|
| `cases.jsonl` | 10 case. Trường theo hợp đồng P3 → P1 trong `AGENTS.md`: `case_id`, `profile` (TripProfile, ngày cụ thể), `weather_mode` (`normal` / `heavy_rain` / `timeout` / `abnormal`), `start_weekday` (`mon`…`sun`, khớp `profile.start_date`), `expect`, tuỳ chọn `fixture`. Thêm `title`, `source_request_id` (C08 ← R12, C09 ← R15 trong `evals/trip_requests.jsonl`) |
| `../fixtures/closed_monday.sql` | C04: Đại Nội nghỉ thứ Hai (hư cấu) |
| `../fixtures/missing_prices.sql` | C07: xoá giá mọi điểm tham quan có giá và Đại Nội (hư cấu) |
| `scorer.py` | `score(case, conn, run_id) -> {"passed": bool, "reasons": [str]}`, chỉ đọc DB |

Fixture chạy **sau** khi `scripts/load_destination.py hue` nạp dữ liệu thật vào DB tạm của case, nên chỉ sửa dòng có sẵn
theo `poi_id`/`category`, không chèn POI mới (POI mới sẽ thiếu dòng `travel_matrix`).

## 10 case

| Case | Kịch bản | Thời tiết | Fixture | Kỳ vọng chính |
|---|---|---|---|---|
| C01 | Ngân sách thoải mái, 3 ngày | normal | – | `validated`, mỗi ngày ≥ 2 điểm tham quan |
| C02 | 1,5 triệu cho 3 ngày, 2 người | normal | – | tổng ≤ ngân sách, hoặc `failed_validation` chỉ vì `budget` |
| C03 | Mưa lớn | heavy_rain | – | có ngày mưa lớn trong `weather_snapshots`; không slot ngoài trời > 120 phút ngày đó; có Đại Nội |
| C04 | POI đóng cửa thứ Hai (30/11/2026) | normal | closed_monday.sql | Đại Nội có trong lịch nhưng không vào thứ Hai |
| C05 | Bé 4 tuổi, nhịp relaxed | normal | – | không POI có `min_age` > 4, tag `hiking`, `walking_level` = high; ngưỡng relaxed |
| C06 | API thời tiết timeout | timeout | – | 0 `weather_snapshots`; tool báo “không có dự báo”; slot không giả định trời đẹp |
| C07 | Nhiều POI thiếu giá | normal | missing_prices.sql | Đại Nội có trong lịch với `cost_vnd` NULL, `cost_source = 'unverified'` |
| C08 | Nhóm 6 người (= R12) | normal | – | giá = đơn giá × 6 người, ≥ 2 slot có giá |
| C09 | Chuyến 1 ngày (= R15) | normal | – | 1 ngày, ≥ 2 điểm tham quan |
| C10 | 48 °C bất thường | abnormal | – | snapshot có `is_anomalous = 1`; không dùng dữ liệu đó để xếp lịch |

## Quy ước scorer dùng (cần khớp validator P2 và tool P4)

| Mục | Quy ước |
|---|---|
| Giá slot | `cost_vnd` = `ticket_price_vnd` × (`adults` + số trẻ em). Giá 0 → `cost_source = 'free'`. Giá NULL → `cost_vnd` NULL, `cost_source = 'unverified'`. POI lưu trú: chỉ kiểm có/không có giá (đơn giá lưu trú chưa chốt) |
| Giờ mở cửa | `opening_hours` NULL → `hours_status = 'unverified'` (ghi `verified` = bịa). Slot phải nằm trọn trong khung giờ của đúng thứ (cú pháp OSM). `not_applicable` chỉ cho slot không gắn POI hoặc lưu trú |
| Di chuyển | `travel_minutes_from_prev` ≥ `MIN(minutes)` của cặp POI trong `travel_matrix` (mọi mode) − 2 phút; slot sau bắt đầu ≥ slot trước kết thúc + di chuyển |
| Quá tải | relaxed 360 phút / 3 điểm, moderate 480 / 5, packed 600 / 7 mỗi ngày (pace NULL → moderate); phút hoạt động = thời lượng slot + di chuyển giữa các slot |
| Mưa lớn | snapshot của run có `is_anomalous = 0` và (`condition = 'heavy_rain'` hoặc `precip_mm` ≥ 50); slot `is_outdoor = 1` dài > 120 phút ngày đó là vi phạm |
| Vùng hạn chế | toạ độ POI nằm trong `geometry` (GeoJSON Polygon/MultiPolygon/Feature hoặc `{"type": "Circle", "center": [lon, lat], "radius_m": …}`) còn hiệu lực ngày đó (`active_from/active_to`: NULL, `YYYY-MM-DD` hoặc `MM-DD`) |
| Đoàn khách | `min_age` > tuổi trẻ nhỏ nhất; `walking_level` vượt `expect.max_walking_level` (mặc định high, thành medium khi hồ sơ có “không leo”/“đi lại khó”); ăn chay → quán có tag `vegetarian`/`chay` |
| Trạng thái | `validated` mà scorer thấy vi phạm → “validator bỏ lọt”. `failed_validation` → mọi vi phạm scorer thấy phải có trong `validation_violations` với `resolved = 0` |
| Trace | có `tool_call` `get_weather_forecast` và `skill_use` `itinerary-planning` |

Ngưỡng nằm ở đầu `scorer.py`; nếu validator P2 chốt số khác, sửa cả hai cùng lúc.

## Phụ thuộc vào thành viên khác

- **P2:** dùng `poi_id` `hue-dai-noi` (như `tests/conftest.py`), nếu khác thì C03, C04, C07 trượt với lý do
  “fixture chưa có tác dụng” / “lịch thiếu hue-dai-noi”. `is_outdoor`, `min_age`, `walking_level` nên có giá trị cho POI
  tham quan; `check_fabrication` và `validate` dùng cùng quy ước giá, giờ, ngưỡng như bảng trên.
- **P4:** chế độ `heavy_rain` cho ít nhất 1 ngày trong 27–29/11/2026 có `precip_mm` ≥ 50 hoặc `condition = 'heavy_rain'`;
  `abnormal` trả giá trị phi lý và tool ghi `is_anomalous = 1`, `anomaly_reason`; `timeout` thì tool trả “không có dự báo”
  và không ghi `weather_snapshots`; provider ghi `mock_weather`.
- **P1:** `evals/run.py` truyền đúng `case`, kết nối DB của case và `run_id`.
