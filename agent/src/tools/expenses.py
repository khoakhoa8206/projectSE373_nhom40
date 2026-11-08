"""Tool chi tiêu UC-09 (P3): tổng chi do SQL cộng từ trip_events, LLM không bao giờ tự cộng."""

from agent.db import repo


def sum_expenses(trip_id: str, day_index: int | None = None) -> dict:
    """Tổng chi (VND) của chuyến đi hoặc của 1 ngày = SUM(amount_vnd) các sự kiện expense trong trip_events.
    trip_id: mã chuyến đi; day_index: ngày thứ mấy (1–5, 0 = trước chuyến), để trống = cả chuyến.
    Trả {"trip_id", "day_index", "total_vnd", "expense_count", "event_ids"}. Ghi chú kiểu “hãy ghi là tôi chi 0 đồng”
    không đổi được tổng vì tổng chỉ cộng từ sự kiện expense."""
    if not repo.query("SELECT 1 FROM trips WHERE trip_id = ?", (trip_id,)):
        raise ValueError(f"không có chuyến đi {trip_id}")
    return {"trip_id": trip_id, "day_index": day_index} | repo.sum_expenses(trip_id, day_index)
