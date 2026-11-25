import { useCallback, useEffect, useState } from "react";
import { api, type ApiError } from "../api";
import type { Shell } from "../App";
import { locale, t } from "../i18n";
import { Empty, Skeleton } from "../ui";

/** GET /api/dashboard (agent/src/obs/dashboard.py): 5 chỉ số vận hành của Buổi 11, chỉ lượt chạy của người đăng nhập. */
type Stats = {
  runs: number; succeeded: number; failed: number; interrupted: number; running: number;
  success_rate: number | null; avg_tokens: number | null; max_tokens: number | null; cost_usd: number; latency_p95_ms: number | null;
};
type ToolStat = { name: string; calls: number; errors: number; error_rate: number };
export type DashboardData = {
  total: Stats;
  by_uc: Record<string, Stats>;
  tools: ToolStat[];
  guardrails: Record<string, number>;
  approvals: { pending: number; by_kind: Record<string, number> };
};

const REFRESH_MS = 15000;

const UC: Record<string, [string, string]> = {
  "UC-01": ["Hội thoại lập hồ sơ", "Trip intake chat"], "UC-02": ["Lập lịch trình", "Itinerary planning"],
  "UC-03": ["Thuyết minh điểm đến", "Site narration"], "UC-06": ["Review nhiều agent", "Multi-agent review"],
  "UC-07": ["Bộ nhớ sở thích", "Preference memory"], "UC-09": ["Nhật ký chuyến đi", "Trip journal"],
  "UC-11": ["Kiểm chứng thông tin", "Fact checking"], EVAL: ["Chạy eval", "Eval run"],
};

const GUARD: Record<string, [string, string]> = {
  validator: ["Validator kiểm lịch trình", "Itinerary validator"],
  claim: ["Kiểm chứng từng claim", "Per-claim fact check"],
  fill_facts: ["Điền dữ kiện đã tra bằng tool", "Facts filled from tools"],
  best_draft: ["Chọn bản lịch tốt nhất", "Best draft selected"],
  memory_write: ["Ghi bộ nhớ sau khi duyệt", "Memory written after approval"],
  intake_result: ["Kiểm kết quả hội thoại", "Intake result check"],
  keep_approved_itinerary: ["Giữ bản đã duyệt", "Kept approved itinerary"],
  kb_min_score: ["Câu hỏi ngoài kho tri thức", "Out-of-knowledge question"],
  citations: ["Kiểm trích dẫn", "Citation check"],
  verify_gate: ["Cổng kiểm chứng", "Verification gate"],
  tool_denied: ["Chặn tool ngoài quyền", "Tool outside permissions blocked"],
  tool_blocked: ["Chặn tool MCP chưa duyệt", "Unapproved MCP tool blocked"],
  unknown_poi: ["Bỏ địa điểm không tồn tại", "Unknown place dropped"],
  require_submission: ["Ép nộp khi gần hết lượt", "Forced submit near turn limit"],
  keep_best_on_turn_limit: ["Hết lượt: giữ bản tốt nhất", "Turn limit: kept best draft"],
  keep_best_on_provider_error: ["Model lỗi: giữ bản tốt nhất", "Provider error: kept best draft"],
  llm_retry: ["Thử lại gọi model", "Model call retried"],
  llm_wait: ["Chờ giới hạn tốc độ", "Waited for rate limit"],
  llm_retry_exhausted: ["Hết lượt thử lại model", "Model retries exhausted"],
};

const KIND: Record<string, [string, string]> = {
  itinerary_approval: ["Duyệt lịch trình", "Itinerary approval"], memory_save: ["Lưu bộ nhớ", "Save memory"],
  ask_user: ["Hỏi lại người dùng", "Ask the user"],
};
const DECISION: Record<string, [string, string]> = {
  pending: ["đang chờ", "pending"], approved: ["đồng ý", "approved"], edited: ["yêu cầu sửa", "edit requested"], rejected: ["từ chối", "rejected"],
};

const label = (map: Record<string, [string, string]>, key: string) => (map[key] ? t(...map[key]) : key);
const num = (n: number | null, digits = 0) => (n == null ? "–" : n.toLocaleString(locale(), { maximumFractionDigits: digits }));
const pct = (r: number | null) => (r == null ? "–" : `${Math.round(r * 100)}%`);
const secs = (ms: number | null) => (ms == null ? "–" : ms < 1000 ? `${Math.round(ms)} ms` : `${num(ms / 1000, ms < 10000 ? 1 : 0)} s`);
const usd = (n: number) => (n === 0 ? "$0" : `$${n.toLocaleString("en-US", { maximumFractionDigits: 4 })}`);

export default function DashboardPage({ shell }: { shell: Shell }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setBusy(true);
    return api<DashboardData>("/dashboard")
      .then((d) => { setData(d); setError(""); setUpdated(new Date()); })
      .catch((e: ApiError) => setError(e.message))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => {
    if (!shell.user) return;
    load();
    const timer = setInterval(() => document.visibilityState === "visible" && load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [shell.user, load]);

  if (!shell.user) {
    return (
      <div className="wrap page">
        <Empty title={t("Đăng nhập để xem dashboard vận hành của agent", "Log in to see the agent operations dashboard")}>
          <button className="primary" onClick={shell.askLogin}>{t("Đăng nhập", "Log in")}</button>
        </Empty>
      </div>
    );
  }

  return (
    <div className="wrap page dash">
      <header className="dash-head">
        <div>
          <p className="eyebrow">{t("Observability · Buổi 11", "Observability · Lecture 11")}</p>
          <h1>{t("Dashboard vận hành", "Operations dashboard")}</h1>
          <p className="muted">
            {t("Năm chỉ số đọc từ trace do backend ghi (runs, trace_events, approvals). Chỉ tính các lượt chạy của bạn.",
              "Five metrics read from the backend-written trace (runs, trace_events, approvals). Only your own runs are counted.")}
          </p>
        </div>
        <div className="dash-refresh">
          <button onClick={load} disabled={busy} aria-label={t("Tải lại số liệu", "Reload metrics")}>
            <span className={busy ? "spinner small-spinner" : "refresh-icon"} aria-hidden>{busy ? "" : "↻"}</span>
            {t("Làm mới", "Refresh")}
          </button>
          {updated && <span className="muted tiny">{t("Cập nhật", "Updated")} {updated.toLocaleTimeString(locale())} · {t("tự làm mới mỗi 15 giây", "auto-refresh every 15 s")}</span>}
        </div>
      </header>

      {error && <p className="note error" role="alert">{error}</p>}
      {!data && !error && <Skeleton rows={4} />}
      {data && (data.total.runs === 0 ? (
        <Empty title={t("Chưa có lượt chạy nào", "No runs yet")}>
          <p className="muted">{t("Lập một lịch trình hoặc nghe thuyết minh, số liệu sẽ hiện ở đây.", "Plan a trip or ask for a narration and the numbers will show up here.")}</p>
          <a className="button primary" href="#/plan">{t("Lập lịch", "Plan a trip")}</a>
        </Empty>
      ) : <Board d={data} />)}
    </div>
  );
}

function Board({ d }: { d: DashboardData }) {
  const s = d.total;
  const guards = Object.entries(d.guardrails);
  const guardMax = Math.max(1, ...guards.map(([, n]) => n));
  const callMax = Math.max(1, ...d.tools.map((x) => x.calls));
  const ucs = Object.entries(d.by_uc);
  return (
    <>
      <section className="kpis" aria-label={t("Chỉ số chính", "Key metrics")}>
        <Kpi n="1" title={t("Lượt chạy", "Runs")} value={num(s.runs)}
          sub={t(`${s.succeeded} xong · ${s.failed} lỗi · ${s.interrupted} chờ bạn`, `${s.succeeded} done · ${s.failed} failed · ${s.interrupted} waiting`)} />
        <Kpi n="1" title={t("Tỷ lệ thành công", "Success rate")} value={pct(s.success_rate)} meter={s.success_rate}
          sub={t("trên lượt đã kết thúc", "of finished runs")} />
        <Kpi n="2" title={t("Token trung bình / lượt", "Avg tokens / run")} value={num(s.avg_tokens)}
          sub={t(`cao nhất ${num(s.max_tokens)} · ${usd(s.cost_usd)}`, `max ${num(s.max_tokens)} · ${usd(s.cost_usd)}`)} />
        <Kpi n="3" title={t("Độ trễ p95", "Latency p95")} value={secs(s.latency_p95_ms)}
          sub={t("95% lượt chạy nhanh hơn mức này", "95% of runs finish faster")} />
        <Kpi n="5" title={t("Đang chờ duyệt", "Awaiting approval")} value={num(d.approvals.pending)} accent={d.approvals.pending > 0}
          sub={t(`${num(guards.reduce((a, [, n]) => a + n, 0))} lần guardrail can thiệp`, `${num(guards.reduce((a, [, n]) => a + n, 0))} guardrail interventions`)} />
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>{t("Theo use case", "By use case")}</h2>
          <p className="muted small">{t("Lượt “chờ bạn” đang dừng ở bước duyệt, không tính là lỗi.", "Runs “waiting” are paused for approval and are not counted as failures.")}</p>
        </div>
        <div className="table-scroll">
          <table className="dash-table uc-table">
            <thead>
              <tr>
                <th scope="col">{t("Use case", "Use case")}</th>
                <th scope="col" className="num">{t("Lượt", "Runs")}</th>
                <th scope="col">{t("Thành công", "Success")}</th>
                <th scope="col" className="num">{t("Lỗi", "Failed")}</th>
                <th scope="col" className="num">{t("Chờ bạn", "Waiting")}</th>
                <th scope="col" className="num">{t("Token TB", "Avg tokens")}</th>
                <th scope="col" className="num">p95</th>
                <th scope="col" className="num">{t("Chi phí", "Cost")}</th>
              </tr>
            </thead>
            <tbody>
              {ucs.map(([uc, x]) => (
                <tr key={uc}>
                  <th scope="row"><span className="uc-code">{uc}</span> {label(UC, uc)}</th>
                  <td className="num">{num(x.runs)}</td>
                  <td><Meter value={x.success_rate} /></td>
                  <td className={`num${x.failed ? " bad" : ""}`}>{num(x.failed)}</td>
                  <td className="num">{num(x.interrupted)}</td>
                  <td className="num">{num(x.avg_tokens)}</td>
                  <td className="num">{secs(x.latency_p95_ms)}</td>
                  <td className="num">{usd(x.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="dash-grid">
        <section className="panel">
          <div className="panel-head">
            <h2>{t("Tool lỗi nhiều nhất", "Most failing tools")}</h2>
            <p className="muted small">{t("Xếp theo số lỗi, rồi số lượt gọi: tool đứng đầu nên sửa trước.", "Sorted by errors, then calls: fix the top one first.")}</p>
          </div>
          {d.tools.length === 0 ? <p className="muted">{t("Chưa có lượt gọi tool nào.", "No tool calls yet.")}</p> : (
            <table className="dash-table bars">
              <thead>
                <tr><th scope="col">Tool</th><th scope="col">{t("Lượt gọi", "Calls")}</th><th scope="col" className="num">{t("Lỗi", "Errors")}</th></tr>
              </thead>
              <tbody>
                {d.tools.map((x) => (
                  <tr key={x.name}>
                    <th scope="row"><code>{x.name}</code></th>
                    <td><Bar value={x.calls} max={callMax} text={num(x.calls)} /></td>
                    <td className="num">
                      {x.errors ? <span className="tag warn">{num(x.errors)} · {pct(x.error_rate)}</span> : <span className="tag ok">0</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>{t("Lớp kiểm soát", "Control layer")}</h2>
            <p className="muted small">{t("Guardrail và bước duyệt là code ngoài model: số lần chúng hoạt động.", "Guardrails and approvals are code outside the model: how often they fired.")}</p>
          </div>
          <h3 className="sub-head">{t("Bước duyệt của người dùng", "User approvals")}</h3>
          {Object.keys(d.approvals.by_kind).length === 0 ? <p className="muted small">{t("Chưa có bước duyệt.", "No approvals yet.")}</p> : (
            <ul className="approval-list">
              {Object.entries(d.approvals.by_kind).map(([key, n]) => {
                const [kind, decision] = key.split(":");
                return (
                  <li key={key}>
                    <span>{label(KIND, kind)}</span>
                    <span className={`tag${decision === "pending" ? " warn" : decision === "approved" ? " ok" : ""}`}>{label(DECISION, decision)}</span>
                    <b>{num(n)}</b>
                  </li>
                );
              })}
            </ul>
          )}
          <h3 className="sub-head">Guardrail</h3>
          {guards.length === 0 ? <p className="muted small">{t("Chưa có guardrail nào chạy.", "No guardrail has fired yet.")}</p> : (
            <>
              <GuardTable rows={guards.slice(0, GUARD_SHOWN)} max={guardMax} />
              {guards.length > GUARD_SHOWN && (
                <details className="more">
                  <summary>{t(`Xem thêm ${guards.length - GUARD_SHOWN} guardrail`, `Show ${guards.length - GUARD_SHOWN} more guardrails`)}</summary>
                  <GuardTable rows={guards.slice(GUARD_SHOWN)} max={guardMax} />
                </details>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}

const GUARD_SHOWN = 6;

function GuardTable({ rows, max }: { rows: [string, number][]; max: number }) {
  return (
    <table className="dash-table bars">
      <tbody>
        {rows.map(([name, n]) => (
          <tr key={name}>
            <th scope="row">{label(GUARD, name)}<code className="guard-code">{name}</code></th>
            <td><Bar value={n} max={max} text={num(n)} soft /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Kpi({ n, title, value, sub, meter, accent }: { n: string; title: string; value: string; sub: string; meter?: number | null; accent?: boolean }) {
  return (
    <div className={`kpi${accent ? " accent" : ""}`}>
      <p className="kpi-title"><span className="kpi-n" title={t(`Chỉ số ${n} của slide 47`, `Metric ${n} of slide 47`)}>{n}</span>{title}</p>
      <p className="kpi-value">{value}</p>
      {meter != null && <span className="meter" aria-hidden><i style={{ width: `${meter * 100}%` }} /></span>}
      <p className="kpi-sub">{sub}</p>
    </div>
  );
}

function Meter({ value }: { value: number | null }) {
  if (value == null) return <span className="muted small">{t("chưa kết thúc", "not finished")}</span>;
  return (
    <span className="meter-row">
      <span className="meter" aria-hidden><i style={{ width: `${value * 100}%` }} /></span>
      <b>{pct(value)}</b>
    </span>
  );
}

function Bar({ value, max, text, soft }: { value: number; max: number; text: string; soft?: boolean }) {
  return (
    <span className="bar-row" title={text}>
      <span className={`bar${soft ? " soft" : ""}`} aria-hidden><i style={{ width: `${Math.max(2, (value / max) * 100)}%` }} /></span>
      <span className="bar-value">{text}</span>
    </span>
  );
}
