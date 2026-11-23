import { useRef, useState, type ReactNode } from "react";
import type { Poi } from "./api";
import { getLang, locale, poiName, t } from "./i18n";

export { ClaimBadge } from "./components/ClaimBadge"; // W10-P4-3: trang cũ vẫn import từ ui

export const vnd = (n: number) => (getLang() === "en" ? `${n.toLocaleString(locale())} VND` : `${n.toLocaleString(locale())} đ`);
export const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/gi, "d").toLowerCase();
export const go = (path: string) => { location.hash = path; };

/** Giờ địa phương kèm múi giờ cho occurred_at của sự kiện chuyến đi. */
export function localIso(d = new Date()) {
  const off = -d.getTimezoneOffset();
  const pad = (n: number) => String(Math.trunc(Math.abs(n))).padStart(2, "0");
  return `${new Date(d.getTime() + off * 60000).toISOString().slice(0, 19)}${off >= 0 ? "+" : "-"}${pad(off / 60)}:${pad(off % 60)}`;
}

export const category = (c: Poi["category"]) =>
  ({ attraction: t("Điểm tham quan", "Attraction"), food: t("Ẩm thực", "Food"), lodging: t("Lưu trú", "Stay") })[c];

const INTEREST: Record<string, [string, string]> = {
  history: ["Lịch sử", "History"], food: ["Ẩm thực", "Food"], culture: ["Văn hoá", "Culture"], nature: ["Thiên nhiên", "Nature"],
  craft: ["Làng nghề", "Craft villages"], nightlife: ["Về đêm", "Nightlife"], beach: ["Biển", "Beach"],
  photography: ["Chụp ảnh", "Photography"], shopping: ["Mua sắm", "Shopping"],
  relaxed: ["Thong thả", "Relaxed"], moderate: ["Vừa phải", "Moderate"], packed: ["Dày đặc", "Packed"],
};
/** Nhãn sở thích/nhịp độ; giá trị lạ (người dùng tự gõ) trả nguyên văn. */
export const interest = (x: string) => (INTEREST[x] ? t(...INTEREST[x]) : x);

const DAY: Record<string, [string, string]> = {
  Mo: ["T2", "Mon"], Tu: ["T3", "Tue"], We: ["T4", "Wed"], Th: ["T5", "Thu"], Fr: ["T6", "Fri"], Sa: ["T7", "Sat"], Su: ["CN", "Sun"],
};

/** Cú pháp OSM → chữ đọc được. Không có dữ liệu thì nói rõ, không đoán. */
export function hoursText(h: string | null) {
  if (!h) return t("Giờ mở cửa chưa xác minh", "Opening hours not verified");
  return h.replace(/\b(Mo|Tu|We|Th|Fr|Sa|Su)\b/g, (d) => t(...DAY[d]));
}

export function priceText(p: Poi) {
  if (p.ticket_price_vnd != null) return t(`Vé ${vnd(p.ticket_price_vnd)} mỗi người`, `Ticket ${vnd(p.ticket_price_vnd)} per person`);
  return p.category === "attraction" ? t("Giá vé chưa xác minh", "Ticket price not verified") : t("Giá chưa xác minh", "Price not verified");
}

/** Ghi chú ảnh minh hoạ theo loại điểm: quán ăn dùng ảnh món Huế; điểm khác (vd Làng hương Thủy Xuân) dùng ảnh chụp ở Huế
 * nhưng không tại chính điểm đó. */
export const illustrativeNote = (p: Poi) => (p.category === "food"
  ? t("Ảnh minh hoạ món Huế, không phải ảnh của quán", "Illustrative photo of Hue food, not taken at this restaurant")
  : t("Ảnh minh hoạ chụp ở Huế, không chụp tại địa điểm này", "Illustrative photo taken in Hue, not at this place"));

export function Photo({ poi, eager = false }: { poi: Poi; eager?: boolean }) {
  const [broken, setBroken] = useState<string | null>(null); // file ảnh không tải được (vd chưa có trong web/public/poi)
  if (!poi.image || broken === poi.image.file) return <div className="no-photo">{t("Chưa có ảnh có giấy phép cho địa điểm này", "No licensed photo for this place yet")}</div>;
  const name = poiName(poi);
  const file = poi.image.file;
  return <img src={file} alt={poi.image.illustrative ? t(`Ảnh minh hoạ cho ${name}`, `Illustrative photo for ${name}`) : name} loading={eager ? "eager" : "lazy"} onError={() => setBroken(file)} />;
}

/** Ghi công ảnh (bắt buộc với CC BY / CC BY-SA): tác giả, giấy phép, link nguồn; ảnh minh hoạ ghi rõ. */
export function PhotoCredit({ poi }: { poi: Poi }) {
  if (!poi.image) return null;
  return (
    <p className="muted tiny credit">
      {poi.image.illustrative && `${illustrativeNote(poi)}. `}
      {t("Ảnh", "Photo")}: <a href={poi.image.source_url} target="_blank" rel="noreferrer">{poi.image.author}</a>, {poi.image.license}, Wikimedia Commons
    </p>
  );
}

export function PoiCard({ poi }: { poi: Poi }) {
  return (
    <a className="card" href={`#/poi/${poi.poi_id}`}>
      <div className="card-photo"><Photo poi={poi} /></div>
      <div className="card-body">
        <span className="card-kind">{category(poi.category)}</span>
        <h3>{poiName(poi)}</h3>
        <p className="muted small">{hoursText(poi.opening_hours)}</p>
        <p className="card-price">{priceText(poi)}</p>
        {poi.image?.illustrative && <p className="muted tiny">{illustrativeNote(poi)}</p>}
      </div>
    </a>
  );
}

export function Carousel({ title, sub, pois }: { title: string; sub?: string; pois: Poi[] }) {
  const track = useRef<HTMLDivElement>(null);
  const move = (dir: number) => track.current?.scrollBy({ left: dir * track.current.clientWidth * 0.85, behavior: "smooth" });
  if (!pois.length) return null;
  return (
    <section className="rail">
      <div className="rail-head">
        <div>
          <h2>{title}</h2>
          {sub && <p className="muted">{sub}</p>}
        </div>
        <div className="rail-arrows">
          <button aria-label={t(`Xem trước trong ${title}`, `Previous in ${title}`)} onClick={() => move(-1)}>‹</button>
          <button aria-label={t(`Xem tiếp trong ${title}`, `Next in ${title}`)} onClick={() => move(1)}>›</button>
        </div>
      </div>
      <div className="rail-track" ref={track}>{pois.map((p) => <PoiCard key={p.poi_id} poi={p} />)}</div>
    </section>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return <div className="skeleton" role="status" aria-label={t("Đang tải", "Loading")}>{Array.from({ length: rows }, (_, i) => <span key={i} />)}</div>;
}
