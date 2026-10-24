-- C07 · Nhiều POI thiếu giá. Dữ liệu HƯ CẤU, chỉ chạy trên DB tạm của case (sau khi nạp dữ liệu Huế).
-- Xoá giá của mọi điểm tham quan có giá và của Đại Nội: agent phải ghi cost_vnd = NULL, cost_source = 'unverified',
-- itineraries.has_unpriced_item = 1, không ước đoán giá.
UPDATE pois
   SET ticket_price_vnd = NULL
 WHERE category = 'attraction' AND (ticket_price_vnd > 0 OR poi_id = 'hue-dai-noi');
