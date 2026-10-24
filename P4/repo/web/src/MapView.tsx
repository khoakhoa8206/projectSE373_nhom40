import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Slot } from "./api";

const HUE: L.LatLngTuple = [16.4637, 107.5909];
export const DAY_COLORS = ["#0f5f73", "#c2410c", "#7c3aed", "#15803d", "#be123c"];

/** Nội dung popup dựng bằng textContent: activity do LLM sinh, không được chèn thành HTML. */
function popup(s: Slot): HTMLElement {
  const div = document.createElement("div");
  for (const [tag, text] of [["b", `Ngày ${s.day_index} · ${s.start_time}–${s.end_time}`], ["div", s.name_vi ?? ""], ["div", s.activity]]) {
    div.appendChild(document.createElement(tag)).textContent = text;
  }
  return div;
}

/** Bản đồ OSM: marker đánh số theo thứ tự trong ngày + đường nối các điểm (mỗi ngày một màu). */
export default function MapView({ slots }: { slots: Slot[] }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    const m = L.map(el.current!).setView(HUE, 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    map.current = m;
    layer.current = L.layerGroup().addTo(m);
    return () => void m.remove();
  }, []);

  useEffect(() => {
    const group = layer.current!;
    group.clearLayers();
    const all: L.LatLngTuple[] = [];
    for (const day of new Set(slots.map((s) => s.day_index))) {
      const color = DAY_COLORS[(day - 1) % DAY_COLORS.length];
      const stops = slots.filter((s) => s.day_index === day && s.lat != null && s.lon != null);
      const pts = stops.map((s) => [s.lat!, s.lon!] as L.LatLngTuple);
      L.polyline(pts, { color, weight: 3, opacity: 0.7, dashArray: "6 6" }).addTo(group);
      stops.forEach((s, i) => {
        const icon = L.divIcon({ className: "pin", html: `<span style="background:${color}">${i + 1}</span>`, iconSize: [26, 26] });
        L.marker(pts[i], { icon, title: s.name_vi ?? s.activity }).bindPopup(popup(s)).addTo(group);
      });
      all.push(...pts);
    }
    if (all.length) map.current!.fitBounds(all, { padding: [30, 30], maxZoom: 15 });
  }, [slots]);

  return <div ref={el} className="map" role="region" aria-label="Bản đồ lịch trình" />;
}
