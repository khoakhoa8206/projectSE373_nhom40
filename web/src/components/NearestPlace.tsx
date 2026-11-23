import type { ReactNode } from "react";
import type { Poi } from "../api";
import { distanceM, formatDistance, inHue } from "../geo";
import { getLang, poiName, t } from "../i18n";
import type { Coords } from "../location";
import { category, hoursText, Photo, priceText } from "../ui";

/** Thẻ "điểm gần bạn nhất" (trang Lập lịch, trang Chuyến đi): ảnh, tên, loại, khoảng cách đường chim bay, giờ và giá theo
 * dữ liệu có nguồn (thiếu thì ghi chưa xác minh). Toạ độ chỉ dùng để tính trên máy này, không gửi đi. */
export function NearestPlace({ poi, here, title, extra, onClear }: {
  poi: Poi; here: Coords; title: string; extra?: ReactNode; onClear: () => void;
}) {
  const far = !inHue(here);
  return (
    <div className="nearest" aria-live="polite">
      <div className="nearest-photo"><Photo poi={poi} /></div>
      <div className="nearest-body">
        <p className="muted tiny">{title}</p>
        <p className="nearest-name"><a href={`#/poi/${poi.poi_id}`}>{poiName(poi)}</a> <span className="tag">{category(poi.category)}</span></p>
        <p className="small">
          {t("Cách bạn", "Distance")} <b>{formatDistance(distanceM(here, poi), getLang())}</b> {t("đường chim bay", "as the crow flies")}
          {here.accuracy_m ? <span className="muted"> · {t("sai số vị trí", "location accuracy")} ±{here.accuracy_m < 1000 ? `${here.accuracy_m} m` : formatDistance(here.accuracy_m, getLang())}</span> : null}
        </p>
        {extra}
        <p className="muted tiny">{hoursText(poi.opening_hours)} · {priceText(poi)}</p>
        {far && <p className="warn tiny">{t("Bạn đang ở ngoài Huế nên khoảng cách chỉ để tham khảo.", "You are outside Hue, so the distance is only indicative.")}</p>}
        <button type="button" className="ghost" onClick={onClear}>{t("Tắt vị trí", "Turn off location")}</button>
      </div>
    </div>
  );
}
