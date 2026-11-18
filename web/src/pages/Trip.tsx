import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, resume, type ApiError, type Decision, type RunRow, type Slot, type TraceEvent, type TripDetail } from "../api";
import type { Shell } from "../App";
import AgentStream from "../components/AgentStream";
import ApprovalCard from "../components/ApprovalCard";
import MapView, { DAY_COLORS } from "../MapView";
import { getLang, poiName, t } from "../i18n";
import { distanceM, nearestPoi, useSessionLocation } from "../location";
import { ClaimBadge, Empty, go, interest, localIso, Photo, Skeleton, vnd } from "../ui";
import { status } from "./Plan";

const TABS = [["plan", ["Lịch trình", "Itinerary"]], ["review", ["Review", "Review"]], ["claims", ["Kiểm chứng", "Fact check"]],
  ["journal", ["Nhật ký", "Journal"]], ["trace", ["Trace", "Trace"]]] as const;
type Tab = (typeof TABS)[number][0];
const REVIEWER = { local_expert: ["Chuyên gia địa phương", "Local expert"], budget: ["Kiểm ngân sách", "Budget check"], safety: ["An toàn", "Safety"] } as const;
const SEVERITY = { low: ["thấp", "low"], medium: ["trung bình", "medium"], high: ["cao", "high"] } as const;

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
      // quay lại trang lúc agent đang chạy nền: nối lại đúng lượt đang chạy (runs[0] có thể là lượt kiểm chứng vừa xong)
      const live = x.runs.find((r) => r.status === "running");
      if (live) setStream((s) => s ?? live.run_id);
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

  if (error && !d) return <div className="wrap page"><Empty title={t("Không mở được chuyến đi", "Could not open this trip")}><p className="muted">{error}</p><a href="#/trips">{t("Về danh sách", "Back to list")}</a></Empty></div>;
  if (!d) return <div className="wrap page"><Skeleton rows={5} /></div>;

  const claimsOf = (slot: string) => d.claims.filter((c) => c.target_id === slot);
  const lastPlan = d.runs.find((r) => r.uc === "UC-01" || r.uc === "UC-02");
  const planFailed = lastPlan?.status === "failed" && !d.running && !d.pending;
  async function planAgain() {
    setError("");
    try {
      setStream((await api<{ run_id: string }>(`/trips/${id}/plan?background=true`, { method: "POST" })).run_id);
      setResumes((n) => n + 1);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }
  return (
    <div className="wrap page">
      <p className="crumbs"><a href="#/trips">{t("Chuyến đi", "Trips")}</a> / {status(d.trip.status)}</p>
      <h1>{d.profile?.start_date ? t(`Huế, ${d.profile.start_date} đến ${d.profile.end_date}`, `Hue, ${d.profile.start_date} to ${d.profile.end_date}`) : t("Chuyến đi mới", "New trip")}</h1>
      <Profile d={d} />
      {error && <p className="error" role="alert">{error}</p>}
      {d.pending && d.pending.kind !== "itinerary_approval" && <ApprovalCard payload={d.pending} busy={sending} onSubmit={decide} />}
      {planFailed && (
        <div className="note warn-note" role="alert">
          <b>{t("Lượt lập lịch gần nhất bị lỗi.", "The last planning run failed.")}</b>{" "}
          {d.itinerary
            ? t("Lịch trình hiện tại vẫn giữ nguyên; bạn có thể gửi lại yêu cầu sửa bên dưới. Chi tiết ở tab Trace.",
              "Your current itinerary is unchanged; you can resend the change request below. Details in the Trace tab.")
            : lastPlan?.uc === "UC-02" && <button className="primary" onClick={planAgain}>{t("Lập lịch lại", "Plan again")}</button>}
        </div>
      )}
      {stream && <AgentStream key={`${stream}-${resumes}`} runId={stream} onInterrupt={load} onDone={load} onError={load} />}

      {d.itinerary ? (
        <>
          {d.pending?.kind === "itinerary_approval" && <p className="note"><b>{t("Lịch trình đang chờ bạn duyệt.", "Your itinerary is waiting for approval.")}</b> <a href="#" onClick={(e) => { e.preventDefault(); document.getElementById("approve")?.scrollIntoView({ behavior: "smooth" }); }}>{t("Đến bước duyệt", "Go to approval")}</a></p>}
          <div className="tabs" role="tablist">
            {TABS.filter(([v]) => v !== "review" || d.review.reports.length > 0).map(([v, label]) => <button key={v} role="tab" aria-selected={tab === v} onClick={() => setTab(v)}>{t(label[0], label[1])}</button>)}
          </div>
          {tab === "plan" && <PlanTab d={d} shell={shell} claimsOf={claimsOf} reload={load} tripId={id} />}
          {tab === "review" && <ReviewTab d={d} />}
          {tab === "claims" && <ClaimsTab d={d} />}
          {tab === "journal" && <JournalTab d={d} tripId={id} reload={load} llm={shell.llm} />}
          {tab === "trace" && <TraceTab runs={d.runs} />}
          {d.pending?.kind === "itinerary_approval" && <div id="approve"><ApprovalCard payload={d.pending} busy={sending} onSubmit={decide} /></div>}
        </>
      ) : !stream && !d.pending && <Empty title={t("Chưa có lịch trình", "No itinerary yet")}><p className="muted">{t("Chuyến đi này chưa tới bước lập lịch.", "This trip has not reached the planning step.")}</p></Empty>}
      {d.itinerary?.status === "approved" && !d.running && !d.pending && (
        <ReviseTrip id={id} onStarted={(runId) => { setStream(runId); setResumes((n) => n + 1); load(); }} />
      )}
      <DeleteTrip id={id} />
    </div>
  );
}

function Profile({ d }: { d: TripDetail }) {
  const p = d.profile;
  if (!p) return null;
  const items = [
    p.adults && t(`${p.adults} người lớn`, `${p.adults} adult${p.adults > 1 ? "s" : ""}`),
    p.children.length > 0 && t(`Trẻ em ${p.children.map((c) => c.age).join(", ")} tuổi`, `Children aged ${p.children.map((c) => c.age).join(", ")}`),
    p.budget_total_vnd && vnd(p.budget_total_vnd),
    p.pace && interest(p.pace),
    ...p.interests.map(interest),
    p.mobility_notes,
    ...p.hard_constraints,
  ].filter(Boolean);
  return <div className="profile">{items.map((x) => <span key={String(x)} className="tag">{x}</span>)}</div>;
}

/** Sau mỗi sự kiện (đã đi, bỏ qua, chi tiêu, ghi chú) tóm tắt lại nhật ký ngày đó ở nền (UC-09), gộp các lần bấm
 * liên tiếp trong 2,5 giây thành 1 lần gọi LLM. Hẹn giờ ở cấp module nên rời trang vẫn chạy. */
const journalTimers = new Map<string, ReturnType<typeof setTimeout>>();
function refreshJournal(tripId: string, day: number, done: () => void) {
  const key = `${tripId}:${day}`;
  clearTimeout(journalTimers.get(key));
  journalTimers.set(key, setTimeout(() => {
    journalTimers.delete(key);
    api(`/trips/${tripId}/journal`, { json: { scope: "day", day_index: day, lang: getLang() } }).then(done, () => undefined);
  }, 2500));
}

const EVENT: Record<string, [string, string]> = {
  slot_done: ["Đã đi", "Visited"], slot_skipped: ["Bỏ qua", "Skipped"], expense: ["Chi tiêu", "Expense"], note: ["Ghi chú", "Note"],
  photo_meta: ["Ảnh", "Photo"], adjustment: ["Điều chỉnh", "Adjustment"],
};

function PlanTab({ d, shell, claimsOf, reload, tripId }: { d: TripDetail; shell: Shell; claimsOf: (s: string) => TripDetail["claims"]; reload: () => void; tripId: string }) {
  const it = d.itinerary!;
  const days = [...new Set(it.slots.map((s) => s.day_index))];
  const canLog = d.trip.status === "approved";
  async function mark(s: Slot, type: "slot_done" | "slot_skipped") {
    await api(`/trips/${tripId}/events`, { json: { occurred_at: localIso(), day_index: s.day_index, event_type: type, slot_id: s.slot_id, payload: {} } });
    reload();
    if (shell.llm) refreshJournal(tripId, s.day_index, reload);
  }
  // Vị trí chỉ để vẽ chấm "bạn ở đây" và tìm điểm gần nhất ngay trên trình duyệt; không gửi lên máy chủ.
  const here = useSessionLocation();
  const stops = it.slots.flatMap((s) => (s.lat != null && s.lon != null ? [{ ...s, lat: s.lat, lon: s.lon }] : []));
  const nearest = nearestPoi(here.coords, stops);
  return (
    <div className="plan-grid">
      <div>
        <p className={it.status === "failed_validation" ? "warn" : "ok"}>
          {it.status === "failed_validation"
            ? t(`Còn vi phạm sau ${it.planner_rounds} vòng lập lịch`, `Violations remain after ${it.planner_rounds} planning rounds`)
            : t(`Đã qua validator sau ${it.planner_rounds} vòng`, `Passed the validator after ${it.planner_rounds} rounds`)}
        </p>
        <p>{t("Chi phí đã có giá", "Priced costs")}: <b>{it.total_cost_vnd == null ? t("chưa có", "none yet") : vnd(it.total_cost_vnd)}</b>{it.has_unpriced_item ? t(", còn các mục chưa có giá", ", some items have no price yet") : ""}</p>
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
                      <p className="slot-name">{s.poi_id ? <a href={`#/poi/${s.poi_id}`}>{poiName(s)}</a> : t("Tự do", "Free time")}</p>
                      <p className="small">{s.activity}</p>
                      <div className="tags">
                        {s.travel_minutes_from_prev != null && <span className="tag">{s.travel_minutes_from_prev} {t("phút di chuyển", "min travel")}</span>}
                        {s.cost_vnd != null && !priceWrong && <span className="tag">{vnd(s.cost_vnd)}</span>}
                        {s.cost_source === "unverified" && <span className="tag warn">{t("chưa có giá", "no price yet")}</span>}
                        {s.hours_status === "unverified" && <span className="tag warn">{t("giờ chưa xác minh", "hours not verified")}</span>}
                        {claims.filter((c) => c.status !== "unverified").map((c, i) => <ClaimBadge key={i} c={c} />)}
                      </div>
                      {s.note && <p className="muted tiny">{s.note}</p>}
                      {canLog && (s.progress === "planned" ? (
                        <div className="slot-actions">
                          <button onClick={() => mark(s, "slot_done")}>{t("Đã đi", "Visited")}</button>
                          <button onClick={() => mark(s, "slot_skipped")}>{t("Bỏ qua", "Skip")}</button>
                        </div>
                      ) : <p className="small"><b>{s.progress === "done" ? t("Đã đi", "Visited") : t("Đã bỏ qua", "Skipped")}</b></p>)}
                    </div>
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>
      <div className="map-stick">
        <div className="here-bar">
          {here.coords && nearest ? (
            <>
              <span className="small">{t("Gần bạn nhất trong lịch", "Closest stop to you")}: <b>{poiName(nearest)}</b>{" "}
                ({(distanceM(here.coords, nearest) / 1000).toFixed(1)} km {t("đường chim bay", "as the crow flies")})</span>
              <button className="ghost" onClick={here.clear}>{t("Tắt vị trí", "Turn off location")}</button>
            </>
          ) : (
            <button onClick={here.request} disabled={here.asking}>{here.asking ? t("Đang lấy vị trí...", "Getting location...") : t("Lấy vị trí hiện tại", "Use my current location")}</button>
          )}
          {here.error && <p className="warn small" role="alert">{here.error}</p>}
        </div>
        <MapView slots={it.slots} pois={[]} here={here.coords} />
        <p className="muted tiny">{t("Đường liền là đường đi thực tế bằng ô tô (định tuyến OSRM trên dữ liệu OSM). Nét đứt: chưa lấy được tuyến, chỉ nối thẳng theo thứ tự tham quan.", "Solid lines are real driving routes (OSRM routing on OSM data). Dashed: route unavailable, straight line in visiting order.")} {t("Vị trí của bạn chỉ hiện trên máy này, không gửi lên máy chủ.", "Your location stays on this device and is never sent to the server.")}</p>
      </div>
    </div>
  );
}

function ReviewTab({ d }: { d: TripDetail }) {
  const { reports, coordination } = d.review;
  if (!reports.length) return <Empty title={t("Chưa có kết quả review", "No review results yet")} />;
  const name = (ref: string | null) => { const s = d.itinerary?.slots.find((x) => x.slot_id === ref); return s && poiName(s); };
  return (
    <div className="review">
      {reports.map((r) => (
        <section key={r.report_id} className="reviewer">
          <h3>{t(REVIEWER[r.reviewer][0], REVIEWER[r.reviewer][1])} <small className="muted">{t("vòng", "round")} {r.round}</small></h3>
          <p className={r.verdict === "approve" ? "ok" : "warn"}>{r.verdict === "approve" ? t("Chấp thuận", "Approved") : t("Yêu cầu sửa", "Changes requested")}</p>
          {r.findings.length === 0 && <p className="muted small">{t("Không có phát hiện nào.", "No findings.")}</p>}
          {r.findings.map((f, i) => (
            <div key={i} className="finding">
              <p><b>{t("Mức", "Severity")} {t(SEVERITY[f.severity][0], SEVERITY[f.severity][1])}</b>{name(f.slot_ref) && `, ${name(f.slot_ref)}`}</p>
              <p className="small">{f.message}</p>
              {f.suggestion && <p className="muted small">{t("Gợi ý", "Suggestion")}: {f.suggestion}</p>}
            </div>
          ))}
        </section>
      ))}
      <details className="coordination">
        <summary>{t("Trao đổi giữa các agent", "Agent coordination")} ({coordination.length} {t("thông điệp", "messages")})</summary>
        <ol className="timeline">{coordination.map((c, i) => <li key={i}><time>{c.ts.slice(11, 19)}</time> <b>{c.from}</b> {t("tới", "to")} <b>{c.to}</b>: {c.message}</li>)}</ol>
      </details>
    </div>
  );
}

function ClaimsTab({ d }: { d: TripDetail }) {
  const count = (s: string) => d.claims.filter((c) => c.status === s).length;
  if (!d.claims.length) return <Empty title={t("Chưa có dữ kiện được kiểm", "No facts checked yet")} />;
  return (
    <div>
      <p><b>{count("verified")}</b> {t("đã xác minh", "verified")}, <b>{count("unverified")}</b> {t("chưa xác minh", "not verified")}, <b>{count("contradicted")}</b> {t("đã sửa theo nguồn", "corrected from source")}.</p>
      <p className="muted small">{t("Dữ liệu chưa có nguồn được gắn nhãn chưa xác minh, hệ thống không điền giá trị ước đoán.", "Data without a source is labelled not verified; the system never fills in guessed values.")}</p>
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
  const [lang, setLang] = useState<"vi" | "en">(getLang());
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
      if (llm) refreshJournal(tripId, day, reload);
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
        <h3>{t("Ghi vào nhật ký", "Add to journal")}</h3>
        <label>{t("Ngày", "Day")}
          <select value={day} onChange={(e) => setDay(Number(e.target.value))}>{days.map((x) => <option key={x} value={x}>{t("Ngày", "Day")} {x}</option>)}</select>
        </label>
        <label>{t("Loại", "Type")}
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="expense">{t("Chi tiêu", "Expense")}</option><option value="note">{t("Ghi chú", "Note")}</option></select>
        </label>
        {kind === "expense" && <label>{t("Số tiền (VND)", "Amount (VND)")}<input type="number" min={0} required value={amount} onChange={(e) => setAmount(e.target.value)} /></label>}
        <label>{t("Nội dung", "Details")}<input maxLength={500} required={kind === "note"} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button>{t("Thêm", "Add")}</button>
        <p className="muted tiny">{t(`Đã ghi ${d.events.length} sự kiện.`, `${d.events.length} events logged.`)}{llm && t(" Nhật ký ngày tự tóm tắt lại vài giây sau mỗi sự kiện.", " The day's journal re-summarises a few seconds after each event.")}</p>
        <EventLog d={d} />
      </form>
      <div>
        <div className="journal-head">
          <div className="seg">
            <button className="primary" disabled={busy} onClick={() => build({ scope: "day", day_index: day })}>{t(`Tóm tắt ngày ${day}`, `Summarise day ${day}`)}</button>
            <button disabled={busy} onClick={() => build({ scope: "trip" })}>{t("Tóm tắt cả chuyến", "Summarise whole trip")}</button>
          </div>
          <div className="seg" role="group" aria-label={t("Ngôn ngữ nhật ký", "Journal language")}>
            <button aria-pressed={lang === "vi"} onClick={() => setLang("vi")}>Tiếng Việt</button>
            <button aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
          </div>
        </div>
        {!llm && <p className="note small">{t("Tóm tắt nhật ký cần khoá LLM. Ghi sự kiện vẫn dùng được.", "Journal summaries need an LLM key. Logging events still works.")}</p>}
        {busy && <p className="muted small">{t("Đang tóm tắt...", "Summarising...")}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        {!trip && dayJournals.length === 0 && <Empty title={t("Chưa có nhật ký", "No journal yet")}><p className="muted">{t("Đánh dấu điểm đã đi, ghi chi tiêu rồi bấm tóm tắt.", "Mark visited stops, log expenses, then press summarise.")}</p></Empty>}
        {trip && (
          <section className="trip-summary">
            <p className="big">{vnd(trip.total_spent_vnd)}</p>
            <p>{trip.content.summary}</p>
            {trip.content.highlights.map((h) => <p key={h.text} className="small">{h.text}</p>)}
            {trip.tokens_before != null && <p className="muted tiny">{t(`Token khi tóm tắt theo tầng: ${trip.tokens_before} xuống ${trip.tokens_after}.`, `Tokens with layered summary: ${trip.tokens_before} down to ${trip.tokens_after}.`)}</p>}
          </section>
        )}
        {dayJournals.map((j) => (
          <section key={j.day_index} className="journal-day">
            <p><b>{t("Ngày", "Day")} {j.day_index}: {vnd(j.total_spent_vnd)}</b></p>
            <p className="small">{j.content.summary}</p>
            {j.content.highlights.map((h) => <p key={h.text} className="small">{h.text}</p>)}
          </section>
        ))}
      </div>
    </div>
  );
}

/** Nhật ký sự kiện: cập nhật ngay khi bấm Đã đi / Bỏ qua hoặc ghi chi tiêu, ghi chú (không cần LLM). */
function EventLog({ d }: { d: TripDetail }) {
  if (!d.events.length) return <p className="muted small">{t("Chưa có sự kiện. Bấm Đã đi / Bỏ qua ở tab Lịch trình hoặc ghi chi tiêu, ghi chú ở trên.", "No events yet. Mark stops as Visited / Skip in the Itinerary tab, or log an expense or note above.")}</p>;
  const slotName = (id: string | null) => { const s = d.itinerary?.slots.find((x) => x.slot_id === id); return s ? poiName(s) : ""; };
  return (
    <section className="event-log" aria-label={t("Nhật ký sự kiện", "Event log")}>
      <h3>{t("Nhật ký sự kiện", "Event log")}</h3>
      <ol className="timeline">
        {[...d.events].reverse().map((e) => {
          const label = EVENT[e.event_type];
          const place = poiName(e) || slotName(e.slot_id);
          const text = e.payload?.text ?? e.payload?.label;
          return (
            <li key={e.event_id}>
              <time>{t("Ngày", "Day")} {e.day_index} · {e.occurred_at.slice(11, 16)}</time> <b>{label ? t(...label) : e.event_type}</b>
              {place && `: ${place}`}{e.amount_vnd != null && ` · ${vnd(e.amount_vnd)}`}{text && ` · ${text}`}
            </li>
          );
        })}
      </ol>
    </section>
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

/** Sửa lịch đã duyệt: agent lập lại theo ghi chú (chạy nền), người dùng duyệt lại; từ chối bản mới thì giữ bản cũ. */
function ReviseTrip({ id, onStarted }: { id: string; onStarted: (runId: string) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      onStarted((await api<{ run_id: string }>(`/trips/${id}/revise`, { json: { note: note.trim() } })).run_id);
      setNote("");
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="approval revise" onSubmit={send}>
      <h2>{t("Muốn đổi lịch trình đã duyệt?", "Want to change your approved itinerary?")}</h2>
      <p className="small muted">{t(
        "Agent lập lại theo ghi chú và chạy ngầm, bạn có thể sang trang khác. Xong bạn duyệt lại; từ chối bản mới thì giữ bản hiện tại. Đánh dấu đã đi không chuyển sang bản mới.",
        "The agent replans from your note in the background, so you can leave this page. Approve the new version when it is ready; rejecting it keeps the current one. Visited marks do not carry over.")}</p>
      <label>{t("Điều muốn sửa", "What to change")}
        <textarea rows={3} required minLength={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={t("vd bỏ Lăng Khải Định, thêm nghỉ trưa ngày 2", "e.g. drop the Tomb of Khai Dinh, add a lunch break on day 2")} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="approval-actions">
        <button className="primary" disabled={busy || note.trim().length < 3}>{busy ? t("Đang gửi...", "Sending...") : t("Gửi yêu cầu sửa", "Request changes")}</button>
      </div>
    </form>
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
          <span>{t("Xoá hẳn lịch trình, nhật ký và trace của chuyến này?", "Permanently delete this trip's itinerary, journal and traces?")}</span>
          <button className="danger" onClick={remove}>{t("Xoá", "Delete")}</button>
          <button className="ghost" onClick={() => setSure(false)}>{t("Giữ lại", "Keep")}</button>
        </>
      ) : <button className="ghost" onClick={() => setSure(true)}>{t("Xoá dữ liệu chuyến đi", "Delete trip data")}</button>}
    </div>
  );
}
