import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, resume, type ApiError, type Decision, type RunRow, type Slot, type TraceEvent, type TripDetail } from "../api";
import type { Shell } from "../App";
import AgentStream from "../components/AgentStream";
import ApprovalCard from "../components/ApprovalCard";
import MapView, { DAY_COLORS } from "../MapView";
import { ClaimBadge, Empty, go, INTEREST, localIso, Photo, Skeleton, vnd } from "../ui";
import { STATUS } from "./Plan";

const TABS = [["plan", "Lịch trình"], ["review", "Review"], ["claims", "Kiểm chứng"], ["journal", "Nhật ký"], ["trace", "Trace"]] as const;
type Tab = (typeof TABS)[number][0];
const REVIEWER = { local_expert: "Chuyên gia địa phương", budget: "Kiểm ngân sách", safety: "An toàn" };
const SEVERITY = { low: "thấp", medium: "trung bình", high: "cao" };
const PACE = { relaxed: "Thong thả", moderate: "Vừa phải", packed: "Dày đặc" };

export default function TripPage({ id, run, shell }: { id: string; run: string | null; shell: Shell }) {
  const [d, setD] = useState<TripDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("plan");
  const [sending, setSending] = useState(false);
  const [stream, setStream] = useState(run);
  const [resumes, setResumes] = useState(0); // P1 trả lại run_id cũ khi resume: đổi key để mở lại stream

  const load = useCallback(() => {
    api<TripDetail>(`/ui/trips/${id}`).then((x) => {
      setD(x);
      if (x.running) setStream((s) => s ?? x.runs[0].run_id); // tải lại trang lúc agent đang chạy
    }, (e: ApiError) => {
      if (e.status === 401) shell.askLogin();
      setError(e.message);
    });
  }, [id, shell.askLogin]);
  useEffect(load, [load, shell.user]);
  useEffect(() => setStream(run), [run]);

  async function decide(decision: Decision, response: unknown) {
    if (!d?.pending) return;
    setSending(true);
    setError("");
    try {
      const r = await resume(id, { approval_id: d.pending.approval_id, decision, response });
      setD({ ...d, pending: null });
      setStream(r.run_id);
      setResumes((n) => n + 1);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSending(false);
    }
  }

  if (error && !d) return <div className="wrap page"><Empty title="Không mở được chuyến đi"><p className="muted">{error}</p><a href="#/trips">Về danh sách</a></Empty></div>;
  if (!d) return <div className="wrap page"><Skeleton rows={5} /></div>;

  const claimsOf = (slot: string) => d.claims.filter((c) => c.target_id === slot);
  return (
    <div className="wrap page">
      <p className="crumbs"><a href="#/trips">Chuyến đi</a> / {STATUS[d.trip.status]}</p>
      <h1>{d.profile?.start_date ? `Huế, ${d.profile.start_date} đến ${d.profile.end_date}` : "Chuyến đi mới"}</h1>
      <Profile d={d} />
      {error && <p className="error" role="alert">{error}</p>}
      {d.pending && d.pending.kind !== "itinerary_approval" && <ApprovalCard payload={d.pending} busy={sending} onSubmit={decide} />}
      {stream && <AgentStream key={`${stream}-${resumes}`} runId={stream} onInterrupt={load} onDone={load} onError={load} />}

      {d.itinerary ? (
        <>
          {d.pending?.kind === "itinerary_approval" && <p className="note"><b>Lịch trình đang chờ bạn duyệt.</b> <a href="#" onClick={(e) => { e.preventDefault(); document.getElementById("approve")?.scrollIntoView({ behavior: "smooth" }); }}>Đến bước duyệt</a></p>}
          <div className="tabs" role="tablist">
            {TABS.filter(([v]) => v !== "review" || d.review.reports.length > 0).map(([v, label]) => <button key={v} role="tab" aria-selected={tab === v} onClick={() => setTab(v)}>{label}</button>)}
          </div>
          {tab === "plan" && <PlanTab d={d} shell={shell} claimsOf={claimsOf} reload={load} tripId={id} />}
          {tab === "review" && <ReviewTab d={d} />}
          {tab === "claims" && <ClaimsTab d={d} />}
          {tab === "journal" && <JournalTab d={d} tripId={id} reload={load} llm={shell.llm} />}
          {tab === "trace" && <TraceTab runs={d.runs} />}
          {d.pending?.kind === "itinerary_approval" && <div id="approve"><ApprovalCard payload={d.pending} busy={sending} onSubmit={decide} /></div>}
        </>
      ) : !stream && !d.pending && <Empty title="Chưa có lịch trình"><p className="muted">Chuyến đi này chưa tới bước lập lịch.</p></Empty>}
      <DeleteTrip id={id} />
    </div>
  );
}

function Profile({ d }: { d: TripDetail }) {
  const p = d.profile;
  if (!p) return null;
  const items = [
    p.adults && `${p.adults} người lớn`,
    p.children.length > 0 && `Trẻ em ${p.children.map((c) => c.age).join(", ")} tuổi`,
    p.budget_total_vnd && vnd(p.budget_total_vnd),
    p.pace && PACE[p.pace],
    ...p.interests.map((x) => INTEREST[x] ?? x),
    p.mobility_notes,
    ...p.hard_constraints,
  ].filter(Boolean);
  return <div className="profile">{items.map((x) => <span key={String(x)} className="tag">{x}</span>)}</div>;
}

function PlanTab({ d, shell, claimsOf, reload, tripId }: { d: TripDetail; shell: Shell; claimsOf: (s: string) => TripDetail["claims"]; reload: () => void; tripId: string }) {
  const it = d.itinerary!;
  const days = [...new Set(it.slots.map((s) => s.day_index))];
  const canLog = d.trip.status === "approved";
  async function mark(s: Slot, type: "slot_done" | "slot_skipped") {
    await api(`/trips/${tripId}/events`, { json: { occurred_at: localIso(), day_index: s.day_index, event_type: type, slot_id: s.slot_id, payload: {} } });
    reload();
  }
  return (
    <div className="plan-grid">
      <div>
        <p className={it.status === "failed_validation" ? "warn" : "ok"}>
          {it.status === "failed_validation" ? `Còn vi phạm sau ${it.planner_rounds} vòng lập lịch` : `Đã qua validator sau ${it.planner_rounds} vòng`}
        </p>
        <p>Chi phí đã có giá: <b>{it.total_cost_vnd == null ? "chưa có" : vnd(it.total_cost_vnd)}</b>{it.has_unpriced_item ? ", còn các mục chưa có giá" : ""}</p>
        {it.violations.map((v) => <p key={v.violation_id} className="warn small">[{v.rule}] {v.message}</p>)}
        {days.map((day) => {
          const slots = it.slots.filter((s) => s.day_index === day);
          return (
            <section key={day} className="day">
              <h3><span className="day-mark" style={{ background: DAY_COLORS[(day - 1) % DAY_COLORS.length] }}>{day}</span>{slots[0].slot_date}</h3>
              {slots.map((s) => {
                const poi = shell.pois.find((p) => p.poi_id === s.poi_id);
                const claims = claimsOf(s.slot_id);
                const priceWrong = claims.some((c) => c.claim_type === "price" && c.status === "contradicted");
                return (
                  <div key={s.slot_id} className={`slot ${s.progress ?? ""}`}>
                    <div className="slot-photo">{poi && <Photo poi={poi} />}</div>
                    <div>
                      <p className="slot-time">{s.start_time} - {s.end_time}</p>
                      <p className="slot-name">{s.poi_id ? <a href={`#/poi/${s.poi_id}`}>{s.name_vi}</a> : "Tự do"}</p>
                      <p className="small">{s.activity}</p>
                      <div className="tags">
                        {s.travel_minutes_from_prev != null && <span className="tag">{s.travel_minutes_from_prev} phút di chuyển</span>}
                        {s.cost_vnd != null && !priceWrong && <span className="tag">{vnd(s.cost_vnd)}</span>}
                        {s.cost_source === "unverified" && <span className="tag warn">chưa có giá</span>}
                        {s.hours_status === "unverified" && <span className="tag warn">giờ chưa xác minh</span>}
                        {claims.filter((c) => c.status !== "unverified").map((c, i) => <ClaimBadge key={i} c={c} />)}
                      </div>
                      {s.note && <p className="muted tiny">{s.note}</p>}
                      {canLog && (s.progress === "planned" ? (
                        <div className="slot-actions">
                          <button onClick={() => mark(s, "slot_done")}>Đã đi</button>
                          <button onClick={() => mark(s, "slot_skipped")}>Bỏ qua</button>
                        </div>
                      ) : <p className="small"><b>{s.progress === "done" ? "Đã đi" : "Đã bỏ qua"}</b></p>)}
                    </div>
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>
      <div className="map-stick">
        <MapView slots={it.slots} pois={[]} />
        <p className="muted tiny">Đường nét đứt nối các điểm theo thứ tự tham quan, không phải đường đi thực tế.</p>
      </div>
    </div>
  );
}

function ReviewTab({ d }: { d: TripDetail }) {
  const { reports, coordination } = d.review;
  if (!reports.length) return <Empty title="Chưa có kết quả review" />;
  const name = (ref: string | null) => d.itinerary?.slots.find((s) => s.slot_id === ref)?.name_vi;
  return (
    <div className="review">
      {reports.map((r) => (
        <section key={r.report_id} className="reviewer">
          <h3>{REVIEWER[r.reviewer]} <small className="muted">vòng {r.round}</small></h3>
          <p className={r.verdict === "approve" ? "ok" : "warn"}>{r.verdict === "approve" ? "Chấp thuận" : "Yêu cầu sửa"}</p>
          {r.findings.length === 0 && <p className="muted small">Không có phát hiện nào.</p>}
          {r.findings.map((f, i) => (
            <div key={i} className="finding">
              <p><b>Mức {SEVERITY[f.severity]}</b>{name(f.slot_ref) && `, ${name(f.slot_ref)}`}</p>
              <p className="small">{f.message}</p>
              {f.suggestion && <p className="muted small">Gợi ý: {f.suggestion}</p>}
            </div>
          ))}
        </section>
      ))}
      <details className="coordination">
        <summary>Trao đổi giữa các agent ({coordination.length} thông điệp)</summary>
        <ol className="timeline">{coordination.map((c, i) => <li key={i}><time>{c.ts.slice(11, 19)}</time> <b>{c.from}</b> tới <b>{c.to}</b>: {c.message}</li>)}</ol>
      </details>
    </div>
  );
}

function ClaimsTab({ d }: { d: TripDetail }) {
  const count = (s: string) => d.claims.filter((c) => c.status === s).length;
  if (!d.claims.length) return <Empty title="Chưa có dữ kiện được kiểm" />;
  return (
    <div>
      <p><b>{count("verified")}</b> đã xác minh, <b>{count("unverified")}</b> chưa xác minh, <b>{count("contradicted")}</b> đã sửa theo nguồn.</p>
      <p className="muted small">Dữ liệu chưa có nguồn được gắn nhãn chưa xác minh, hệ thống không điền giá trị ước đoán.</p>
      <div className="tags">{d.claims.map((c, i) => <ClaimBadge key={i} c={c} />)}</div>
    </div>
  );
}

function JournalTab({ d, tripId, reload, llm }: { d: TripDetail; tripId: string; reload: () => void; llm: boolean }) {
  const days = [...new Set(d.itinerary!.slots.map((s) => s.day_index))];
  const [day, setDay] = useState(days[0]);
  const [kind, setKind] = useState<"expense" | "note">("expense");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [lang, setLang] = useState<"vi" | "en">("vi");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError("");
    const body = kind === "expense"
      ? { event_type: "expense", amount_vnd: Number(amount), payload: { category: "other", ...(note ? { label: note } : {}) } }
      : { event_type: "note", payload: { text: note } };
    try {
      await api(`/trips/${tripId}/events`, { json: { occurred_at: localIso(), day_index: day, ...body } });
      setAmount("");
      setNote("");
      reload();
    } catch (err) {
      setError((err as ApiError).message);
    }
  }
  async function build(json: object) {
    setBusy(true);
    setError("");
    try {
      await api(`/trips/${tripId}/journal`, { json: { ...json, lang } });
      reload();
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  const trip = d.journal.find((j) => j.scope === "trip" && j.lang === lang);
  const dayJournals = d.journal.filter((j) => j.scope === "day" && j.lang === lang);
  return (
    <div className="journal">
      <form className="journal-form" onSubmit={add}>
        <h3>Ghi vào nhật ký</h3>
        <label>Ngày
          <select value={day} onChange={(e) => setDay(Number(e.target.value))}>{days.map((x) => <option key={x} value={x}>Ngày {x}</option>)}</select>
        </label>
        <label>Loại
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="expense">Chi tiêu</option><option value="note">Ghi chú</option></select>
        </label>
        {kind === "expense" && <label>Số tiền (VND)<input type="number" min={0} required value={amount} onChange={(e) => setAmount(e.target.value)} /></label>}
        <label>Nội dung<input maxLength={500} required={kind === "note"} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button>Thêm</button>
        <p className="muted tiny">Đã ghi {d.events.length} sự kiện.</p>
      </form>
      <div>
        <div className="journal-head">
          <div className="seg">
            <button className="primary" disabled={busy} onClick={() => build({ scope: "day", day_index: day })}>Tóm tắt ngày {day}</button>
            <button disabled={busy} onClick={() => build({ scope: "trip" })}>Tóm tắt cả chuyến</button>
          </div>
          <div className="seg" role="group" aria-label="Ngôn ngữ nhật ký">
            <button aria-pressed={lang === "vi"} onClick={() => setLang("vi")}>Tiếng Việt</button>
            <button aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
          </div>
        </div>
        {!llm && <p className="note small">Tóm tắt nhật ký cần khoá LLM. Ghi sự kiện vẫn dùng được.</p>}
        {busy && <p className="muted small">Đang tóm tắt...</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {!trip && dayJournals.length === 0 && <Empty title="Chưa có nhật ký"><p className="muted">Đánh dấu điểm đã đi, ghi chi tiêu rồi bấm tóm tắt.</p></Empty>}
        {trip && (
          <section className="trip-summary">
            <p className="big">{vnd(trip.total_spent_vnd)}</p>
            <p>{trip.content.summary}</p>
            {trip.content.highlights.map((h) => <p key={h.text} className="small">{h.text}</p>)}
            {trip.tokens_before != null && <p className="muted tiny">Token khi tóm tắt theo tầng: {trip.tokens_before} xuống {trip.tokens_after}.</p>}
          </section>
        )}
        {dayJournals.map((j) => (
          <section key={j.day_index} className="journal-day">
            <p><b>Ngày {j.day_index}: {vnd(j.total_spent_vnd)}</b></p>
            <p className="small">{j.content.summary}</p>
            {j.content.highlights.map((h) => <p key={h.text} className="small">{h.text}</p>)}
          </section>
        ))}
      </div>
    </div>
  );
}

function TraceTab({ runs }: { runs: RunRow[] }) {
  const [events, setEvents] = useState<Record<string, TraceEvent[]>>({});
  const open = (id: string) => { if (!events[id]) api<TraceEvent[]>(`/runs/${id}/trace`).then((e) => setEvents((x) => ({ ...x, [id]: e }))); };
  return (
    <div className="trace-list">
      {runs.map((r) => (
        <details key={r.run_id} onToggle={(e) => e.currentTarget.open && open(r.run_id)}>
          <summary><b>{r.uc}</b> {r.status}, <code>{r.run_id}</code>{r.tokens_in + r.tokens_out > 0 && `, ${r.tokens_in + r.tokens_out} token`}{r.latency_ms != null && `, ${r.latency_ms} ms`}</summary>
          <ol className="timeline">
            {events[r.run_id]?.map((e) => <li key={e.seq}><b>{e.node}</b> {e.kind}{e.name && `: ${e.name}`}{e.duration_ms != null && `, ${e.duration_ms} ms`}{e.error && `, ${e.error}`}</li>)}
          </ol>
        </details>
      ))}
    </div>
  );
}

function DeleteTrip({ id }: { id: string }) {
  const [sure, setSure] = useState(false);
  async function remove() {
    await api(`/ui/trips/${id}`, { method: "DELETE" });
    go("/trips");
  }
  return (
    <div className="danger-zone">
      {sure ? (
        <>
          <span>Xoá hẳn lịch trình, nhật ký và trace của chuyến này?</span>
          <button className="danger" onClick={remove}>Xoá</button>
          <button className="ghost" onClick={() => setSure(false)}>Giữ lại</button>
        </>
      ) : <button className="ghost" onClick={() => setSure(true)}>Xoá dữ liệu chuyến đi</button>}
    </div>
  );
}
