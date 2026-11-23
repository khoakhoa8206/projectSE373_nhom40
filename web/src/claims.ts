/** UC-11 (W10-P4-3): cách hiển thị một dữ kiện đã kiểm. Hàm thuần, không import gì để test bằng node --test.
 * Quy tắc: claim sai (contradicted) KHÔNG BAO GIỜ hiện giá trị sai (claim_text), chỉ hiện giá trị đúng theo nguồn. */
export type ClaimLike = {
  claim_type: "opening_hours" | "price" | "festival_date" | "weather" | "distance";
  claim_text: string;
  status: "verified" | "unverified" | "contradicted";
  source_url: string | null;
  verified_at: string | null;
  corrected_text: string | null;
  evidence_kind?: "tool" | "kb" | null;
};

type Lang = "vi" | "en";
const KIND: Record<ClaimLike["claim_type"], [string, string]> = {
  opening_hours: ["Giờ", "Hours"], price: ["Giá", "Price"], festival_date: ["Ngày lễ", "Festival date"],
  weather: ["Thời tiết", "Weather"], distance: ["Di chuyển", "Travel"],
};
const STATE: Record<ClaimLike["status"], { tone: "ok" | "warn" | "fixed"; icon: string; label: [string, string] }> = {
  verified: { tone: "ok", icon: "✓", label: ["đã xác minh", "verified"] },
  unverified: { tone: "warn", icon: "?", label: ["chưa xác minh", "not verified"] },
  contradicted: { tone: "fixed", icon: "✎", label: ["đã sửa theo nguồn", "corrected from source"] },
};

/** Tên miền của nguồn để hiện cho gọn; URL hỏng hoặc không phải http(s) thì không tạo link. */
export function sourceHost(url: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.hostname.replace(/^www\./, "") : null;
  } catch {
    return null;
  }
}

export function claimView(c: ClaimLike, lang: Lang) {
  const pick = ([vi, en]: [string, string]) => (lang === "vi" ? vi : en);
  const s = STATE[c.status];
  const detail = {
    verified: pick(["Khớp với nguồn", "Matches the source"]),
    unverified: pick(["Chưa có nguồn để đối chiếu, hãy kiểm tra lại trước khi đi", "No source to check against, please confirm before you go"]),
    contradicted: `${pick(["Giá trị theo nguồn", "Value from source"])}: ${c.corrected_text ?? ""}`,
  }[c.status];
  const host = sourceHost(c.source_url);
  return {
    tone: s.tone,
    icon: s.icon,
    label: `${pick(KIND[c.claim_type])}: ${pick(s.label)}`,
    detail,
    source: host && c.source_url ? { url: c.source_url, host, kind: c.evidence_kind === "kb" ? pick(["kho tri thức", "knowledge base"]) : pick(["dữ liệu điểm đến", "destination data"]) } : null,
    checkedOn: c.verified_at ? c.verified_at.slice(0, 10) : null,
  };
}
