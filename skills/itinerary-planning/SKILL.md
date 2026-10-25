---
name: itinerary-planning
description: Xếp lịch trình nhiều ngày ở Huế từ TripProfile, chỉ dùng dữ liệu lấy từ tool.
---

# itinerary-planning

## Khi dùng / không dùng
- Dùng ở node `plan` của UC-02, sau khi có TripProfile hợp lệ cho Huế; cả lần đầu và khi sửa violations.
- Không dùng để hỏi intake tự do (UC-01 Phase 2), thuyết minh lịch sử, đặt phòng/vé, tư vấn khẩn cấp,
  duyệt lịch trình thay người dùng hoặc đọc bộ chấm. Không chạy shell/script, không đọc `evals/`.

## Input / output
- Input: `profile`, `previous_itinerary`, `violations_to_fix`, `verified_context` (ứng viên/thời tiết đã lấy qua tool).
- Output: Itinerary có `slots`, mỗi slot gồm day_index, slot_date (ISO), start_time/end_time (HH:MM), poi_id,
  activity, travel_minutes_from_prev, cost_vnd, cost_source, hours_status, note. Không cần ID/trạng thái/tổng giá;
  code tự gán ID, cộng tiền và kiểm nghiệp vụ. Nộp bằng `submit_result` theo JSON Schema tool.
- Thời gian theo giờ địa phương Huế (UTC+7), ngày thứ 1 là start_date, tối đa 5 ngày theo model chung.

## Quy trình
1. Đọc hồ sơ: ngày, số người/tuổi trẻ, mobility, ngân sách/phạm vi chi, pace, interests, hard_constraints.
   Không tự đoán thông tin thiếu hoặc bỏ qua ràng buộc cứng. Điểm đến duy nhất Phase 1 là Huế.
2. Dùng `search_poi` theo loại và tags (AND). Tuổi = trẻ nhỏ nhất; mobility cần ít đi bộ → low.
   Nếu metadata thiếu nên không có kết quả: nói rõ không xác nhận được độ phù hợp, không tự gắn low/min_age=0.
   Interests là xếp hạng ưu tiên, không phải lý do bịa tags. Dùng `get_poi` xem thông tin/nguồn đầy đủ.
3. Lấy `get_weather_forecast` mỗi ngày. Timeout, no_forecast hoặc anomalous: ghi “không có dự báo”,
   không kết luận trời đẹp. Snapshot lỗi không phải dữ kiện để lập lịch an toàn.
4. Với mỗi điểm, lấy `get_opening_hours(poi_id, date)`. `open_intervals=[]` là đóng; `null` là chưa biết;
   phút tính từ 00:00. Giờ đóng/mở và nghỉ trưa đều phải chứa TRỌN slot. Không tự hiểu cú pháp chưa hỗ trợ.
5. Với mỗi cặp điểm liên tiếp cùng ngày, lấy `get_travel_time` đúng hướng và mode.
   Cache hiện chỉ drive: không gọi là đi bộ/xe đạp; unavailable không phải 0. Thay điểm hoặc giảm số điểm nếu thiếu tuyến.
   Chừa travel sau slot trước; slot đầu ngày null/0. Chèn bữa ăn/nghỉ; không cho slot vượt ngày hay chồng giờ.
6. Xếp vừa pace: relaxed ≤6h và ≤3 điểm tham quan, moderate ≤8h và ≤5 điểm, packed ≤10h và ≤7 điểm
   (hoạt động+travel/ngày). Ngưỡng đi bộ có dữ liệu 3/6/10 km; đây là policy dự án, không phải khuyến cáo sức khoẻ.
   Mưa lớn: tổng thời gian ở điểm ngoài trời + điểm tham quan chưa rõ indoor/outdoor ≤120 phút/ngày,
   không lách bằng chia nhỏ slot.
   Không lặp POI hoặc xếp Đại Nội cùng các điểm con như những vé/chuyến riêng chỉ để đủ lịch.
7. Giá chưa biết hoặc đơn vị vé/nhóm chưa tương thích: null/unverified. `free` chỉ khi nguồn xác nhận 0.
   Giá vé dữ liệu là giá/người: cost_vnd = ticket_price_vnd × số người trong đoàn (code tính lại khi nộp);
   không chế mức giảm trẻ em, không bịa giá bữa ăn/phòng. `total_cost_vnd` chỉ là tổng khoản biết giá;
   chưa đủ giá không được tuyên bố ngân sách toàn chuyến đã được xác nhận.
8. Chưa có avg_visit_minutes thì thời lượng là phân bổ dự kiến của planner, không phải giờ tham quan xác minh.
   `note` phải nói rõ giờ/giá/khả năng đi bộ chưa xác minh. Slot nghỉ: poi_id=null, cost_vnd=null,
   cost_source=unverified, hours_status=not_applicable; không gắn nghỉ với một POI bịa.
9. Nếu có violations: sửa nguyên nhân (giờ/địa điểm/quá tải/giá/route), không che lỗi bằng đổi nhãn.
   Ưu tiên sửa slot bị lỗi, giữ điểm/ngày/slot đã đúng; không xây lại toàn lịch ở mỗi vòng sửa.
   `verified_context.previous_facts` đã chứa kết quả giờ/travel cho bản trước, kể cả unknown: dùng lại,
   không hỏi lại với hy vọng unknown tự thành known. Chỉ tra cứu thêm khi thật sự thay điểm/chặng/ngày.
   Code kiểm restricted_area sau khi nộp; nếu bị chặn, thay điểm. Vùng OSM không phải dữ liệu pháp lý đầy đủ,
   cache ma trận không có hình học tuyến, nên không cam kết mọi đoạn đường đều tránh vùng hạn chế.
10. Nộp bản có căn cứ; code quyết định validated/failed_validation, tối đa 4 vòng, chọn bản ít lỗi nhất.
    Mỗi vòng có tối đa15lượt LLM: gom tất cả yêu cầu tool độc lập vào cùng một lượt, không tuần tự hỏi từng chặng.
    Hai lượt cuối harness yêu cầu `submit_result`: nộp bản bảo thủ, không bịa để đủ trường/số điểm.
    Nếu vòng sửa vẫn hết lượt, hệ thống giữ bản tốt nhất đã kiểm cùng lỗi còn lại; không gọi đó là lịch thành công.
    Không khẳng định “đã đặt”, “chắc chắn an toàn”, “đã duyệt” hoặc “đủ ngân sách” khi chưa có bằng chứng.

## Ví dụ nhãn dữ liệu
Tool trả giờ/giá Thiên Mụ là null → slot dự kiến:
```json
{"day_index":1,"slot_date":"2026-11-27","start_time":"09:00","end_time":"10:00",
 "poi_id":"hue-chua-thien-mu","activity":"Tham quan dự kiến",
 "travel_minutes_from_prev":null,"cost_vnd":null,"cost_source":"unverified","hours_status":"unverified",
 "note":"Chưa xác minh giờ/giá và điều kiện đi bộ; 60 phút là thời lượng dự kiến."}
```
Đây là ví dụ schema, không phải lịch bảo đảm phù hợp mọi hồ sơ hoặc dữ kiện giờ/giá.

## Final check
- Mỗi ngày trong hồ sơ có slot, ngày/thứ tự đúng, có ăn/nghỉ và đủ travel có nguồn?
- POI thật, đúng nguồn; tất cả số liệu giá/travel khớp tool, null không biến thành 0?
- Giờ mở cửa chứa slot, kể giờ nghỉ trưa; unknown được ghi chú?
- Pace/mưa lớn/nhu cầu trẻ và mobility có được tôn trọng, không giả định metadata còn thiếu?
- Có sửa violations cụ thể, không gọi dữ liệu bên ngoài hay bộ chấm?
- Không đặt trạng thái/tổng tiền thay code, không hứa mức độ xác minh chưa đạt?
