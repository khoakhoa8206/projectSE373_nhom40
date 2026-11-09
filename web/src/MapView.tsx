import L from "leaflet";
import { useEffect, useRef } from "react";
import type { Poi, Slot } from "./api";
import type { Coords } from "./location";

const HUE: L.LatLngTuple = [16.4637, 107.5909];
export const DAY_COLORS = ["#0f5f73", "#c2410c", "#7c3aed", "#15803d", "#be123c"];
const POI_COLORS = { attraction: "#475569", food: "#b45309", lodging: "#0369a1" };

/** Nội dung popup dựng bằng textContent: activity do LLM sinh, không được chèn thành HTML. */
function popup(s: Slot): HTMLElement {
  const div = document.createElement("div");
  for (const [tag, text] of [["b", `Ngày ${s.day_index} · ${s.start_time}–${s.end_time}`], ["div", s.name_vi ?? ""], ["div", s.activity]]) {
    div.appendChild(document.createElement(tag)).textContent = text;
  }
  return div;
}

/** Bản đồ OSM: mọi POI + marker đánh số theo thứ tự trong ngày + đường nối các điểm (mỗi ngày một màu) + vị trí người dùng nếu có. */
export default function MapView({ slots, pois, here }: { slots: Slot[]; pois: Poi[]; here?: Coords | null }) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const hereLayer = useRef<L.LayerGroup | null>(null);
  const poiLayer = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    const m = L.map(el.current!).setView(HUE, 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    map.current = m;
    poiLayer.current = L.layerGroup().addTo(m); // lịch trình vẽ đè lên trên
    layer.current = L.layerGroup().addTo(m);
    hereLayer.current = L.layerGroup().addTo(m);
    return () => void m.remove();
  }, []);

  // Mọi POI Huế (chấm nhỏ, màu theo loại)
  useEffect(() => {
    const group = poiLayer.current!;
    group.clearLayers();
    pois.forEach((p) => {
      const name = document.createElement("span");
      name.textContent = p.name_vi; // dữ liệu từ DB, không chèn thành HTML
      const color = POI_COLORS[p.category];
      L.circleMarker([p.lat, p.lon], { radius: 5, color, weight: 1, fillOpacity: 0.7 }).bindTooltip(name).addTo(group);
    });
  }, [pois]);

  // Vị trí người dùng chỉ vẽ trên bản đồ ở trình duyệt, không gửi đi đâu
  useEffect(() => {
    const group = hereLayer.current!;
    group.clearLayers();
    if (!here) return;
    const pt: L.LatLngTuple = [here.lat, here.lon];
    if (here.accuracy_m) L.circle(pt, { radius: here.accuracy_m, color: "#2563eb", weight: 1, fillOpacity: 0.1 }).addTo(group);
    L.circleMarker(pt, { radius: 8, color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }).bindTooltip("Bạn ở đây").addTo(group);
    map.current!.setView(pt, 15);
  }, [here]);

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
