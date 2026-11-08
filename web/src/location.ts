import { useCallback, useState } from "react";

/** Vị trí người dùng: chỉ nằm trong state React của phiên này (không localStorage, không gửi server, tải lại trang là mất).
 * Cần gửi lên server (vd chế độ "đang ở đây" của UC-03) thì chỉ gửi poi_id từ nearestPoi(), không gửi toạ độ. */
export type Coords = { lat: number; lon: number; accuracy_m?: number };

export function useSessionLocation() {
  const [coords, setCoords] = useState<Coords | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  // Chỉ gọi khi người dùng bấm nút, sau khi đã đọc lời giải thích mục đích.
  const request = useCallback(() => {
    // Trình duyệt chỉ cho lấy vị trí qua HTTPS hoặc localhost; mở bằng IP mạng LAN trên điện thoại sẽ không có.
    if (!window.isSecureContext || !("geolocation" in navigator)) {
      setError(window.isSecureContext ? "Trình duyệt không hỗ trợ định vị." : "Trình duyệt chỉ cho lấy vị trí khi mở trang qua HTTPS.");
      return;
    }
    setAsking(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setAsking(false);
        setCoords({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy_m: Math.round(p.coords.accuracy) });
      },
      (e) => {
        setAsking(false);
        setError(
          e.code === e.PERMISSION_DENIED
            ? "Bạn đã từ chối quyền vị trí. Muốn bật lại thì mở quyền trong cài đặt trình duyệt."
            : e.code === e.TIMEOUT
              ? "Lấy vị trí quá lâu, hãy thử lại."
              : "Không xác định được vị trí.",
        );
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    );
  }, []);

  const clear = useCallback(() => {
    setCoords(null);
    setError(null);
  }, []);

  return { coords, request, error, asking, clear };
}

/** Khoảng cách đường chim bay (m), công thức haversine. */
export function distanceM(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((b.lat - a.lat) * rad) / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(((b.lon - a.lon) * rad) / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

/** POI gần toạ độ nhất, tính ngay trên trình duyệt. null khi chưa có vị trí hoặc danh sách rỗng. */
export function nearestPoi<P extends { lat: number; lon: number }>(coords: { lat: number; lon: number } | null, pois: P[]): P | null {
  if (!coords) return null;
  let best: P | null = null;
  let bestM = Infinity;
  for (const p of pois) {
    const m = distanceM(coords, p);
    if (m < bestM) [best, bestM] = [p, m];
  }
  return best;
}
