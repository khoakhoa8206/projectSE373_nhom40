import { useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type Itinerary, type PlanResult, type Slot, type TraceEvent, type TripProfile, type User } from "./api";
import MapView, { DAY_COLORS } from "./MapView";

const USER_KEY = "tourguide.user";
const NO_SLOTS: Slot[] = [];
const INTERESTS = [["history", "Lịch sử"], ["food", "Ẩm thực"], ["culture", "Văn hoá"], ["nature", "Thiên nhiên"], ["shopping", "Mua sắm"]] as const;

// localStorage chỉ để nhớ người dùng đã chọn; có thể bị chặn (chế độ riêng tư) nên luôn bọc try/catch.
function loadUser(): User | null {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) ?? "null");
  } catch {
    return null;
  }
}

function saveUser(u: User | null) {
  try {
    if (u) localStorage.setItem(USER_KEY, JSON.stringify(u));
    else localStorage.removeItem(USER_KEY);
  } catch {
    /* bỏ qua */
  }
}

const vnd = (n: number) => `${n.toLocaleString("vi-VN")} đ`;
const dayLabel = (d: string) => new Date(`${d}T00:00`).toLocaleDateString("vi-VN", { weekday: "long", day: "2-digit", month: "2-digit" });

function addDays(d: string, n: number) {
  const t = new Date(`${d}T00:00Z`);
  if (isNaN(t.getTime())) return undefined;
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}

export default function App() {
  const [user, setUser] = useState<User | null>(loadUser);
  const pick = (u: User | null) => {
    saveUser(u);
    setUser(u);
  };
  return (
    <div className="app">
      <header className="top">
        <h1>Tour Guide Huế</h1>
        {user && (
          <span className="who">
            {user.display_name}
            <button className="link" onClick={() => pick(null)}>
              Đổi người dùng
            </button>
          </span>
        )}
      </header>
      {user ? <PlanScreen user={user} onExpired={() => pick(null)} /> : <UserPicker onPick={pick} />}
    </div>
  );
}

/** GET /api/users → POST /api/session (server lưu user_id vào cookie, không gửi user_id trong body request khác). */
function UserPicker({ onPick }: { onPick: (u: User) => void }) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<User[]>("/users").then(setUsers, (e: ApiError) => setError(e.message));
  }, []);

  async function choose(u: User) {
    setError("");
    try {
      await api("/session", { json: { user_id: u.user_id } });
      onPick(u);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  return (
    <main className="picker">
      <h2>Chọn người dùng</h2>
      <p className="muted">Bản demo có 3 người dùng hư cấu, không dùng dữ liệu người thật.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!users && !error && <p className="muted">Đang tải…</p>}
      <div className="users">
        {users?.map((u) => (
          <button key={u.user_id} onClick={() => choose(u)}>
            {u.display_name}
            <small>{u.preferred_lang === "en" ? "English" : "Tiếng Việt"}</small>
          </button>
        ))}
      </div>
    </main>
  );
}

type Form = {
  start_date: string;
  end_date: string;
  adults: number;
  children: string;
  budget: string;
  interests: string[];
  pace: TripProfile["pace"];
  language: TripProfile["language"];
  mobility_notes: string;
};

function toProfile(f: Form): TripProfile {
  return {
    start_date: f.start_date,
    end_date: f.end_date,
    adults: f.adults,
    children: f.children.split(/[,\s]+/).filter(Boolean).map((a) => ({ age: Number(a) })),
    budget_total_vnd: f.budget ? Number(f.budget) : null,
    interests: f.interests,
    pace: f.pace,
    language: f.language,
    mobility_notes: f.mobility_notes.trim() || null,
  };
}

type Phase = { kind: "idle" | "done" } | { kind: "running"; step: string; since: number } | { kind: "error"; message: string };

/** UC-02: form hồ sơ → POST /trips → POST /plan (2–3 phút) → lịch trình theo ngày + bản đồ + log các bước. */
function PlanScreen({ user, onExpired }: { user: User; onExpired: () => void }) {
  const [form, setForm] = useState<Form>({
    start_date: "2026-11-25",
    end_date: "2026-11-27",
    adults: 2,
    children: "",
    budget: "8000000",
    interests: ["history", "food"],
    pace: "moderate",
    language: user.preferred_lang,
    mobility_notes: "",
  });
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [itinerary, setItinerary] = useState<Itinerary | null>(null);
  const [trace, setTrace] = useState<{ runId: string; events: TraceEvent[] } | null>(null);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setItinerary(null);
    setTrace(null);
    const since = Date.now();
    let runId: string | undefined;
    try {
      setPhase({ kind: "running", step: "Đang lưu hồ sơ…", since });
      const { trip_id } = await api<{ trip_id: string }>("/trips", { json: toProfile(form) });
      setPhase({ kind: "running", step: "Agent đang lập lịch trình: tra giờ mở cửa, thời gian di chuyển, thời tiết…", since });
      const plan = await api<PlanResult>(`/trips/${trip_id}/plan`, { method: "POST" });
      runId = plan.run_id;
      setItinerary(await api<Itinerary>(`/trips/${trip_id}/itinerary`));
      setPhase({ kind: "done" });
    } catch (err) {
      const e = err as ApiError;
      if (e.status === 401) return onExpired();
      runId ??= (e.detail as { run_id?: string } | undefined)?.run_id; // /plan lỗi vẫn trả run_id để xem log
      setPhase({ kind: "error", message: e.message });
    }
    if (runId) {
      const id = runId;
      api<TraceEvent[]>(`/runs/${id}/trace`).then((events) => setTrace({ runId: id, events }), () => {});
    }
  }

  const running = phase.kind === "running";
  return (
    <main className="plan">
      <section className="side">
        <form onSubmit={submit}>
          <fieldset disabled={running} className="grid">
            <legend>Hồ sơ chuyến đi Huế</legend>
            <label>
              Ngày đi
              <input type="date" required value={form.start_date} onChange={(e) => set("start_date", e.target.value)} />
            </label>
            <label>
              Ngày về <small>(tối đa 5 ngày)</small>
              <input type="date" required min={form.start_date} max={addDays(form.start_date, 4)} value={form.end_date}
                onChange={(e) => set("end_date", e.target.value)} />
            </label>
            <label>
              Người lớn
              <input type="number" required min={1} max={6} value={form.adults} onChange={(e) => set("adults", Number(e.target.value))} />
            </label>
            <label>
              Tuổi trẻ em <small>(cách nhau dấu phẩy)</small>
              <input inputMode="numeric" pattern="[0-9 ,]*" placeholder="vd 6, 9" value={form.children}
                onChange={(e) => set("children", e.target.value)} />
            </label>
            <label>
              Ngân sách cả chuyến (VND)
              <input type="number" min={1} value={form.budget} onChange={(e) => set("budget", e.target.value)} />
            </label>
            <label>
              Nhịp độ
              <select value={form.pace} onChange={(e) => set("pace", e.target.value as Form["pace"])}>
                <option value="relaxed">Thong thả</option>
                <option value="moderate">Vừa phải</option>
                <option value="packed">Dày đặc</option>
              </select>
            </label>
            <fieldset className="wide checks">
              <legend>Sở thích</legend>
              {INTERESTS.map(([v, label]) => (
                <label key={v}>
                  <input type="checkbox" checked={form.interests.includes(v)}
                    onChange={(e) => set("interests", e.target.checked ? [...form.interests, v] : form.interests.filter((x) => x !== v))} />
                  {label}
                </label>
              ))}
            </fieldset>
            <label>
              Ngôn ngữ
              <select value={form.language} onChange={(e) => set("language", e.target.value as Form["language"])}>
                <option value="vi">Tiếng Việt</option>
                <option value="en">English</option>
              </select>
            </label>
            <label>
              Ghi chú đi lại
              <input placeholder="vd có người cao tuổi, ít đi bộ" value={form.mobility_notes} onChange={(e) => set("mobility_notes", e.target.value)} />
            </label>
            <button type="submit" className="wide primary">
              {running ? "Đang lập lịch trình…" : "Lập lịch trình"}
            </button>
          </fieldset>
        </form>

        {phase.kind === "running" && (
          <div className="loading" role="status">
            <span className="spinner" aria-hidden />
            <div>
              {phase.step} <b><Elapsed since={phase.since} /></b>
              <small>Thường mất 2–3 phút, đừng đóng trang.</small>
            </div>
          </div>
        )}
        {phase.kind === "error" && <p className="error" role="alert">{phase.message}</p>}
        {itinerary && <ItineraryView it={itinerary} />}
        {trace && <TracePanel {...trace} />}
      </section>
      <section className="mapcol">
        <MapView slots={itinerary?.slots ?? NO_SLOTS} />
        <p className="muted small">Đường nét đứt nối các điểm theo thứ tự tham quan, không phải đường đi thực tế.</p>
      </section>
    </main>
  );
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const s = Math.floor((now - since) / 1000);
  return <>{Math.floor(s / 60)}:{String(s % 60).padStart(2, "0")}</>;
}

function ItineraryView({ it }: { it: Itinerary }) {
  const days = [...new Set(it.slots.map((s) => s.day_index))];
  return (
    <section className="itinerary">
      <h2>Lịch trình</h2>
      <p className={it.status === "validated" ? "ok" : "warn"}>
        {it.status === "validated" ? `Đã qua validator sau ${it.planner_rounds} vòng` : `Còn vi phạm sau ${it.planner_rounds} vòng`}
      </p>
      <p>
        Tổng chi phí đã có giá: <b>{vnd(it.total_cost_vnd ?? 0)}</b>
        {it.has_unpriced_item ? " + các mục chưa có giá" : ""}
      </p>
      {it.violations.length > 0 && (
        <ul className="violations">
          {it.violations.map((v) => (
            <li key={v.violation_id}>
              [{v.rule}] {v.message}
            </li>
          ))}
        </ul>
      )}
      {days.map((d) => {
        const slots = it.slots.filter((s) => s.day_index === d);
        return (
          <div key={d} className="day">
            <h3>
              <span className="dot" style={{ background: DAY_COLORS[(d - 1) % DAY_COLORS.length] }} />
              Ngày {d} · {dayLabel(slots[0].slot_date)}
            </h3>
            <ul>
              {slots.map((s) => (
                <SlotItem key={s.slot_id} s={s} />
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

function SlotItem({ s }: { s: Slot }) {
  return (
    <li className="slot">
      <div className="time">
        {s.start_time}–{s.end_time}
      </div>
      <div>
        <div className="title">{s.name_vi ?? "Tự do / nghỉ"}</div>
        <div>{s.activity}</div>
        <div className="tags">
          {s.travel_minutes_from_prev != null && <span className="tag">{s.travel_minutes_from_prev} phút di chuyển</span>}
          {s.cost_source === "tool" && s.cost_vnd != null && <span className="tag">{vnd(s.cost_vnd)}</span>}
          {s.cost_source === "free" && <span className="tag">Miễn phí</span>}
          {s.cost_source === "unverified" && <span className="tag warn">chưa có giá</span>}
          {s.hours_status === "unverified" && <span className="tag warn">giờ mở cửa chưa xác minh</span>}
          {s.hours_status === "verified" && <span className="tag ok">giờ mở cửa đã xác minh</span>}
        </div>
        {s.note && <div className="muted small">{s.note}</div>}
      </div>
    </li>
  );
}

/** Panel log: GET /api/runs/{id}/trace, mỗi bước bấm vào xem tham số và kết quả. */
function TracePanel({ runId, events }: { runId: string; events: TraceEvent[] }) {
  return (
    <details className="trace" open>
      <summary>
        Log các bước của agent · {events.length} bước · <code>{runId}</code>
      </summary>
      <ol>
        {events.map((e) => (
          <li key={e.seq} className={e.error ? "err" : undefined}>
            <details>
              <summary>
                <b>{e.node}</b> · {e.kind}
                {e.name && ` · ${e.name}`}
                {e.duration_ms != null && ` · ${e.duration_ms} ms`}
                {e.tokens != null && ` · ${e.tokens} token`}
                {e.error && ` · lỗi: ${e.error}`}
              </summary>
              <pre>{JSON.stringify({ args: e.args, result: e.result }, null, 2)}</pre>
            </details>
          </li>
        ))}
      </ol>
    </details>
  );
}
