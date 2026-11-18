/** Ngôn ngữ giao diện VN/US. Chuỗi viết tại chỗ: t("tiếng Việt", "English"), không cần bảng key.
 * App giữ state lang và render lại cả cây khi đổi, nên mọi t() đọc giá trị mới. Lựa chọn lưu trong localStorage. */
export type Lang = "vi" | "en";

const KEY = "hue.lang";

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "vi" || saved === "en") return saved;
  } catch { /* storage bị chặn: dùng mặc định */ }
  return "vi";
}

let current: Lang = initial();
document.documentElement.lang = current;

export const getLang = () => current;

export function setLang(lang: Lang) {
  current = lang;
  document.documentElement.lang = lang;
  try { localStorage.setItem(KEY, lang); } catch { /* chỉ là tiện ích, không lưu được cũng không sao */ }
}

export const t = (vi: string, en: string) => (current === "en" ? en : vi);

/** Tên POI theo ngôn ngữ; thiếu name_en thì dùng name_vi. */
export const poiName = (p: { name_vi?: string | null; name_en?: string | null }) => (current === "en" && p.name_en) || p.name_vi || "";

export const locale = () => (current === "en" ? "en-US" : "vi-VN");
