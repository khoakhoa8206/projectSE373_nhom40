/** Hàm thuần về vị trí (không import gì để test bằng node --test). Toạ độ người dùng chỉ đi qua các hàm này trên trình duyệt. */
export type LatLon = { lat: number; lon: number };

/** Khoảng cách đường chim bay (m), công thức haversine. */
export function distanceM(a: LatLon, b: LatLon): number {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((b.lat - a.lat) * rad) / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(((b.lon - a.lon) * rad) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

/** Điểm gần toạ độ nhất. null khi chưa có vị trí hoặc danh sách rỗng. */
export function nearestPoi<P extends LatLon>(coords: LatLon | null, pois: P[]): P | null {
  if (!coords) return null;
  let best: P | null = null;
  let bestM = Infinity;
  for (const p of pois) {
    const m = distanceM(coords, p);
    if (m < bestM) [best, bestM] = [p, m];
  }
  return best;
}

/** "850 m", "1,2 km" (tiếng Việt dùng dấu phẩy), "629 km". */
export function formatDistance(m: number, lang: "vi" | "en"): string {
  if (m < 1000) return `${Math.round(m / 10) * 10} m`;
  const km = m < 10000 ? (Math.round(m / 100) / 10).toFixed(1) : String(Math.round(m / 1000));
  return `${lang === "vi" ? km.replace(".", ",") : km} km`;
}

export const HUE_CENTER: LatLon = { lat: 16.4637, lon: 107.5909 };
// ponytail: bán kính cố định quanh tâm Huế (Huế là điểm đến duy nhất); có điểm đến thứ hai thì lấy vùng từ bảng destinations
export const NEAR_HUE_M = 30000;

/** Người dùng đang ở Huế (trong 30 km quanh tâm thành phố)? Ngoài Huế thì điểm gần nhất không dùng làm điểm xuất phát. */
export const inHue = (c: LatLon) => distanceM(c, HUE_CENTER) <= NEAR_HUE_M;
