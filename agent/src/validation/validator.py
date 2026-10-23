"""Validator UC-02 (owner: P2, nhiệm vụ P2-4). Hàm thuần: không gọi LLM, không ghi DB.
Bản stub giữ chữ ký hợp đồng để graph chạy được; P2 thay bằng 4 rule: overlap, opening_hours, budget, weather."""

from agent.schemas import Itinerary, TripProfile, Violation


def validate(itinerary: Itinerary, profile: TripProfile, weather: dict) -> list[Violation]:
    """weather: {forecast_date: dòng weather_snapshots} do tool thời tiết ghi trong lượt chạy hiện tại."""
    return []


def check_fabrication(itinerary: Itinerary) -> list[Violation]:
    """Mọi poi_id, cost_vnd, giờ trong slot phải khớp dữ liệu tool; sai thì Violation(rule='fabricated_value').
    Nhớ bắt cả poi_id không có trong bảng pois (nếu lọt tới finalize sẽ lỗi khoá ngoại)."""
    return []
