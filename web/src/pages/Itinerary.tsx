import { useState } from "react";
import type { Itinerary, Slot } from "../api";
import { poiName, t } from "../i18n";
import MapView, { DAY_COLORS } from "../MapView";
import { vnd as money } from "../ui";

function SlotRow({ slot }: { slot: Slot }) {
  return <li className="slot">
    <div className="time">{slot.start_time}–{slot.end_time}</div>
    <div>
      <div className="title">{poiName(slot) || t("Tự do / nghỉ", "Free time / rest")}</div>
      <p>{slot.activity}</p>
      <div className="tags">
        {slot.cost_vnd === null ? <span className="tag warn">{t("Chưa có giá", "No price yet")}</span> : <span className="tag">{money(slot.cost_vnd)}</span>}
        {slot.hours_status === "unverified" && <span className="tag warn">{t("Giờ mở cửa chưa xác minh", "Opening hours not verified")}</span>}
        {slot.travel_minutes_from_prev !== null && <span className="tag">{slot.travel_minutes_from_prev} {t("phút di chuyển", "min travel")}</span>}
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
    approved: t("Đã được người dùng duyệt", "Approved by the user"),
    validated: t("Đã qua validator, chưa được người dùng duyệt", "Passed the validator, not yet approved"),
    failed_validation: t("Còn vi phạm — lịch chưa đạt kiểm tra", "Violations remain — itinerary failed checks"),
    draft: t("Bản nháp", "Draft"), superseded: t("Bản cũ", "Superseded"),
  };
  return <section className="itinerary phase2-itinerary">
    <h2>{t("Lịch trình", "Itinerary")}</h2>
    <p className={itinerary.status === "failed_validation" ? "warn" : "muted"}>
      {labels[itinerary.status] ?? itinerary.status} · {itinerary.planner_rounds}/4 {t("vòng", "rounds")}
    </p>
    <p>{unknownTotal
      ? <strong>{t("Tổng chi phí chưa đầy đủ", "Total cost incomplete")}</strong>
      : <>{t("Tổng các khoản đã biết", "Total of known costs")}: <strong>{money(itinerary.total_cost_vnd!)}</strong></>}
      {!unknownTotal && !!itinerary.has_unpriced_item && ` · ${t("Tổng chi phí chưa đầy đủ", "Total cost incomplete")}`}
    </p>
    {itinerary.violations.length > 0 && <ul className="violations" aria-label={t("Vi phạm còn lại", "Remaining violations")}>
      {itinerary.violations.map((violation) => <li key={violation.violation_id}>[{violation.rule}] {violation.message}</li>)}
    </ul>}
    <div role="tablist" aria-label={t("Ngày tham quan", "Trip days")} className="day-tabs">
      {days.map((day) => <button key={day} role="tab" aria-selected={day === active}
        id={`day-tab-${day}`} aria-controls={`day-panel-${day}`} onClick={() => setSelected(day)}>
        <span className="dot" style={{ background: DAY_COLORS[(day - 1) % DAY_COLORS.length] }} />{t("Ngày", "Day")} {day}
      </button>)}
    </div>
    <div role="tabpanel" id={`day-panel-${active}`} aria-labelledby={`day-tab-${active}`}>
      <h3>{slots[0]?.slot_date}</h3>
      <ul className="slots-list">{slots.map((slot) => <SlotRow key={slot.slot_id} slot={slot} />)}</ul>
    </div>
    <MapView slots={itinerary.slots} pois={[]} />
    <p className="muted small">{t("Đường nối thứ tự tham quan, không phải đường đi thực tế.", "Lines show visiting order, not actual routes.")}</p>
    <ul className="map-legend" aria-label={t("Chú giải màu bản đồ", "Map colour legend")}>
      {days.map((day) => <li key={day}><span className="dot" style={{ background: DAY_COLORS[(day - 1) % DAY_COLORS.length] }} />{t("Ngày", "Day")} {day}</li>)}
    </ul>
    <p className="muted small">{t("Nguồn POI", "POI sources")}: © OpenStreetMap contributors (ODbL), Wikivoyage contributors (CC BY-SA 4.0).{" "}
      {t("Dữ liệu còn thiếu giờ/giá, không phải cam kết an toàn hoặc đã đặt vé.", "Some hours/prices are missing; this is not a safety guarantee or a booking.")}</p>
  </section>;
}
