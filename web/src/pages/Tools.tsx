import { useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type Claim, type MemoryRow, type Narration, type Poi } from "../api";
import type { Shell } from "../App";
import { distanceM, nearestPoi, useSessionLocation } from "../location";
import { ClaimBadge, Empty, INTEREST, Skeleton } from "../ui";

const KIND: Record<string, string> = {
  food_like: "Món thích", food_dislike: "Món không ăn", allergy: "Dị ứng", dietary: "Chế độ ăn", pace: "Nhịp đi", interest: "Sở thích", visited_city: "Đã đi", other: "Khác",
};

function NeedLogin({ shell }: { shell: Shell }) {
  return <div className="wrap page"><Empty title="Cần đăng nhập để dùng mục này"><button className="primary" onClick={shell.askLogin}>Đăng nhập</button></Empty></div>;
}

export function NarratePage({ shell, preset }: { shell: Shell; preset: string | null }) {
  const attractions = shell.pois.filter((p) => p.category === "attraction").sort((a, b) => a.name_vi.localeCompare(b.name_vi, "vi"));
  const [poiId, setPoiId] = useState(preset ?? "");
  const [question, setQuestion] = useState("");
  const [detail, setDetail] = useState(false);
  const [lang, setLang] = useState<"vi" | "en">(shell.user?.preferred_lang ?? "vi");
  const [result, setResult] = useState<Narration | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const here = useSessionLocation();
  const nearest = nearestPoi(here.coords, attractions);

  if (!shell.user) return <NeedLogin shell={shell} />;
  async function ask(q: string, poi: string) {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await api<Narration>("/narrate", { json: { question: q.trim() || null, poi_id: poi || null, lang, length: detail ? "detail" : "short" } }));
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
    u.lang = lang === "vi" ? "vi-VN" : "en-US";
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
      <h1>Thuyết minh điểm tham quan</h1>
      <p className="muted">Trả lời theo ngôn ngữ bạn chọn, kèm trích dẫn. Kho tri thức không có thì hệ thống nói rõ.</p>
      {!shell.llm && <p className="note small">Thuyết minh cần khoá LLM. Thêm LLM_API_KEY vào file .env rồi khởi động lại.</p>}
      <form className="stack" onSubmit={submit}>
        <label htmlFor="n-poi">Địa điểm</label>
        <select id="n-poi" value={poiId} onChange={(e) => setPoiId(e.target.value)}>
          <option value="">Tìm trong toàn bộ kho</option>
          {attractions.map((p) => <option key={p.poi_id} value={p.poi_id}>{p.name_vi}</option>)}
        </select>
        <label htmlFor="n-q">Câu hỏi</label>
        <input id="n-q" required={!poiId} maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ngọ Môn được xây năm nào?" />
        <label htmlFor="n-lang">Ngôn ngữ trả lời</label>
        <select id="n-lang" value={lang} onChange={(e) => setLang(e.target.value as "vi" | "en")}>
          <option value="vi">Tiếng Việt</option>
          <option value="en">English</option>
        </select>
        <label className="check"><input type="checkbox" checked={detail} onChange={(e) => setDetail(e.target.checked)} /> Bản chi tiết</label>
        <button className="primary" disabled={busy}>{busy ? "Đang tìm..." : "Hỏi"}</button>
      </form>

      <section className="here">
        <h2>Đang ở đây</h2>
        <p className="small">Vị trí chỉ dùng để tìm điểm tham quan gần bạn trong phiên này. Toạ độ không được lưu và không gửi lên máy chủ.</p>
        {here.error && <p className="warn small" role="alert">{here.error}</p>}
        {!here.coords && <button onClick={here.request} disabled={here.asking}>{here.asking ? "Đang lấy vị trí..." : "Tìm điểm gần tôi"}</button>}
        {nearest && here.coords && (
          <div className="here-found">
            <p>Gần bạn nhất: <b>{nearest.name_vi}</b>, khoảng {(distanceM(here.coords, nearest) / 1000).toFixed(1)} km đường chim bay.</p>
            <button className="primary" onClick={hereNow}>Thuyết minh điểm này</button>
            <button className="ghost" onClick={here.clear}>Tắt vị trí</button>
          </div>
        )}
      </section>

      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <section className="answer" aria-live="polite">
          {result.text.split("\n").map((line, i) => <p key={i} className={result.out_of_kb ? "warn" : undefined}>{line}</p>)}
          {!result.out_of_kb && <button className="ghost" onClick={speak}>Đọc thành tiếng</button>}
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
      <h1>Bộ nhớ sở thích</h1>
      <p className="muted">Chỉ lưu điều bạn đã nói và xác nhận. Mục nhạy cảm chỉ lưu khi bạn đồng ý, mọi mục đều sửa và xoá được.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!items && !error && <Skeleton />}
      {items?.length === 0 && <Empty title="Bộ nhớ đang trống"><p className="muted">Sau khi duyệt lịch trình, agent sẽ hỏi bạn có muốn lưu sở thích không.</p></Empty>}
      <ul className="memory-list">
        {items?.map((m) => (
          <li key={m.memory_id}>
            <div>
              <span className="muted small">{KIND[m.kind]}{m.sensitivity === "sensitive" && ", nhạy cảm"}</span>
              {editing === m.memory_id
                ? <input aria-label={`Sửa ${KIND[m.kind]}`} value={value} maxLength={200} onChange={(e) => setValue(e.target.value)} />
                : <p><b>{INTEREST[m.value] ?? m.value}</b></p>}
              <span className="muted tiny">Hết hạn {m.expires_at.slice(0, 10)}</span>
            </div>
            <div className="memory-actions">
              {editing === m.memory_id
                ? <button className="primary" disabled={!value.trim()} onClick={() => act(() => api(`/memory/${m.memory_id}`, { method: "PATCH", json: { value } }))}>Lưu</button>
                : <button onClick={() => { setEditing(m.memory_id); setValue(m.value); }}>Sửa</button>}
              <button className="ghost" onClick={() => act(() => api(`/memory/${m.memory_id}`, { method: "DELETE" }))}>Xoá</button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VerifyPage({ shell }: { shell: Shell }) {
  const [text, setText] = useState("Đại Nội Huế giá vé 300.000đ. Lăng Tự Đức giá vé 150.000đ. Bảo tàng Cổ vật Cung đình Huế mở cửa lúc 9h. Chùa Thiên Mụ mở cửa lúc 7h.");
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
      <h1>Kiểm chứng thông tin</h1>
      <p className="muted">Dán một đoạn nháp có giờ, giá, thời tiết hoặc khoảng cách. Số sai được sửa theo nguồn trước khi trình bày.</p>
      <form className="stack" onSubmit={check}>
        <label htmlFor="v-text">Đoạn cần kiểm</label>
        <textarea id="v-text" rows={5} required maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} />
        <button className="primary" disabled={busy}>{busy ? "Đang kiểm..." : "Kiểm chứng"}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <section className="answer" aria-live="polite">
          <h2>Bản được trình bày</h2>
          <ul className="verify-lines">
            {result.lines.map((line, i) => (
              <li key={i}>
                <span>{line.text}</span>
                <div className="tags">
                  {line.claims.length === 0 && <span className="muted tiny">Không có dữ kiện cần kiểm</span>}
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
      <h1>Nguồn ảnh và giấy phép</h1>
      <p className="muted">Ảnh lấy từ Wikimedia Commons với giấy phép cho phép tái sử dụng. Ảnh món ăn là ảnh minh hoạ, không chụp tại quán được nhắc.</p>
      <div className="credits">
        {withImage.map((p) => (
          <div key={p.poi_id}>
            <img src={p.image!.file} alt="" loading="lazy" />
            <p className="small"><b>{p.name_vi}</b>{p.image!.illustrative && " (minh hoạ)"}</p>
            <p className="muted tiny"><a href={p.image!.source_url} target="_blank" rel="noreferrer">{p.image!.author}</a>, {p.image!.license}</p>
          </div>
        ))}
      </div>
      {without.length > 0 && <p className="muted small">Chưa có ảnh được phép dùng: {without.map((p) => p.name_vi).join(", ")}.</p>}
    </div>
  );
}
