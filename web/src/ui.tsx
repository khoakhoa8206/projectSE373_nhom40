import { useRef, type ReactNode } from "react";
import type { Claim, Poi } from "./api";
import { getLang, locale, poiName, t } from "./i18n";

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

export function Photo({ poi, eager = false }: { poi: Poi; eager?: boolean }) {
  if (!poi.image) return <div className="no-photo">{t("Chưa có ảnh có giấy phép cho địa điểm này", "No licensed photo for this place yet")}</div>;
  const name = poiName(poi);
  return <img src={poi.image.file} alt={poi.image.illustrative ? t(`Ảnh minh hoạ món ăn Huế cho ${name}`, `Illustrative photo of Hue food for ${name}`) : name} loading={eager ? "eager" : "lazy"} />;
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
        {poi.image?.illustrative && <p className="muted tiny">{t("Ảnh minh hoạ món Huế, không phải ảnh của quán", "Illustrative photo of Hue food, not taken at this restaurant")}</p>}
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

const CLAIM_LABEL: Record<Claim["claim_type"], [string, string]> = {
  opening_hours: ["Giờ", "Hours"], price: ["Giá", "Price"], festival_date: ["Ngày lễ", "Festival date"], weather: ["Thời tiết", "Weather"], distance: ["Di chuyển", "Travel"],
};

/** UC-11: claim sai không bao giờ hiện giá trị sai, chỉ hiện giá trị đã sửa theo nguồn. */
export function ClaimBadge({ c }: { c: Claim }) {
  const label = t(...CLAIM_LABEL[c.claim_type]);
  if (c.status === "contradicted") return <span className="tag fixed">{label}: {t("đã sửa theo nguồn", "corrected from source")}, {c.corrected_text}</span>;
  if (c.status === "unverified") return <span className="tag warn">{label}: {t("chưa xác minh", "not verified")}</span>;
  return (
    <a className="tag ok" href={c.source_url ?? undefined} target="_blank" rel="noreferrer" title={t(`Xác minh ngày ${c.verified_at?.slice(0, 10) ?? ""}`, `Verified on ${c.verified_at?.slice(0, 10) ?? ""}`)}>
      {label}: {t("đã xác minh", "verified")}
    </a>
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
