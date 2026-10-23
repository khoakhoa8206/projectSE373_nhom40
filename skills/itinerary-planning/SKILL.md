---
name: itinerary-planning
description: Xếp lịch trình nhiều ngày ở Huế từ TripProfile, chỉ dùng dữ liệu lấy từ tool.
---

# itinerary-planning

> Bản nháp của P1 để agent loop chạy được. P2 viết lại đủ contract (khi nào dùng, đầu vào/đầu ra, các bước,
> ràng buộc, ví dụ, final check) theo nhiệm vụ P2-5. Không chứa script chạy lệnh.

1. Lọc POI bằng `search_poi` theo sở thích, tuổi trẻ em, mức đi bộ.
2. Với từng ngày: lấy thời tiết (`get_weather_forecast`), giờ mở cửa (`get_opening_hours`), thời gian di chuyển giữa
   các POI liền nhau (`get_travel_time`).
3. Xếp slot theo ngày, không chồng giờ, chừa thời gian di chuyển.
4. Thiếu dữ liệu thì ghi nhãn chưa xác minh (`hours_status` / `cost_source` = `unverified`), tuyệt đối không đoán
   giờ, giá hay thời tiết.
