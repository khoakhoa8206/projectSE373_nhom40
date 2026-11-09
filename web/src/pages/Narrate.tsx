import { useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type Poi, type TraceEvent, type User } from "../api";
import { distanceM, nearestPoi, useSessionLocation } from "../location";

// UC-03 (P3 · W9-P3-4): POST /api/narrate. Chỉ gửi poi_id và/hoặc câu hỏi, không bao giờ gửi toạ độ.
type Citation = { doc_id: string; section: string; source_url: string; quote: string };
type NarrateResult = { text: string; citations: Citation[]; out_of_kb: boolean; run_id: string };
type Lang = "vi" | "en";
const NEAR_M = 3000; // xa hơn 3 km thì coi như không đứng ở điểm nào

const MARKER = /\[([a-z0-9-]+-(?:vi|en)-\d{2}) §([^\]]+)\]/g;

/** 1 dòng câu trả lời: marker [doc_id §section] thành link tới source_url của trích dẫn tương ứng. */
function Line({ text, citations }: { text: string; citations: Citation[] }) {
  const parts: (string | Citation | { doc_id: string; section: string })[] = [];
  let last = 0;
  for (const m of text.matchAll(MARKER)) {
    parts.push(text.slice(last, m.index));
    parts.push(citations.find((c) => c.doc_id === m[1] && c.section === m[2]) ?? { doc_id: m[1], section: m[2] });
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(text.slice(last));
  return (
    <p>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          p
        ) : "source_url" in p ? (
          <a key={i} className="cite" href={p.source_url} target="_blank" rel="noreferrer" title={p.quote}>
            [{p.doc_id} §{p.section}]
          </a>
        ) : (
          <span key={i} className="cite">[{p.doc_id} §{p.section}]</span>
        ),
      )}
    </p>
  );
}

export default function Narrate({ user, onExpired }: { user: User; onExpired: () => void }) {
  const [pois, setPois] = useState<Poi[]>([]);
  const [poiId, setPoiId] = useState("");
  const [question, setQuestion] = useState("");
  const [lang, setLang] = useState<Lang>(user.preferred_lang);
  const [length, setLength] = useState<"short" | "detail">("short");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [near, setNear] = useState("");
  const [result, setResult] = useState<NarrateResult | null>(null);
  const [trace, setTrace] = useState<TraceEvent[] | null>(null);
  // Hook vị trí của P4 (web/src/location.ts): toạ độ chỉ nằm trong state của phiên, không lưu, không gửi server.
  const { coords, request, error: locError, asking, clear } = useSessionLocation();

  useEffect(() => {
    api<Poi[]>("/pois?category=attraction").then(setPois, (e: ApiError) => setError(e.message));
  }, []);

  // Có vị trí → tìm POI gần nhất NGAY TRÊN TRÌNH DUYỆT, giữ poi_id rồi xoá toạ độ khỏi bộ nhớ.
  useEffect(() => {
    if (!coords || pois.length === 0) return;
    const p = nearestPoi(coords, pois);
    const m = p ? distanceM(coords, p) : Infinity;
    if (p && m <= NEAR_M) {
      setPoiId(p.poi_id);
      setNear(`Gần nhất: ${p.name_vi} (~${Math.round(m)} m). Chỉ mã điểm được gửi lên máy chủ.`);
    } else setNear("Không có điểm tham quan nào trong bán kính 3 km: hãy chọn điểm trong danh sách.");
    clear();
  }, [coords, pois, clear]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);
    setTrace(null);
    if (!poiId && !question.trim()) return setError("Chọn một điểm tham quan hoặc nhập câu hỏi.");
    setBusy(true);
    let runId: string | undefined;
    try {
      const body = { lang, length, ...(poiId ? { poi_id: poiId } : {}), ...(question.trim() ? { question: question.trim() } : {}) };
      const res = await api<NarrateResult>("/narrate", { json: body });
      runId = res.run_id;
      setResult(res);
    } catch (err) {
      const e = err as ApiError;
      if (e.status === 401) return onExpired();
      runId = (e.detail as { run_id?: string } | undefined)?.run_id;
      setError(e.message);
    } finally {
      setBusy(false);
    }
    if (runId) api<TraceEvent[]>(`/runs/${runId}/trace`).then(setTrace, () => {});
  }

  return (
    <main className="page">
      <form onSubmit={submit} className="card">
        <fieldset disabled={busy} className="grid">
          <legend>Thuyết minh điểm tham quan</legend>
          <label className="wide">
            Điểm tham quan
            <select value={poiId} onChange={(e) => { setPoiId(e.target.value); setNear(""); }}>
              <option value="">(không chọn: hỏi chung về Huế)</option>
              {pois.map((p) => (
                <option key={p.poi_id} value={p.poi_id}>{p.name_vi}</option>
              ))}
            </select>
          </label>
          <div className="wide row">
            <button type="button" onClick={() => { setNear(""); request(); }} disabled={asking}>
              {asking ? "Đang lấy vị trí…" : "📍 Đang ở đây"}
            </button>
            <small>{near || locError || "Tìm điểm gần nhất trên trình duyệt, không gửi toạ độ."}</small>
          </div>
          <label className="wide">
            Câu hỏi <small>(để trống = giới thiệu điểm đã chọn)</small>
            <input value={question} maxLength={500} placeholder="vd Chùa Thiên Mụ được xây năm nào?"
              onChange={(e) => setQuestion(e.target.value)} />
          </label>
          <label>
            Ngôn ngữ trả lời
            <select value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
            </select>
          </label>
          <label>
            Độ dài
            <select value={length} onChange={(e) => setLength(e.target.value as "short" | "detail")}>
              <option value="short">Ngắn (~60 giây đọc)</option>
              <option value="detail">Chi tiết</option>
            </select>
          </label>
          <button type="submit" className="wide primary">{busy ? "Đang thuyết minh…" : "Thuyết minh"}</button>
        </fieldset>
      </form>

      {busy && (
        <div className="loading" role="status">
          <span className="spinner" aria-hidden /> Agent đang tìm trong kho tri thức và viết câu trả lời có trích dẫn…
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <section className="card">
          {result.out_of_kb ? (
            <p className="notice" role="status">
              <b>{result.text}</b>
              <br />
              <small>Kho tri thức Huế chưa có tài liệu trả lời câu này nên agent không đoán.</small>
            </p>
          ) : (
            <>
              <h2>Thuyết minh</h2>
              {result.text.split("\n").map((line, i) => <Line key={i} text={line} citations={result.citations} />)}
              <h3>Nguồn</h3>
              <ol className="sources">
                {result.citations.map((c, i) => (
                  <li key={i}>
                    <a href={c.source_url} target="_blank" rel="noreferrer">{c.doc_id} §{c.section}</a>
                    <div className="muted small">“{c.quote}”</div>
                  </li>
                ))}
              </ol>
            </>
          )}
          <p className="muted small">run_id: <code>{result.run_id}</code></p>
        </section>
      )}
      {trace && (
        <details className="trace">
          <summary>Log các bước của agent · {trace.length} bước</summary>
          <ol>
            {trace.map((e) => (
              <li key={e.seq} className={e.error ? "err" : undefined}>
                <b>{e.node}</b> · {e.kind}{e.name && ` · ${e.name}`}{e.error && ` · lỗi: ${e.error}`}
              </li>
            ))}
          </ol>
        </details>
      )}
    </main>
  );
}
