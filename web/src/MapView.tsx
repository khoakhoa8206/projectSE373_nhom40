import L from "leaflet";
import { useEffect, useRef } from "react";
import { api, type Poi, type Slot } from "./api";
import { getLang, poiName, t } from "./i18n";
import type { Coords } from "./location";

const HUE: L.LatLngTuple = [16.4637, 107.5909];
export const DAY_COLORS = ["#0f5f73", "#c2410c", "#7c3aed", "#15803d", "#be123c"];
const POI_COLORS = { attraction: "#475569", food: "#b45309", lodging: "#0369a1" };
// loại POI không chỉ thể hiện bằng màu
const poiLabel = (c: Poi["category"]) => ({ attraction: t("điểm tham quan", "attraction"), food: t("ăn uống", "food"), lodging: t("lưu trú", "stay") })[c];

/** Nội dung popup dựng bằng textContent: activity do LLM sinh, không được chèn thành HTML. */
function popup(s: Slot): HTMLElement {
  const div = document.createElement("div");
  for (const [tag, text] of [["b", `${t("Ngày", "Day")} ${s.day_index} · ${s.start_time}–${s.end_time}`], ["div", poiName(s)], ["div", s.activity]]) {
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
  const lang = getLang(); // tooltip/popup dựng trong effect: đổi ngôn ngữ thì vẽ lại

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
      name.textContent = `${poiName(p)} · ${poiLabel(p.category)}`; // dữ liệu từ DB, không chèn thành HTML
      const color = POI_COLORS[p.category];
      L.circleMarker([p.lat, p.lon], { radius: 5, color, weight: 1, fillOpacity: 0.7 }).bindTooltip(name).addTo(group);
    });
  }, [pois, lang]);

  // Vị trí người dùng chỉ vẽ trên bản đồ ở trình duyệt, không gửi đi đâu
  useEffect(() => {
    const group = hereLayer.current!;
    group.clearLayers();
    if (!here) return;
    const pt: L.LatLngTuple = [here.lat, here.lon];
    if (here.accuracy_m) L.circle(pt, { radius: here.accuracy_m, color: "#2563eb", weight: 1, fillOpacity: 0.1 }).addTo(group);
    L.circleMarker(pt, { radius: 8, color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }).bindTooltip(t("Bạn ở đây", "You are here")).addTo(group);
    map.current!.setView(pt, 15);
  }, [here, lang]);

  useEffect(() => {
    const group = layer.current!;
    group.clearLayers();
    let alive = true;
    const all: L.LatLngTuple[] = [];
    for (const day of new Set(slots.map((s) => s.day_index))) {
      const color = DAY_COLORS[(day - 1) % DAY_COLORS.length];
      const stops = slots.filter((s) => s.day_index === day && s.lat != null && s.lon != null);
      const pts = stops.map((s) => [s.lat!, s.lon!] as L.LatLngTuple);
      // Vẽ ngay nét đứt nối thẳng; lấy được tuyến OSRM (đường đi thực tế) thì thay bằng đường liền.
      const line = L.polyline(pts, { color, weight: 3, opacity: 0.7, dashArray: "6 6" }).addTo(group);
      const ids = stops.map((s) => s.poi_id);
      if (ids.length >= 2 && ids.every(Boolean)) {
        api<{ coordinates: L.LatLngTuple[] | null }>(`/ui/route?pois=${encodeURIComponent(ids.join(","))}`).then((r) => {
          if (!alive || !r.coordinates) return;
          line.setLatLngs(r.coordinates);
          line.setStyle({ dashArray: undefined, weight: 4, opacity: 0.85 });
        }, () => undefined);
      }
      stops.forEach((s, i) => {
        const icon = L.divIcon({ className: "pin", html: `<span style="background:${color}">${i + 1}</span>`, iconSize: [26, 26] });
        L.marker(pts[i], { icon, title: poiName(s) || s.activity }).bindPopup(popup(s)).addTo(group);
      });
      all.push(...pts);
    }
    if (all.length) map.current!.fitBounds(all, { padding: [30, 30], maxZoom: 15 });
    return () => { alive = false; };
  }, [slots, lang]);

  return <div ref={el} className="map" role="region" aria-label={t("Bản đồ lịch trình", "Itinerary map")} />;
}
