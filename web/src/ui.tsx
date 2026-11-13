import { useRef, type ReactNode } from "react";
import type { Claim, Poi } from "./api";

export const vnd = (n: number) => `${n.toLocaleString("vi-VN")} đ`;
export const fold = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/gi, "d").toLowerCase();
export const go = (path: string) => { location.hash = path; };

/** Giờ địa phương kèm múi giờ cho occurred_at của sự kiện chuyến đi. */
export function localIso(d = new Date()) {
  const off = -d.getTimezoneOffset();
  const pad = (n: number) => String(Math.trunc(Math.abs(n))).padStart(2, "0");
  return `${new Date(d.getTime() + off * 60000).toISOString().slice(0, 19)}${off >= 0 ? "+" : "-"}${pad(off / 60)}:${pad(off % 60)}`;
}
export const CATEGORY = { attraction: "Điểm tham quan", food: "Ẩm thực", lodging: "Lưu trú" };

export const INTEREST: Record<string, string> = {
  history: "Lịch sử", food: "Ẩm thực", culture: "Văn hoá", nature: "Thiên nhiên", craft: "Làng nghề", nightlife: "Về đêm", beach: "Biển",
  photography: "Chụp ảnh", shopping: "Mua sắm", relaxed: "Thong thả", moderate: "Vừa phải", packed: "Dày đặc",
};

const DAY = { Mo: "T2", Tu: "T3", We: "T4", Th: "T5", Fr: "T6", Sa: "T7", Su: "CN" };

/** Cú pháp OSM → tiếng Việt. Không có dữ liệu thì nói rõ, không đoán. */
export function hoursText(h: string | null) {
  if (!h) return "Giờ mở cửa chưa xác minh";
  return h.replace(/\b(Mo|Tu|We|Th|Fr|Sa|Su)\b/g, (d) => DAY[d as keyof typeof DAY]);
}

export function priceText(p: Poi) {
  if (p.ticket_price_vnd != null) return `Vé ${vnd(p.ticket_price_vnd)} mỗi người`;
  return p.category === "attraction" ? "Giá vé chưa xác minh" : "Giá chưa xác minh";
}

export function Photo({ poi, eager = false }: { poi: Poi; eager?: boolean }) {
  if (!poi.image) return <div className="no-photo">Chưa có ảnh có giấy phép cho địa điểm này</div>;
  return <img src={poi.image.file} alt={poi.image.illustrative ? `Ảnh minh hoạ món ăn Huế cho ${poi.name_vi}` : poi.name_vi} loading={eager ? "eager" : "lazy"} />;
}

export function PoiCard({ poi }: { poi: Poi }) {
  return (
    <a className="card" href={`#/poi/${poi.poi_id}`}>
      <div className="card-photo"><Photo poi={poi} /></div>
      <div className="card-body">
        <span className="card-kind">{CATEGORY[poi.category]}</span>
        <h3>{poi.name_vi}</h3>
        <p className="muted small">{hoursText(poi.opening_hours)}</p>
        <p className="card-price">{priceText(poi)}</p>
        {poi.image?.illustrative && <p className="muted tiny">Ảnh minh hoạ món Huế, không phải ảnh của quán</p>}
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
          <button aria-label={`Xem trước trong ${title}`} onClick={() => move(-1)}>‹</button>
          <button aria-label={`Xem tiếp trong ${title}`} onClick={() => move(1)}>›</button>
        </div>
      </div>
      <div className="rail-track" ref={track}>{pois.map((p) => <PoiCard key={p.poi_id} poi={p} />)}</div>
    </section>
  );
}

const CLAIM_LABEL: Record<Claim["claim_type"], string> = { opening_hours: "Giờ", price: "Giá", festival_date: "Ngày lễ", weather: "Thời tiết", distance: "Di chuyển" };

/** UC-11: claim sai không bao giờ hiện giá trị sai, chỉ hiện giá trị đã sửa theo nguồn. */
export function ClaimBadge({ c }: { c: Claim }) {
  const label = CLAIM_LABEL[c.claim_type];
  if (c.status === "contradicted") return <span className="tag fixed">{label}: đã sửa theo nguồn, {c.corrected_text}</span>;
  if (c.status === "unverified") return <span className="tag warn">{label}: chưa xác minh</span>;
  return (
    <a className="tag ok" href={c.source_url ?? undefined} target="_blank" rel="noreferrer" title={`Xác minh ngày ${c.verified_at?.slice(0, 10) ?? ""}`}>
      {label}: đã xác minh
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
  return <div className="skeleton" role="status" aria-label="Đang tải">{Array.from({ length: rows }, (_, i) => <span key={i} />)}</div>;
}
