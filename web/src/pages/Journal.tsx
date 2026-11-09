import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type Poi, type User } from "../api";

// UC-09 (P3 · W9-P3-4): ghi sự kiện chuyến đi, xem nhật ký ngày / tóm tắt chuyến, token trước → sau, tổng chi (tool).
type TripRow = { trip_id: string; status: string; created_at: string; start_date: string | null; end_date: string | null };
type EventType = "slot_done" | "slot_skipped" | "note" | "expense" | "photo_meta" | "adjustment";
type TripEventRow = {
  event_id: string;
  occurred_at: string;
  day_index: number;
  event_type: EventType;
  poi_id: string | null;
  amount_vnd: number | null;
  payload: Record<string, string>;
  name_vi: string | null;
};
type Highlight = { text: string; event_ids?: string[]; day_indexes?: number[] };
type Journal = {
  journal_id: string;
  scope: "day" | "trip";
  day_index: number | null;
  lang: "vi" | "en";
  content: { summary: string; highlights: Highlight[]; is_empty?: boolean; days?: { day_index: number; total_spent_vnd: number }[] };
  event_ids: string[];
  total_spent_vnd: number;
  tokens_before: number | null;
  tokens_after: number | null;
  run_id: string;
};

const LABEL: Record<EventType, string> = {
  slot_done: "Đã đi", slot_skipped: "Bỏ", note: "Ghi chú", expense: "Chi tiêu", photo_meta: "Ảnh", adjustment: "Điều chỉnh",
};
const CATEGORY: Record<string, string> = { food: "Ăn uống", tickets: "Vé", transport: "Di chuyển", lodging: "Lưu trú", other: "Khác" };
const vnd = (n: number) => `${n.toLocaleString("vi-VN")} đ`;

/** Giờ máy kèm độ lệch múi giờ (vd 2026-11-21T15:36:00+07:00), không dùng toISOString() vì đó là giờ UTC:
 * danh sách sự kiện và prompt nhật ký đọc HH:MM từ chuỗi này. */
function localIso(d = new Date()) {
  const off = -d.getTimezoneOffset();
  const pad = (n: number) => String(Math.trunc(Math.abs(n))).padStart(2, "0");
  const wall = new Date(d.getTime() + off * 60000).toISOString().slice(0, 19);
  return `${wall}${off >= 0 ? "+" : "-"}${pad(off / 60)}:${pad(off % 60)}`;
}

function describe(e: TripEventRow) {
  const p = e.payload ?? {};
  const where = e.name_vi ?? e.poi_id ?? "";
  if (e.event_type === "expense")
    return [p.label || CATEGORY[p.category] || p.category, where, vnd(e.amount_vnd ?? 0)].filter(Boolean).join(" · ");
  if (e.event_type === "note") return p.text ?? "";
  if (e.event_type === "photo_meta") return p.caption ?? "";
  if (e.event_type === "adjustment") return `${p.change ?? ""}${p.reason ? ` (${p.reason})` : ""}`;
  return `${where}${p.reason ? ` — ${p.reason}` : ""}`;
}

export default function JournalPage({ user, onExpired }: { user: User; onExpired: () => void }) {
  const [trips, setTrips] = useState<TripRow[] | null>(null);
  const [tripId, setTripId] = useState("");
  const [events, setEvents] = useState<TripEventRow[]>([]);
  const [pois, setPois] = useState<Poi[]>([]);
  const [form, setForm] = useState({ type: "slot_done" as EventType, day: 1, poiId: "", text: "", amount: "", category: "food" });
  const [day, setDay] = useState(1);
  const [lang, setLang] = useState<"vi" | "en">(user.preferred_lang);
  const [journal, setJournal] = useState<Journal | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const fail = useCallback((err: unknown) => {
    const e = err as ApiError;
    if (e.status === 401) onExpired();
    else setError(e.message);
  }, [onExpired]);

  useEffect(() => {
    api<TripRow[]>("/trips").then((rows) => {
      setTrips(rows);
      setTripId((t) => t || rows[0]?.trip_id || "");
    }, fail);
    api<Poi[]>("/pois").then(setPois, fail);
  }, [fail]);

  const loadEvents = useCallback(() => {
    if (tripId) api<TripEventRow[]>(`/trips/${tripId}/events`).then(setEvents, fail);
  }, [tripId, fail]);
  useEffect(() => {
    setJournal(null);
    loadEvents();
  }, [loadEvents]);

  async function addEvent(e: FormEvent) {
    e.preventDefault();
    setError("");
    const f = form;
    const needsPoi = f.type === "slot_done" || f.type === "slot_skipped";
    const text = f.text.trim();
    if (needsPoi && !f.poiId) return setError("Chọn địa điểm cho sự kiện đã đi / bỏ.");
    if (f.type === "note" && !text) return setError("Nhập nội dung ghi chú.");
    if (f.type === "expense" && !(f.amount !== "" && Number(f.amount) >= 0)) return setError("Nhập số tiền (VND).");
    // Chỉ gửi trường có nội dung; không bao giờ gửi toạ độ (server cũng từ chối lat/lon trong payload).
    const payload = f.type === "note" ? { text } : f.type === "slot_skipped" ? (text ? { reason: text } : {})
      : f.type === "expense" ? { category: f.category, ...(text ? { label: text } : {}) } : {};
    const body = {
      occurred_at: localIso(), day_index: f.day, event_type: f.type, payload,
      ...(f.poiId && f.type !== "note" ? { poi_id: f.poiId } : {}),
      ...(f.type === "expense" ? { amount_vnd: Math.round(Number(f.amount)) } : {}),
    };
    setBusy("event");
    try {
      await api(`/trips/${tripId}/events`, { json: body });
      setForm({ ...f, text: "", amount: "" });
      loadEvents();
    } catch (err) {
      fail(err);
    } finally {
      setBusy("");
    }
  }

  async function summarize(scope: "day" | "trip") {
    setError("");
    setJournal(null);
    setBusy(scope);
    try {
      setJournal(await api<Journal>(`/trips/${tripId}/journal`, { json: scope === "day" ? { scope, day_index: day, lang } : { scope, lang } }));
    } catch (err) {
      fail(err);
    } finally {
      setBusy("");
    }
  }

  if (trips && trips.length === 0)
    return (
      <main className="page">
        <p className="card">
          Chưa có chuyến đi. Lập lịch trình ở tab “Lịch trình”, hoặc nạp log mẫu:{" "}
          <code>python scripts/load_trip_events.py evals/uc09/fixtures/trip_3days.json --user {user.user_id}</code>
        </p>
      </main>
    );

  const days = [...new Set(events.map((e) => e.day_index))].sort((a, b) => a - b);
  const saved = journal?.tokens_before && journal.tokens_after ? 1 - journal.tokens_after / journal.tokens_before : null;
  return (
    <main className="page">
      <section className="card">
        <label>
          Chuyến đi
          <select value={tripId} onChange={(e) => setTripId(e.target.value)}>
            {trips?.map((t) => (
              <option key={t.trip_id} value={t.trip_id}>
                {t.trip_id} · {t.start_date ? `${t.start_date} → ${t.end_date}` : t.created_at.slice(0, 10)}
              </option>
            ))}
          </select>
        </label>
      </section>

      <form className="card" onSubmit={addEvent}>
        <fieldset className="grid" disabled={busy !== ""}>
          <legend>Thêm sự kiện</legend>
          <label>
            Loại
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as EventType })}>
              {(["slot_done", "slot_skipped", "note", "expense"] as const).map((t) => <option key={t} value={t}>{LABEL[t]}</option>)}
            </select>
          </label>
          <label>
            Ngày thứ
            <select value={form.day} onChange={(e) => setForm({ ...form, day: Number(e.target.value) })}>
              {[0, 1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d === 0 ? "0 (trước chuyến)" : d}</option>)}
            </select>
          </label>
          {form.type !== "note" && (
            <label className="wide">
              Địa điểm {form.type === "expense" && <small>(tuỳ chọn)</small>}
              <select value={form.poiId} onChange={(e) => setForm({ ...form, poiId: e.target.value })}>
                <option value="">(không chọn)</option>
                {pois.map((p) => <option key={p.poi_id} value={p.poi_id}>{p.name_vi}</option>)}
              </select>
            </label>
          )}
          {form.type === "expense" && (
            <>
              <label>
                Số tiền (VND)
                <input type="number" min={0} value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
              </label>
              <label>
                Nhóm
                <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  {Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
            </>
          )}
          {form.type !== "slot_done" && (
            <label className="wide">
              {form.type === "note" ? "Ghi chú" : form.type === "slot_skipped" ? "Lý do bỏ" : "Mô tả"}
              <input value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
            </label>
          )}
          <button className="wide primary" type="submit" disabled={!tripId}>{busy === "event" ? "Đang lưu…" : "Lưu sự kiện"}</button>
        </fieldset>
      </form>

      <section className="card">
        <h2>Sự kiện ({events.length})</h2>
        {days.length === 0 && <p className="muted">Chưa có sự kiện nào.</p>}
        {days.map((d) => (
          <div key={d} className="day">
            <h3>{d === 0 ? "Trước chuyến" : `Ngày ${d}`}</h3>
            <ul className="events">
              {events.filter((e) => e.day_index === d).map((e) => (
                <li key={e.event_id}>
                  <span className="tag">{LABEL[e.event_type]}</span> {e.occurred_at.slice(11, 16)} · {describe(e)}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className="card">
        <h2>Nhật ký</h2>
        <div className="row">
          <select value={day} onChange={(e) => setDay(Number(e.target.value))} aria-label="Ngày">
            {[0, 1, 2, 3, 4, 5].map((d) => <option key={d} value={d}>{d === 0 ? "Trước chuyến" : `Ngày ${d}`}</option>)}
          </select>
          <select value={lang} onChange={(e) => setLang(e.target.value as "vi" | "en")} aria-label="Ngôn ngữ">
            <option value="vi">Tiếng Việt</option>
            <option value="en">English</option>
          </select>
          <button type="button" onClick={() => summarize("day")} disabled={!tripId || busy !== ""}>
            {busy === "day" ? "Đang viết…" : "Tóm tắt ngày"}
          </button>
          <button type="button" className="primary" onClick={() => summarize("trip")} disabled={!tripId || busy !== ""}>
            {busy === "trip" ? "Đang tóm tắt…" : "Tóm tắt cả chuyến"}
          </button>
        </div>
        {busy === "trip" && <p className="muted small">Tóm tắt từng ngày trước, rồi tóm tắt chuyến từ các tóm tắt ngày…</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {journal && (
          <div className="journal">
            <h3>{journal.scope === "trip" ? "Tóm tắt cả chuyến" : journal.day_index === 0 ? "Trước chuyến" : `Ngày ${journal.day_index}`}</h3>
            <p>{journal.content.summary}</p>
            {journal.content.highlights.length > 0 && (
              <ul>
                {journal.content.highlights.map((h, i) => (
                  <li key={i}>
                    {h.text} <small>{h.event_ids ? `(${h.event_ids.length} sự kiện)` : `(ngày ${h.day_indexes?.join(", ")})`}</small>
                  </li>
                ))}
              </ul>
            )}
            <div className="stats">
              <div><small>Tổng chi (tool sum_expenses)</small><b>{vnd(journal.total_spent_vnd)}</b></div>
              <div>
                <small>Token prompt {journal.scope === "trip" ? "trước → sau khi nén" : "(sự kiện thô)"}</small>
                <b>
                  {journal.tokens_before ?? "—"}
                  {journal.scope === "trip" && ` → ${journal.tokens_after ?? "—"}`}
                  {saved !== null && ` (giảm ${Math.round(saved * 100)}%)`}
                </b>
              </div>
            </div>
            <p className="muted small">{journal.event_ids.length} sự kiện · run_id <code>{journal.run_id}</code></p>
          </div>
        )}
      </section>
    </main>
  );
}
