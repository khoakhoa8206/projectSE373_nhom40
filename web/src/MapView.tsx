import L from "leaflet";
import { useEffect, useRef } from "react";
import { api, type Poi, type Slot } from "./api";
import { getLang, poiName, t } from "./i18n";
import { distanceM, formatDistance } from "./geo";
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

/** Bản đồ OSM: mọi POI + marker đánh số theo thứ tự trong ngày + đường nối các điểm (mỗi ngày một màu) + vị trí người dùng
 * nếu có, nối tới điểm gần nhất (nearest) kèm khoảng cách. */
export default function MapView({ slots, pois, here, nearest }: {
  slots: Slot[]; pois: Poi[]; here?: Coords | null; nearest?: { lat: number; lon: number; name: string } | null;
}) {
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

  // Vị trí người dùng chỉ vẽ trên bản đồ ở trình duyệt, không gửi đi đâu. Có điểm gần nhất thì nối nét đứt + ghi khoảng
  // cách ở giữa đường, khung nhìn ôm cả hai điểm (ở xa Huế vẫn thấy được mình và điểm đến).
  const [nLat, nLon, nName] = [nearest?.lat, nearest?.lon, nearest?.name];
  useEffect(() => {
    const group = hereLayer.current!;
    group.clearLayers();
    if (!here) return;
    map.current!.invalidateSize(); // thẻ điểm gần nhất vừa chèn phía trên làm bản đồ đổi cỡ: Leaflet phải đo lại trước khi canh khung
    const pt: L.LatLngTuple = [here.lat, here.lon];
    if (here.accuracy_m) L.circle(pt, { radius: here.accuracy_m, color: "#2563eb", weight: 1, fillOpacity: 0.1 }).addTo(group);
    L.circleMarker(pt, { radius: 8, color: "#fff", weight: 3, fillColor: "#2563eb", fillOpacity: 1 }).bindTooltip(t("Bạn ở đây", "You are here")).addTo(group);
    if (nLat == null || nLon == null) {
      map.current!.setView(pt, 15);
      return;
    }
    const to: L.LatLngTuple = [nLat, nLon];
    const name = document.createElement("span");
    name.textContent = `${t("Gần bạn nhất", "Closest to you")}: ${nName ?? ""}`; // tên từ DB, không chèn thành HTML
    L.polyline([pt, to], { color: "#2563eb", weight: 3, dashArray: "4 8" }).addTo(group);
    L.circleMarker(to, { radius: 13, color: "#2563eb", weight: 3, fill: false }).bindTooltip(name).addTo(group);
    const label = document.createElement("span");
    label.textContent = formatDistance(distanceM(here, { lat: nLat, lon: nLon }), lang);
    L.tooltip({ permanent: true, direction: "center", className: "dist-label" })
      .setLatLng([(pt[0] + to[0]) / 2, (pt[1] + to[1]) / 2]).setContent(label).addTo(group);
    map.current!.fitBounds([pt, to], { padding: [48, 48], maxZoom: 16 });
  }, [here, nLat, nLon, nName, lang]);

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
