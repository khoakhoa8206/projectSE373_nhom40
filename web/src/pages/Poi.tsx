import { useEffect, useState } from "react";
import { api, type ApiError, type PoiDetail } from "../api";
import type { Shell } from "../App";
import MapView from "../MapView";
import { getLang, poiName, t } from "../i18n";
import { category, Empty, hoursText, Photo, priceText, Skeleton } from "../ui";

const NO_SLOTS: never[] = [];

export default function PoiPage({ id, shell }: { id: string; shell: Shell }) {
  const [poi, setPoi] = useState<PoiDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<PoiDetail>(`/ui/pois/${id}`).then(setPoi, (e: ApiError) => setError(e.message));
  }, [id]);

  if (error) return <div className="wrap page"><Empty title={t("Không mở được địa điểm", "Could not open this place")}><p className="muted">{error}</p><a href="#/">{t("Về trang khám phá", "Back to Explore")}</a></Empty></div>;
  if (!poi) return <div className="wrap page"><Skeleton rows={5} /></div>;

  const lang = getLang();
  const about = poi.about.filter((a) => a.lang === lang).length ? poi.about.filter((a) => a.lang === lang) : poi.about;
  const near = poi.nearby.map((n) => ({ ...n, poi: shell.pois.find((p) => p.poi_id === n.poi_id) })).filter((n) => n.poi);
  const name = poiName(poi);
  const other = lang === "en" ? poi.name_vi : poi.name_en;
  const planText = t(`Tôi muốn đi Huế và ghé ${name}, `, `I want to visit Hue and stop by ${name}, `);

  return (
    <article className="wrap page poi">
      <p className="crumbs"><a href="#/">{t("Khám phá", "Explore")}</a> / {category(poi.category)}</p>
      <h1>{name}</h1>
      {other && other !== name && <p className="muted">{other}</p>}
      <div className="poi-photo"><Photo poi={poi} eager /></div>
      {poi.image && (
        <p className="muted tiny credit">
          {poi.image.illustrative && t("Ảnh minh hoạ món Huế, không phải ảnh của quán. ", "Illustrative photo of Hue food, not taken at this restaurant. ")}
          {t("Ảnh", "Photo")}: <a href={poi.image.source_url} target="_blank" rel="noreferrer">{poi.image.author}</a>, {poi.image.license}, Wikimedia Commons
        </p>
      )}
      <div className="poi-grid">
        <div>
          <h2>{t("Giới thiệu", "About")}</h2>
          {about.length ? about.slice(0, 3).map((a) => (
            <section key={a.doc_id + a.section} className="about">
              <h3>{a.section}</h3>
              <p>{a.text}</p>
              <p className="muted tiny"><a href={a.source_url} target="_blank" rel="noreferrer">[{a.doc_id} §{a.section}]</a> {a.license}</p>
            </section>
          )) : <p className="muted">{t("Kho tri thức chưa có bài về địa điểm này, nên trang không tự viết phần giới thiệu.", "The knowledge base has no article about this place yet, so no introduction is written.")}</p>}
          <h2>{t("Vị trí", "Location")}</h2>
          <MapView slots={NO_SLOTS} pois={[poi]} />
          {near.length > 0 && (
            <>
              <h2>{t("Gần đây", "Nearby")}</h2>
              <ul className="nearby">
                {near.map((n) => (
                  <li key={n.poi_id}>
                    <a href={`#/poi/${n.poi_id}`}>{poiName(n)}</a>
                    <span className="muted small">{n.minutes} {t("phút lái xe", "min by car")}</span>
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
            {t("Nguồn", "Source")} <a href={poi.source_url} target="_blank" rel="noreferrer">{poi.license}</a>, {t("xác minh", "verified")} {poi.verified_at}
          </p>
          <a className="button primary" href={`#/plan?text=${encodeURIComponent(planText)}`}>{t("Thêm vào chuyến đi", "Add to a trip")}</a>
          <a className="button" href={`#/narrate?poi=${poi.poi_id}`}>{t("Nghe thuyết minh", "Listen to narration")}</a>
        </aside>
      </div>
    </article>
  );
}
