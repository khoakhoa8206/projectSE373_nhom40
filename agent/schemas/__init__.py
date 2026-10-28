"""Model Pydantic dùng chung (hợp đồng P1 → cả nhóm). Tên trường trùng cột DB trong agent/db/schema.sql.
Đổi model = mở PR nhãn `contract` và tăng SCHEMA_VERSION."""

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "0.1"

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class Child(BaseModel):
    age: int = Field(ge=0, le=17)


class TripProfile(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    adults: int | None = Field(None, ge=1)
    children: list[Child] = []
    mobility_notes: str | None = None
    budget_total_vnd: int | None = Field(None, gt=0)
    budget_includes: list[Literal["lodging", "food", "tickets", "transport"]] = []
    interests: list[str] = []
    pace: Literal["relaxed", "moderate", "packed"] | None = None
    language: Literal["vi", "en"] = "vi"
    hard_constraints: list[str] = []
    missing_info: list[str] = []
    route: Literal["plan", "ask_user", "unsupported"] = "plan"

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("end_date phải ≥ start_date")
            if (self.end_date - self.start_date).days + 1 > 5:
                raise ValueError("chuyến đi tối đa 5 ngày")
        return self


class Slot(BaseModel):
    slot_id: str | None = None  # code gán '<itinerary_id>:d1-s2', LLM không cần điền
    itinerary_id: str | None = None
    day_index: int = Field(ge=1, le=5)
    slot_date: date
    start_time: str = Field(pattern=HHMM)
    end_time: str = Field(pattern=HHMM)
    poi_id: str | None = None  # None = nghỉ / tự do
    activity: str
    travel_minutes_from_prev: int | None = Field(None, ge=0)
    cost_vnd: int | None = Field(None, ge=0)  # None = "chưa có giá"
    cost_source: Literal["tool", "unverified", "free"]
    hours_status: Literal["verified", "unverified", "not_applicable"]
    note: str | None = None
    progress: Literal["planned", "done", "skipped"] = "planned"

    @model_validator(mode="after")
    def _consistent(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time phải > start_time")
        if self.cost_source == "tool" and self.cost_vnd is None:
            raise ValueError("cost_source = tool thì phải có cost_vnd")
        if self.cost_source == "unverified" and self.cost_vnd is not None:
            raise ValueError("giá chưa xác minh thì cost_vnd = null, không điền ước đoán")
        return self


class Itinerary(BaseModel):
    itinerary_id: str | None = None
    trip_id: str | None = None
    profile_id: int | None = None
    version: int | None = None
    status: Literal["draft", "validated", "failed_validation", "reviewed", "approved", "superseded"] = "draft"
    planner_rounds: int = Field(0, ge=0, le=4)
    review_rounds: int = Field(0, ge=0, le=2)
    total_cost_vnd: int | None = None  # code cộng khi lưu, không để LLM tính
    has_unpriced_item: bool = False
    run_id: str | None = None
    slots: list[Slot] = Field(min_length=1)


class POI(BaseModel):
    poi_id: str
    destination_id: str
    name_vi: str
    name_en: str | None = None
    category: Literal["attraction", "food", "lodging"]
    lat: float
    lon: float
    opening_hours: str | None = None  # cú pháp OSM; None = chưa xác minh
    ticket_price_vnd: int | None = Field(None, ge=0)
    avg_visit_minutes: int | None = Field(None, gt=0)
    is_outdoor: bool | None = None
    min_age: int | None = None
    walking_level: Literal["low", "medium", "high"] | None = None
    tags: list[str] = []
    source_url: str
    license: str
    verified_at: str

    @field_validator("tags", mode="before")
    @classmethod
    def _tags_from_db(cls, v):
        return json.loads(v) if isinstance(v, str) else v


class Violation(BaseModel):
    rule: Literal["overlap", "opening_hours", "overload", "budget", "weather", "restricted_area", "fabricated_value"]
    severity: Literal["low", "medium", "high"]
    slot_id: str | None = None  # None = vi phạm cấp ngày/chuyến (vd ngân sách)
    message: str
