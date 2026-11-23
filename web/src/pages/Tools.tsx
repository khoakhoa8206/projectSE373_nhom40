import { useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type Claim, type MemoryRow, type Narration, type Poi } from "../api";
import type { Shell } from "../App";
import { distanceM, nearestPoi, useSessionLocation } from "../location";
import { getLang, poiName, t } from "../i18n";
import { ClaimBadge, Empty, interest, Photo, PhotoCredit, Skeleton } from "../ui";

const KIND: Record<string, [string, string]> = {
  food_like: ["Món thích", "Favourite food"], food_dislike: ["Món không ăn", "Food to avoid"], allergy: ["Dị ứng", "Allergy"],
  dietary: ["Chế độ ăn", "Diet"], pace: ["Nhịp đi", "Pace"], interest: ["Sở thích", "Interest"], visited_city: ["Đã đi", "Visited"], other: ["Khác", "Other"],
};
const kind = (k: string) => (KIND[k] ? t(...KIND[k]) : k);

function NeedLogin({ shell }: { shell: Shell }) {
  return <div className="wrap page"><Empty title={t("Cần đăng nhập để dùng mục này", "Log in to use this section")}><button className="primary" onClick={shell.askLogin}>{t("Đăng nhập", "Log in")}</button></Empty></div>;
}

export function NarratePage({ shell, preset }: { shell: Shell; preset: string | null }) {
  const attractions = shell.pois.filter((p) => p.category === "attraction").sort((a, b) => poiName(a).localeCompare(poiName(b), getLang()));
  const [poiId, setPoiId] = useState(preset ?? "");
  const [question, setQuestion] = useState("");
  const [detail, setDetail] = useState(false);
  const [result, setResult] = useState<(Narration & { lang: "vi" | "en" }) | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const here = useSessionLocation();
  const nearest = nearestPoi(here.coords, attractions);
  const selected = attractions.find((p) => p.poi_id === poiId); // ảnh của điểm đang chọn để thuyết minh

  if (!shell.user) return <NeedLogin shell={shell} />;
  async function ask(q: string, poi: string) {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const lang = getLang(); // trả lời theo chế độ VN/US lúc bấm, không giữ lựa chọn cũ của trang
      setResult({ ...(await api<Narration>("/narrate", { json: { question: q.trim() || null, poi_id: poi || null, lang, length: detail ? "detail" : "short" } })), lang });
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    ask(question, poiId);
  }
  function speak() {
    if (!result) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(result.text.replace(/\[[^\]]*§[^\]]*\]/g, ""));
    u.lang = result.lang === "vi" ? "vi-VN" : "en-US";
    speechSynthesis.speak(u);
  }
  function hereNow() {
    if (!nearest) return;
    setPoiId(nearest.poi_id); // chỉ gửi poi_id, toạ độ ở lại trình duyệt
    setQuestion("");
    ask("", nearest.poi_id);
  }

  return (
    <div className="wrap page narrow">
      <h1>{t("Thuyết minh điểm tham quan", "Site narration")}</h1>
      <p className="muted">{t("Trả lời bằng ngôn ngữ đang chọn (VN/US), kèm trích dẫn. Kho tri thức không có thì hệ thống nói rõ.", "Answers in the selected language (VN/US), with citations. If the knowledge base has nothing, it says so.")}</p>
      {!shell.llm && <p className="note small">{t("Thuyết minh cần khoá LLM. Thêm LLM_API_KEY vào file .env rồi khởi động lại.", "Narration needs an LLM key. Add LLM_API_KEY to .env and restart.")}</p>}
      <form className="stack" onSubmit={submit}>
        <label htmlFor="n-poi">{t("Địa điểm", "Place")}</label>
        <select id="n-poi" value={poiId} onChange={(e) => setPoiId(e.target.value)}>
          <option value="">{t("Tìm trong toàn bộ kho", "Search the whole knowledge base")}</option>
          {attractions.map((p) => <option key={p.poi_id} value={p.poi_id}>{poiName(p)}</option>)}
        </select>
        {selected && (
          <figure className="narrate-photo">
            <Photo poi={selected} />
            <figcaption><PhotoCredit poi={selected} /></figcaption>
          </figure>
        )}
        <label htmlFor="n-q">{t("Câu hỏi", "Question")}</label>
        <input id="n-q" required={!poiId} maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={t("Ngọ Môn được xây năm nào?", "When was the Noon Gate built?")} />
        <label className="check"><input type="checkbox" checked={detail} onChange={(e) => setDetail(e.target.checked)} /> {t("Bản chi tiết", "Detailed version")}</label>
        <button className="primary" disabled={busy}>{busy ? t("Đang tìm...", "Searching...") : t("Hỏi", "Ask")}</button>
      </form>

      <section className="here">
        <h2>{t("Đang ở đây", "I'm here")}</h2>
        <p className="small">{t("Vị trí chỉ dùng để tìm điểm tham quan gần bạn trong phiên này. Toạ độ không được lưu và không gửi lên máy chủ.", "Your location is only used to find nearby sights during this session. Coordinates are never stored or sent to the server.")}</p>
        {here.error && <p className="warn small" role="alert">{here.error}</p>}
        {!here.coords && <button onClick={here.request} disabled={here.asking}>{here.asking ? t("Đang lấy vị trí...", "Getting location...") : t("Tìm điểm gần tôi", "Find sights near me")}</button>}
        {nearest && here.coords && (
          <div className="here-found">
            <p>{t("Gần bạn nhất", "Closest to you")}: <b>{poiName(nearest)}</b>, {t("khoảng", "about")} {(distanceM(here.coords, nearest) / 1000).toFixed(1)} {t("km đường chim bay", "km as the crow flies")}.</p>
            <button className="primary" onClick={hereNow}>{t("Thuyết minh điểm này", "Narrate this place")}</button>
            <button className="ghost" onClick={here.clear}>{t("Tắt vị trí", "Turn off location")}</button>
          </div>
        )}
      </section>

      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <section className="answer" aria-live="polite">
          {result.text.split("\n").map((line, i) => <p key={i} className={result.out_of_kb ? "warn" : undefined}>{line}</p>)}
          {!result.out_of_kb && <button className="ghost" onClick={speak}>{t("Đọc thành tiếng", "Read aloud")}</button>}
          {result.citations.map((c) => (
            <p key={c.doc_id + c.section} className="citation small">
              <a href={c.source_url} target="_blank" rel="noreferrer">[{c.doc_id} §{c.section}]</a>
            </p>
          ))}
        </section>
      )}
    </div>
  );
}

export function MemoryPage({ shell }: { shell: Shell }) {
  const [items, setItems] = useState<MemoryRow[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const load = () => api<{ items: MemoryRow[] }>("/memory").then((r) => setItems(r.items), (e: ApiError) => setError(e.message));
  useEffect(() => { if (shell.user) load(); }, [shell.user]);

  if (!shell.user) return <NeedLogin shell={shell} />;
  async function act(fn: () => Promise<unknown>) {
    setError("");
    try {
      await fn();
      setEditing(null);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  return (
    <div className="wrap page narrow">
      <h1>{t("Bộ nhớ sở thích", "Preference memory")}</h1>
      <p className="muted">{t("Chỉ lưu điều bạn đã nói và xác nhận. Mục nhạy cảm chỉ lưu khi bạn đồng ý, mọi mục đều sửa và xoá được.", "Only what you said and confirmed is saved. Sensitive items are saved only with your consent; everything can be edited or deleted.")}</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!items && !error && <Skeleton />}
      {items?.length === 0 && <Empty title={t("Bộ nhớ đang trống", "Memory is empty")}><p className="muted">{t("Sau khi duyệt lịch trình, agent sẽ hỏi bạn có muốn lưu sở thích không.", "After you approve an itinerary, the agent will ask whether to save your preferences.")}</p></Empty>}
      <ul className="memory-list">
        {items?.map((m) => (
          <li key={m.memory_id}>
            <div>
              <span className="muted small">{kind(m.kind)}{m.sensitivity === "sensitive" && t(", nhạy cảm", ", sensitive")}</span>
              {editing === m.memory_id
                ? <input aria-label={t(`Sửa ${kind(m.kind)}`, `Edit ${kind(m.kind)}`)} value={value} maxLength={200} onChange={(e) => setValue(e.target.value)} />
                : <p><b>{interest(m.value)}</b></p>}
              <span className="muted tiny">{t("Hết hạn", "Expires")} {m.expires_at.slice(0, 10)}</span>
            </div>
            <div className="memory-actions">
              {editing === m.memory_id
                ? <button className="primary" disabled={!value.trim()} onClick={() => act(() => api(`/memory/${m.memory_id}`, { method: "PATCH", json: { value } }))}>{t("Lưu", "Save")}</button>
                : <button onClick={() => { setEditing(m.memory_id); setValue(m.value); }}>{t("Sửa", "Edit")}</button>}
              <button className="ghost" onClick={() => act(() => api(`/memory/${m.memory_id}`, { method: "DELETE" }))}>{t("Xoá", "Delete")}</button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VerifyPage({ shell }: { shell: Shell }) {
  const [text, setText] = useState(() => t("Đại Nội Huế giá vé 300.000đ. Lăng Tự Đức giá vé 150.000đ. Bảo tàng Cổ vật Cung đình Huế mở cửa lúc 9h. Chùa Thiên Mụ mở cửa lúc 7h.",
    "The Imperial City of Hue ticket costs 300,000 VND. The Tomb of Tu Duc ticket costs 150,000 VND. The Hue Royal Antiquities Museum opens at 9am. Thien Mu Pagoda opens at 7am."));
  const [result, setResult] = useState<{ blocked: boolean; lines: { text: string; claims: Claim[] }[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!shell.user) return <NeedLogin shell={shell} />;
  async function check(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setResult(await api("/ui/verify", { json: { text } }));
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="wrap page narrow">
      <h1>{t("Kiểm chứng thông tin", "Fact check")}</h1>
      <p className="muted">{t("Dán một đoạn nháp có giờ, giá, thời tiết hoặc khoảng cách. Số sai được sửa theo nguồn trước khi trình bày.", "Paste a draft with hours, prices, weather or distances. Wrong numbers are corrected from sources before display.")}</p>
      <form className="stack" onSubmit={check}>
        <label htmlFor="v-text">{t("Đoạn cần kiểm", "Text to check")}</label>
        <textarea id="v-text" rows={5} required maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} />
        <button className="primary" disabled={busy}>{busy ? t("Đang kiểm...", "Checking...") : t("Kiểm chứng", "Check")}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <section className="answer" aria-live="polite">
          <h2>{t("Bản được trình bày", "Version shown to the user")}</h2>
          <ul className="verify-lines">
            {result.lines.map((line, i) => (
              <li key={i}>
                <span>{line.text}</span>
                <div className="tags">
                  {line.claims.length === 0 && <span className="muted tiny">{t("Không có dữ kiện cần kiểm", "No facts to check")}</span>}
                  {line.claims.map((c, j) => <ClaimBadge key={j} c={c} />)}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function CreditsPage({ pois }: { pois: Poi[] }) {
  const withImage = pois.filter((p) => p.image);
  const without = pois.filter((p) => !p.image);
  return (
    <div className="wrap page">
      <h1>{t("Nguồn ảnh và giấy phép", "Photo credits and licences")}</h1>
      <p className="muted">{t("Ảnh lấy từ Wikimedia Commons với giấy phép cho phép tái sử dụng. Ảnh ghi “minh hoạ” (món ăn, Làng hương Thủy Xuân) không chụp tại chính địa điểm đó.", "Photos come from Wikimedia Commons under reuse-friendly licences. Photos marked “illustrative” (food, Thuy Xuan incense village) were not taken at that exact place.")}</p>
      <div className="credits">
        {withImage.map((p) => (
          <div key={p.poi_id}>
            <img src={p.image!.file} alt="" loading="lazy" />
            <p className="small"><b>{poiName(p)}</b>{p.image!.illustrative && t(" (minh hoạ)", " (illustrative)")}</p>
            <p className="muted tiny"><a href={p.image!.source_url} target="_blank" rel="noreferrer">{p.image!.author}</a>, {p.image!.license}</p>
          </div>
        ))}
      </div>
      {without.length > 0 && <p className="muted small">{t("Chưa có ảnh được phép dùng", "No licensed photo yet")}: {without.map(poiName).join(", ")}.</p>}
    </div>
  );
}
