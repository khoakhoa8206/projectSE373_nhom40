import { useEffect, useState } from "react";
import { api, type ApiError, type PoiDetail } from "../api";
import type { Shell } from "../App";
import MapView from "../MapView";
import { CATEGORY, Empty, hoursText, Photo, priceText, Skeleton } from "../ui";

const NO_SLOTS: never[] = [];

export default function PoiPage({ id, shell }: { id: string; shell: Shell }) {
  const [poi, setPoi] = useState<PoiDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<PoiDetail>(`/ui/pois/${id}`).then(setPoi, (e: ApiError) => setError(e.message));
  }, [id]);

  if (error) return <div className="wrap page"><Empty title="Không mở được địa điểm"><p className="muted">{error}</p><a href="#/">Về trang khám phá</a></Empty></div>;
  if (!poi) return <div className="wrap page"><Skeleton rows={5} /></div>;

  const lang = shell.user?.preferred_lang ?? "vi";
  const about = poi.about.filter((a) => a.lang === lang).length ? poi.about.filter((a) => a.lang === lang) : poi.about;
  const near = poi.nearby.map((n) => ({ ...n, poi: shell.pois.find((p) => p.poi_id === n.poi_id) })).filter((n) => n.poi);
  const planText = `Tôi muốn đi Huế và ghé ${poi.name_vi}, `;

  return (
    <article className="wrap page poi">
      <p className="crumbs"><a href="#/">Khám phá</a> / {CATEGORY[poi.category]}</p>
      <h1>{poi.name_vi}</h1>
      {poi.name_en && poi.name_en !== poi.name_vi && <p className="muted">{poi.name_en}</p>}
      <div className="poi-photo"><Photo poi={poi} eager /></div>
      {poi.image && (
        <p className="muted tiny credit">
          {poi.image.illustrative && "Ảnh minh hoạ món Huế, không phải ảnh của quán. "}
          Ảnh: <a href={poi.image.source_url} target="_blank" rel="noreferrer">{poi.image.author}</a>, {poi.image.license}, Wikimedia Commons
        </p>
      )}
      <div className="poi-grid">
        <div>
          <h2>Giới thiệu</h2>
          {about.length ? about.slice(0, 3).map((a) => (
            <section key={a.doc_id + a.section} className="about">
              <h3>{a.section}</h3>
              <p>{a.text}</p>
              <p className="muted tiny"><a href={a.source_url} target="_blank" rel="noreferrer">[{a.doc_id} §{a.section}]</a> {a.license}</p>
            </section>
          )) : <p className="muted">Kho tri thức chưa có bài về địa điểm này, nên trang không tự viết phần giới thiệu.</p>}
          <h2>Vị trí</h2>
          <MapView slots={NO_SLOTS} pois={[poi]} />
          {near.length > 0 && (
            <>
              <h2>Gần đây</h2>
              <ul className="nearby">
                {near.map((n) => (
                  <li key={n.poi_id}>
                    <a href={`#/poi/${n.poi_id}`}>{n.name_vi}</a>
                    <span className="muted small">{n.minutes} phút lái xe</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <aside className="facts">
          <p className="facts-price">{priceText(poi)}</p>
          <p>{hoursText(poi.opening_hours)}</p>
          <p className="muted tiny">
            Nguồn <a href={poi.source_url} target="_blank" rel="noreferrer">{poi.license}</a>, xác minh {poi.verified_at}
          </p>
          <a className="button primary" href={`#/plan?text=${encodeURIComponent(planText)}`}>Thêm vào chuyến đi</a>
          <a className="button" href={`#/narrate?poi=${poi.poi_id}`}>Nghe thuyết minh</a>
        </aside>
      </div>
    </article>
  );
}
