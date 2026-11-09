import { useState } from "react";
import type { Itinerary, Slot } from "../api";
import MapView, { DAY_COLORS } from "../MapView";

const money = (amount: number) => `${amount.toLocaleString("vi-VN")} đ`;

function SlotRow({ slot }: { slot: Slot }) {
  return <li className="slot">
    <div className="time">{slot.start_time}–{slot.end_time}</div>
    <div>
      <div className="title">{slot.name_vi ?? "Tự do / nghỉ"}</div>
      <p>{slot.activity}</p>
      <div className="tags">
        {slot.cost_vnd === null ? <span className="tag warn">Chưa có giá</span> : <span className="tag">{money(slot.cost_vnd)}</span>}
        {slot.hours_status === "unverified" && <span className="tag warn">Giờ mở cửa chưa xác minh</span>}
        {slot.travel_minutes_from_prev !== null && <span className="tag">{slot.travel_minutes_from_prev} phút di chuyển</span>}
      </div>
      {slot.note && <p className="muted small">{slot.note}</p>}
    </div>
  </li>;
}

export default function ItineraryPage({ itinerary }: { itinerary: Itinerary }) {
  const days = [...new Set(itinerary.slots.map((slot) => slot.day_index))].sort((a, b) => a - b);
  const [selected, setSelected] = useState(days[0]);
  const active = days.includes(selected) ? selected : days[0];
  const slots = itinerary.slots.filter((slot) => slot.day_index === active);
  const unknownTotal = itinerary.total_cost_vnd === null || itinerary.slots.every((slot) => slot.cost_vnd === null);
  const labels: Record<string, string> = {
    approved: "Đã được người dùng duyệt", validated: "Đã qua validator, chưa được người dùng duyệt",
    failed_validation: "Còn vi phạm — lịch chưa đạt kiểm tra", draft: "Bản nháp", superseded: "Bản cũ",
  };
  return <section className="itinerary phase2-itinerary">
    <h2>Lịch trình</h2>
    <p className={itinerary.status === "failed_validation" ? "warn" : "muted"}>
      {labels[itinerary.status] ?? itinerary.status} · {itinerary.planner_rounds}/4 vòng
    </p>
    <p>{unknownTotal
      ? <strong>Tổng chi phí chưa đầy đủ</strong>
      : <>Tổng các khoản đã biết: <strong>{money(itinerary.total_cost_vnd!)}</strong></>}
      {!unknownTotal && !!itinerary.has_unpriced_item && " · Tổng chi phí chưa đầy đủ"}
    </p>
    {itinerary.violations.length > 0 && <ul className="violations" aria-label="Vi phạm còn lại">
      {itinerary.violations.map((violation) => <li key={violation.violation_id}>[{violation.rule}] {violation.message}</li>)}
    </ul>}
    <div role="tablist" aria-label="Ngày tham quan" className="day-tabs">
      {days.map((day) => <button key={day} role="tab" aria-selected={day === active}
        id={`day-tab-${day}`} aria-controls={`day-panel-${day}`} onClick={() => setSelected(day)}>
        <span className="dot" style={{ background: DAY_COLORS[(day - 1) % DAY_COLORS.length] }} />Ngày {day}
      </button>)}
    </div>
    <div role="tabpanel" id={`day-panel-${active}`} aria-labelledby={`day-tab-${active}`}>
      <h3>{slots[0]?.slot_date}</h3>
      <ul className="slots-list">{slots.map((slot) => <SlotRow key={slot.slot_id} slot={slot} />)}</ul>
    </div>
    <MapView slots={itinerary.slots} />
    <p className="muted small">Đường nối thứ tự tham quan, không phải đường đi thực tế.</p>
    <ul className="map-legend" aria-label="Chú giải màu bản đồ">
      {days.map((day) => <li key={day}><span className="dot" style={{ background: DAY_COLORS[(day - 1) % DAY_COLORS.length] }} />Ngày {day}</li>)}
    </ul>
    <p className="muted small">Nguồn POI: © OpenStreetMap contributors (ODbL), Wikivoyage contributors (CC BY-SA 4.0).
      Dữ liệu còn thiếu giờ/giá, không phải cam kết an toàn hoặc đã đặt vé.</p>
  </section>;
}
