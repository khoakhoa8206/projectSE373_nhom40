import { useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type TripProfile, type TripRow } from "../api";
import type { Shell } from "../App";
import { Empty, go, Skeleton, vnd } from "../ui";

export const STATUS: Record<string, string> = {
  profiling: "Đang hỏi thêm thông tin", planning: "Đang lập lịch", awaiting_approval: "Chờ bạn duyệt", approved: "Đã duyệt",
  in_progress: "Đang đi", completed: "Đã xong", cancelled: "Đã huỷ",
};

const INTERESTS = [["history", "Lịch sử"], ["food", "Ẩm thực"], ["culture", "Văn hoá"], ["nature", "Thiên nhiên"], ["shopping", "Mua sắm"]] as const;

type Form = {
  start_date: string;
  end_date: string;
  adults: number;
  children: string;
  budget: string;
  interests: string[];
  pace: NonNullable<TripProfile["pace"]>;
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

function addDays(d: string, n: number) {
  const t = new Date(`${d}T00:00Z`);
  if (isNaN(t.getTime())) return undefined;
  t.setUTCDate(t.getUTCDate() + n);
  return t.toISOString().slice(0, 10);
}

function dayCount(a: string, b: string) {
  const n = Math.round((Date.parse(b) - Date.parse(a)) / 86400000) + 1;
  return n >= 1 && n <= 5 ? `${n} ngày` : null;
}

export function PlanPage({ shell, preset }: { shell: Shell; preset: string }) {
  const [form, setForm] = useState<Form>({
    start_date: "2026-11-25", end_date: "2026-11-27", adults: 2, children: "", budget: "8000000",
    interests: ["history", "food"], pace: "moderate", language: "vi", mobility_notes: "",
  });
  const [text, setText] = useState(preset);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));
  const preferred = shell.user?.preferred_lang;
  useEffect(() => { if (preferred) setForm((f) => ({ ...f, language: preferred })); }, [preferred]);

  async function start(path: string, json: unknown) {
    if (!shell.user) return shell.askLogin();
    setBusy(true);
    setError("");
    try {
      const { trip_id, run_id } = await api<{ trip_id: string; run_id: string }>(path, { json });
      go(`/trips/${trip_id}?run=${run_id}`);
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  }
  const submitForm = (e: FormEvent) => { e.preventDefault(); start("/ui/start-form", toProfile(form)); };
  const submitText = (e: FormEvent) => { e.preventDefault(); start("/ui/start-text", { text }); };
  const length = dayCount(form.start_date, form.end_date);

  return (
    <div className="wrap page narrow">
      <h1>Kể về chuyến đi của bạn</h1>
      <p className="muted">Điền thông tin chuyến đi, agent sẽ lập lịch để bạn duyệt.</p>
      <form onSubmit={submitForm}>
        <fieldset disabled={busy} className="form-grid">
          <label>
            Ngày đi
            <input type="date" required value={form.start_date} onChange={(e) => set("start_date", e.target.value)} />
          </label>
          <label>
            <span>Ngày về <small>(tối đa 5 ngày{length ? `, đang chọn ${length}` : ""})</small></span>
            <input type="date" required min={form.start_date} max={addDays(form.start_date, 4)} value={form.end_date} onChange={(e) => set("end_date", e.target.value)} />
          </label>
          <label>
            Người lớn
            <input type="number" required min={1} max={6} value={form.adults} onChange={(e) => set("adults", Number(e.target.value))} />
          </label>
          <label>
            <span>Tuổi trẻ em <small>(cách nhau dấu phẩy)</small></span>
            <input inputMode="numeric" pattern="[0-9 ,]*" placeholder="vd 6, 9" value={form.children} onChange={(e) => set("children", e.target.value)} />
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
          <fieldset className="wide">
            <legend>Sở thích</legend>
            <div className="interests">
              {INTERESTS.map(([v, label]) => (
                <label key={v}>
                  <input type="checkbox" checked={form.interests.includes(v)}
                    onChange={(e) => set("interests", e.target.checked ? [...form.interests, v] : form.interests.filter((x) => x !== v))} />
                  {label}
                </label>
              ))}
            </div>
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
            <input maxLength={500} placeholder="vd có người cao tuổi, ít đi bộ" value={form.mobility_notes} onChange={(e) => set("mobility_notes", e.target.value)} />
          </label>
          <button type="submit" className="wide primary">{busy ? "Đang gửi..." : "Lập lịch trình"}</button>
        </fieldset>
      </form>
      {error && <p className="error" role="alert">{error}</p>}

      <details className="text-entry" open={!!preset}>
        <summary>Hoặc kể bằng lời (cần đủ ngày, số người, ngân sách)</summary>
        <form onSubmit={submitText}>
          <label htmlFor="trip-text" className="sr">Yêu cầu chuyến đi</label>
          <textarea id="trip-text" rows={2} required minLength={3} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Cuối tháng 11 nhà mình đi Huế 3 ngày, 2 người lớn 1 bé 6 tuổi, khoảng 8 triệu" />
          <button className="primary" disabled={busy}>Gửi</button>
        </form>
      </details>
      {!shell.llm && <p className="note">Bản này chưa có khoá LLM nên planner là bản giả. Giờ, giá, thời tiết, validator, bước duyệt và bộ nhớ vẫn là code và dữ liệu thật của nhóm.</p>}
    </div>
  );
}

export function TripsPage({ shell }: { shell: Shell }) {
  const [trips, setTrips] = useState<TripRow[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (shell.user) api<TripRow[]>("/ui/trips").then(setTrips, (e: ApiError) => setError(e.message));
  }, [shell.user]);

  if (!shell.user) return <div className="wrap page"><Empty title="Đăng nhập để xem chuyến đi"><button className="primary" onClick={shell.askLogin}>Đăng nhập</button></Empty></div>;
  return (
    <div className="wrap page">
      <h1>Chuyến đi của tôi</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {!trips && !error && <Skeleton />}
      {trips?.length === 0 && <Empty title="Bạn chưa có chuyến nào"><a className="button primary" href="#/plan">Lập lịch trình</a></Empty>}
      <div className="trip-list">
        {trips?.map((t) => (
          <a key={t.trip_id} className="trip-row" href={`#/trips/${t.trip_id}`}>
            <div>
              <b>{t.start_date ? `Huế, ${t.start_date} đến ${t.end_date}` : "Chuyến đi chưa đủ thông tin"}</b>
              <p className="muted small">{t.request}</p>
            </div>
            <div className="trip-state">
              <span className={t.waiting ? "tag warn" : "tag"}>{t.waiting ? "Agent đang chờ bạn" : STATUS[t.status]}</span>
              {t.budget_total_vnd != null && <span className="muted small">{vnd(t.budget_total_vnd)}</span>}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
