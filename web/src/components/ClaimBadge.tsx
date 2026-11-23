import { useId, useState } from "react";
import type { Claim } from "../api";
import { claimView } from "../claims";
import { getLang, t } from "../i18n";

/** UC-11 (W10-P4-3): nhãn verified / chưa xác minh / đã sửa cho 1 dữ kiện, bấm vào xem nguồn và ngày xác minh.
 * Dùng chung: P2 gắn lên lịch trình, P3 gắn lên câu thuyết minh. Trạng thái có cả chữ và ký hiệu, không chỉ bằng màu. */
export function ClaimBadge({ c }: { c: Claim }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const v = claimView(c, getLang());
  return (
    <span className="claim" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      <button type="button" className={`tag ${v.tone}`} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <span aria-hidden="true">{v.icon}</span> {v.label}
      </button>
      {open && (
        <span id={id} className="claim-pop" role="note">
          <span>{v.detail}</span>
          {v.source ? (
            <span>
              {t("Nguồn", "Source")} ({v.source.kind}):{" "}
              <a href={v.source.url} target="_blank" rel="noreferrer">{v.source.host}</a>
            </span>
          ) : (
            <span className="muted">{t("Không có nguồn", "No source")}</span>
          )}
          {v.checkedOn && <span className="muted">{t(`Xác minh ngày ${v.checkedOn}`, `Checked on ${v.checkedOn}`)}</span>}
        </span>
      )}
    </span>
  );
}
