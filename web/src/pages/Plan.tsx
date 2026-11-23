import { useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type TripProfile, type TripRow } from "../api";
import type { Shell } from "../App";
import { NearestPlace } from "../components/NearestPlace";
import { getLang, poiName, t } from "../i18n";
import { inHue, nearestPoi, useSessionLocation } from "../location";
import MapView from "../MapView";
import { Empty, go, interest, Skeleton, vnd } from "../ui";

const STATUS: Record<string, [string, string]> = {
  profiling: ["Đang hỏi thêm thông tin", "Collecting details"], planning: ["Đang lập lịch", "Planning"],
  awaiting_approval: ["Chờ bạn duyệt", "Awaiting your approval"], approved: ["Đã duyệt", "Approved"],
  in_progress: ["Đang đi", "In progress"], completed: ["Đã xong", "Completed"], cancelled: ["Đã huỷ", "Cancelled"],
};
export const status = (s: string) => (STATUS[s] ? t(...STATUS[s]) : s);

const INTERESTS = ["history", "food", "culture", "nature", "shopping"] as const;

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

function toProfile(f: Form, start: { poi_id: string; name_vi: string } | null): TripProfile {
  return {
    // Chỉ gửi POI gần vị trí người dùng nhất, không gửi toạ độ (quy tắc nhóm: không lưu vị trí chính xác).
    hard_constraints: start ? [`Mỗi ngày xuất phát từ khu vực gần ${start.name_vi} (${start.poi_id}); ưu tiên các điểm gần đó vào đầu ngày`] : [],
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
  return n >= 1 && n <= 5 ? t(`${n} ngày`, `${n} day${n > 1 ? "s" : ""}`) : null;
}

export function PlanPage({ shell, preset }: { shell: Shell; preset: string }) {
  const [form, setForm] = useState<Form>({
    start_date: "2026-11-25", end_date: "2026-11-27", adults: 2, children: "", budget: "8000000",
    interests: ["history", "food"], pace: "moderate", language: getLang(), mobility_notes: "",
  });
  const [text, setText] = useState(preset);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

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
  const here = useSessionLocation();
  const nearest = nearestPoi(here.coords, shell.pois);
  // Ở ngoài Huế thì điểm gần nhất vẫn hiện để tham khảo nhưng không gửi agent làm điểm xuất phát
  const origin = here.coords && inHue(here.coords) ? nearest : null;
  const submitForm = (e: FormEvent) => { e.preventDefault(); start("/ui/start-form", toProfile(form, origin)); };
  const submitText = (e: FormEvent) => { e.preventDefault(); start("/ui/start-text", { text }); };
  const length = dayCount(form.start_date, form.end_date);

  return (
    <div className="wrap page narrow">
      <h1>{t("Kể về chuyến đi của bạn", "Tell us about your trip")}</h1>
      <p className="muted">{t("Điền thông tin chuyến đi, agent sẽ lập lịch để bạn duyệt.", "Fill in your trip details and the agent will draft an itinerary for you to approve.")}</p>
      <form onSubmit={submitForm}>
        <fieldset disabled={busy} className="form-grid">
          <label>
            {t("Ngày đi", "Start date")}
            <input type="date" required value={form.start_date} onChange={(e) => set("start_date", e.target.value)} />
          </label>
          <label>
            <span>{t("Ngày về", "End date")} <small>({t("tối đa 5 ngày", "up to 5 days")}{length ? t(`, đang chọn ${length}`, `, ${length} selected`) : ""})</small></span>
            <input type="date" required min={form.start_date} max={addDays(form.start_date, 4)} value={form.end_date} onChange={(e) => set("end_date", e.target.value)} />
          </label>
          <label>
            {t("Người lớn", "Adults")}
            <input type="number" required min={1} max={6} value={form.adults} onChange={(e) => set("adults", Number(e.target.value))} />
          </label>
          <label>
            <span>{t("Tuổi trẻ em", "Children's ages")} <small>({t("cách nhau dấu phẩy", "comma separated")})</small></span>
            <input inputMode="numeric" pattern="[0-9 ,]*" placeholder={t("vd 6, 9", "e.g. 6, 9")} value={form.children} onChange={(e) => set("children", e.target.value)} />
          </label>
          <label>
            {t("Ngân sách cả chuyến (VND)", "Total budget (VND)")}
            <input type="number" min={1} value={form.budget} onChange={(e) => set("budget", e.target.value)} />
          </label>
          <label>
            {t("Nhịp độ", "Pace")}
            <select value={form.pace} onChange={(e) => set("pace", e.target.value as Form["pace"])}>
              <option value="relaxed">{interest("relaxed")}</option>
              <option value="moderate">{interest("moderate")}</option>
              <option value="packed">{interest("packed")}</option>
            </select>
          </label>
          <fieldset className="wide">
            <legend>{t("Sở thích", "Interests")}</legend>
            <div className="interests">
              {INTERESTS.map((v) => (
                <label key={v}>
                  <input type="checkbox" checked={form.interests.includes(v)}
                    onChange={(e) => set("interests", e.target.checked ? [...form.interests, v] : form.interests.filter((x) => x !== v))} />
                  {interest(v)}
                </label>
              ))}
            </div>
          </fieldset>
          <label>
            {t("Ngôn ngữ lịch trình", "Itinerary language")}
            <select value={form.language} onChange={(e) => set("language", e.target.value as Form["language"])}>
              <option value="vi">Tiếng Việt</option>
              <option value="en">English</option>
            </select>
          </label>
          <label>
            {t("Ghi chú đi lại", "Mobility notes")}
            <input maxLength={500} placeholder={t("vd có người cao tuổi, ít đi bộ", "e.g. elderly traveller, little walking")} value={form.mobility_notes} onChange={(e) => set("mobility_notes", e.target.value)} />
          </label>
          <div className="wide here-bar">
            <span>{t("Điểm xuất phát", "Starting point")}</span>
            {!(here.coords && nearest) && (
              <button type="button" onClick={here.request} disabled={here.asking}>{here.asking ? t("Đang lấy vị trí...", "Getting location...") : t("Lấy vị trí hiện tại", "Use my current location")}</button>
            )}
            <small className="muted">{t("Agent chỉ nhận tên địa điểm gần bạn nhất, toạ độ ở lại trên máy này.", "The agent only gets the name of the nearest place; your coordinates stay on this device.")}</small>
            {here.error && <p className="warn small" role="alert">{here.error}</p>}
          </div>
          {here.coords && nearest && (
            <div className="wide here-panel">
              <NearestPlace poi={nearest} here={here.coords} title={t("Điểm gần bạn nhất", "Closest place to you")} onClear={here.clear}
                extra={<p className="small">{origin
                  ? t("Agent sẽ ưu tiên các điểm gần đây vào đầu mỗi ngày.", "The agent will favour nearby places at the start of each day.")
                  : t("Không dùng làm điểm xuất phát vì bạn đang ở ngoài Huế.", "Not used as the starting point because you are outside Hue.")}</p>} />
              <MapView slots={[]} pois={shell.pois} here={here.coords} nearest={{ lat: nearest.lat, lon: nearest.lon, name: poiName(nearest) }} />
            </div>
          )}
          <button type="submit" className="wide primary">{busy ? t("Đang gửi...", "Sending...") : t("Lập lịch trình", "Plan itinerary")}</button>
        </fieldset>
      </form>
      {error && <p className="error" role="alert">{error}</p>}

      <details className="text-entry" open={!!preset}>
        <summary>{t("Hoặc kể bằng lời (cần đủ ngày, số người, ngân sách)", "Or describe it in words (include dates, group size, budget)")}</summary>
        <form onSubmit={submitText}>
          <label htmlFor="trip-text" className="sr">{t("Yêu cầu chuyến đi", "Trip request")}</label>
          <textarea id="trip-text" rows={2} required minLength={3} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder={t("Cuối tháng 11 nhà mình đi Huế 3 ngày, 2 người lớn 1 bé 6 tuổi, khoảng 8 triệu", "Late November, Hue for 3 days, 2 adults and a 6-year-old, about 8 million VND")} />
          <button className="primary" disabled={busy}>{t("Gửi", "Send")}</button>
        </form>
      </details>
      {!shell.llm && <p className="note">{t("Bản này chưa có khoá LLM nên planner là bản giả. Giờ, giá, thời tiết, validator, bước duyệt và bộ nhớ vẫn là code và dữ liệu thật của nhóm.", "This build has no LLM key, so the planner is a stub. Hours, prices, weather, validator, approval and memory are still the team's real code and data.")}</p>}
    </div>
  );
}

export function TripsPage({ shell }: { shell: Shell }) {
  const [trips, setTrips] = useState<TripRow[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (shell.user) api<TripRow[]>("/ui/trips").then(setTrips, (e: ApiError) => setError(e.message));
  }, [shell.user]);

  if (!shell.user) return <div className="wrap page"><Empty title={t("Đăng nhập để xem chuyến đi", "Log in to see your trips")}><button className="primary" onClick={shell.askLogin}>{t("Đăng nhập", "Log in")}</button></Empty></div>;
  return (
    <div className="wrap page">
      <h1>{t("Chuyến đi của tôi", "My trips")}</h1>
      {error && <p className="error" role="alert">{error}</p>}
      {!trips && !error && <Skeleton />}
      {trips?.length === 0 && <Empty title={t("Bạn chưa có chuyến nào", "You have no trips yet")}><a className="button primary" href="#/plan">{t("Lập lịch trình", "Plan itinerary")}</a></Empty>}
      <div className="trip-list">
        {trips?.map((trip) => (
          <a key={trip.trip_id} className="trip-row" href={`#/trips/${trip.trip_id}`}>
            <div>
              <b>{trip.start_date ? t(`Huế, ${trip.start_date} đến ${trip.end_date}`, `Hue, ${trip.start_date} to ${trip.end_date}`) : t("Chuyến đi chưa đủ thông tin", "Trip details incomplete")}</b>
              <p className="muted small">{trip.request}</p>
            </div>
            <div className="trip-state">
              <span className={trip.waiting ? "tag warn" : "tag"}>{trip.waiting ? t("Agent đang chờ bạn", "Agent is waiting for you") : status(trip.status)}</span>
              {trip.budget_total_vnd != null && <span className="muted small">{vnd(trip.budget_total_vnd)}</span>}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
