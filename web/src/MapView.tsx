import L from "leaflet";
import { useEffect, useRef } from "react";

const HUE: L.LatLngTuple = [16.4637, 107.5909];

/** Bản đồ OSM quanh Huế, tile ghi attribution theo yêu cầu của OpenStreetMap. */
export default function MapView() {
  const el = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const m = L.map(el.current!).setView(HUE, 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    return () => void m.remove();
  }, []);

  return <div ref={el} className="map" role="region" aria-label="Bản đồ Huế" />;
}
