import { useEffect, useState, type FormEvent } from "react";
import { api, type ApiError, type TraceEvent } from "../api";
import type { Shell } from "../App";
import { t } from "../i18n";
import { Empty, go, Skeleton } from "../ui";

export type Run = {
  run_id: string; trip_id: string | null; uc: string; status: string; started_at: string; ended_at: string | null;
  tokens_in: number; tokens_out: number; cost_usd: number; latency_ms: number | null;
};

type Kind = "node" | "llm_call" | "tool_call" | "skill_use" | "guardrail" | "approval" | "error";
const KINDS: [Kind, string, string][] = [
  ["node", "Node", "Node"], ["llm_call", "LLM", "LLM"], ["tool_call", "Tool", "Tool"], ["skill_use", "Skill", "Skill"],
  ["guardrail", "Guardrail", "Guardrail"], ["approval", "Duyệt", "Approval"], ["error", "Lỗi", "Error"],
];
const kindOf = (e: TraceEvent): Kind => (e.kind === "node_start" || e.kind === "node_end" ? "node" : (e.kind as Kind));
const TAG: Partial<Record<Kind, string>> = { guardrail: "warn", error: "err", approval: "fixed", tool_call: "ok" };
const ms = (n: number | null) => (n == null ? "" : n >= 10000 ? `${(n / 1000).toFixed(0)} s` : `${n} ms`);

/** W11-P1-3: trace viewer. #/trace?q=<trip_id|run_id> liệt kê lượt chạy, #/trace/<run_id> xem từng bước. */
export default function TracePage({ shell, runId, query }: { shell: Shell; runId: string | null; query: string }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [q, setQ] = useState(query);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!shell.user) return;
    const param = !query ? "" : query.startsWith("t-") ? `?trip_id=${query}` : `?run_id=${query}`;
    api<Run[]>(`/runs${param}`).then(setRuns).catch((e: ApiError) => setError(e.message));
  }, [shell.user, query]);

  if (!shell.user) return <div className="wrap page"><Empty title={t("Đăng nhập để xem trace của bạn", "Log in to see your traces")}><button className="primary" onClick={shell.askLogin}>{t("Đăng nhập", "Log in")}</button></Empty></div>;
  const search = (e: FormEvent) => { e.preventDefault(); go(`/trace${runId ? `/${runId}` : ""}${q.trim() ? `?q=${q.trim()}` : ""}`); };

  return (
    <div className="wrap page trace-page">
      <h1>{t("Trace các lượt chạy", "Run traces")}</h1>
      <p className="muted">{t("Từng bước agent đã làm: node, lời gọi LLM, tool, skill, guardrail, lỗi. Toạ độ trong trace đã được làm thô.", "Every step the agent took: nodes, LLM calls, tools, skills, guardrails, errors. Coordinates in traces are coarsened.")}</p>
      <form className="trace-search" onSubmit={search} role="search">
        <label className="sr" htmlFor="trace-q">{t("Lọc theo mã chuyến hoặc mã lượt chạy", "Filter by trip id or run id")}</label>
        <input id="trace-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("t-… (chuyến) hoặc r-… (lượt chạy)", "t-… (trip) or r-… (run)")} />
        <button>{t("Lọc", "Filter")}</button>
        {query && <button type="button" className="ghost" onClick={() => { setQ(""); go(`/trace${runId ? `/${runId}` : ""}`); }}>{t("Bỏ lọc", "Clear")}</button>}
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="trace-grid">
        <aside aria-label={t("Danh sách lượt chạy", "Run list")}>
          {!runs && !error && <Skeleton rows={5} />}
          {runs?.length === 0 && <Empty title={t("Không có lượt chạy nào", "No runs found")} />}
          <ul className="run-list">
            {runs?.map((r) => (
              <li key={r.run_id}>
                <a href={`#/trace/${r.run_id}${query ? `?q=${query}` : ""}`} aria-current={r.run_id === runId ? "true" : undefined}>
                  <b>{r.uc}</b> <span className={`tag ${r.status === "failed" ? "err" : r.status === "succeeded" ? "ok" : ""}`}>{r.status}</span>
                  <span className="muted tiny">{r.started_at.slice(0, 16).replace("T", " ")} · {r.tokens_in + r.tokens_out} token · {ms(r.latency_ms)}</span>
                </a>
              </li>
            ))}
          </ul>
        </aside>
        <section aria-live="polite">
          {runId ? <RunTrace key={runId} run={runs?.find((r) => r.run_id === runId) ?? null} runId={runId} /> : <Empty title={t("Chọn 1 lượt chạy để xem trace", "Pick a run to see its trace")} />}
        </section>
      </div>
    </div>
  );
}

function RunTrace({ run, runId }: { run: Run | null; runId: string }) {
  const [events, setEvents] = useState<TraceEvent[] | null>(null);
  const [off, setOff] = useState<Set<Kind>>(new Set());
  const [error, setError] = useState("");
  useEffect(() => { api<TraceEvent[]>(`/runs/${runId}/trace`).then(setEvents).catch((e: ApiError) => setError(e.message)); }, [runId]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!events) return <Skeleton rows={8} />;
  const count = (k: Kind) => events.filter((e) => kindOf(e) === k).length;
  const llmTokens = events.reduce((s, e) => s + (e.kind === "llm_call" ? e.tokens ?? 0 : 0), 0);
  const toggle = (k: Kind) => setOff((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const shown = events.filter((e) => !off.has(kindOf(e)));

  return (
    <>
      <h2><code>{runId}</code> {run && <small className="muted">{run.uc}{run.trip_id && <> · <a href={`#/trips/${run.trip_id}`}>{run.trip_id}</a></>}</small>}</h2>
      <dl className="trace-stats">
        <div><dt>{t("Lời gọi LLM", "LLM calls")}</dt><dd>{count("llm_call")}</dd></div>
        <div><dt>Tool</dt><dd>{count("tool_call")}</dd></div>
        <div><dt>Token</dt><dd>{run ? `${run.tokens_in} + ${run.tokens_out}` : llmTokens}</dd></div>
        <div><dt>{t("Chi phí", "Cost")}</dt><dd>{run ? `$${run.cost_usd.toFixed(4)}` : "?"}</dd></div>
        <div><dt>{t("Độ trễ", "Latency")}</dt><dd>{run ? ms(run.latency_ms) || "…" : "?"}</dd></div>
        <div><dt>Guardrail</dt><dd>{count("guardrail")}</dd></div>
        <div className={count("error") ? "err" : ""}><dt>{t("Lỗi", "Errors")}</dt><dd>{count("error")}</dd></div>
      </dl>
      <div className="chips" role="group" aria-label={t("Lọc loại bước", "Filter step kinds")}>
        {KINDS.filter(([k]) => count(k)).map(([k, vi, en]) => (
          <button key={k} className={`chip ${off.has(k) ? "" : "on"}`} aria-pressed={!off.has(k)} onClick={() => toggle(k)}>{t(vi, en)} {count(k)}</button>
        ))}
      </div>
      {shown.length === 0 && <p className="muted">{t("Không còn bước nào sau khi lọc.", "No steps left after filtering.")}</p>}
      <ol className="trace-events">
        {shown.map((e) => {
          const k = kindOf(e);
          const detail = e.args != null || e.result != null || e.error;
          const head = (
            <>
              <span className="muted tiny">#{e.seq}</span> <b>{e.node}</b> <span className={`tag ${TAG[k] ?? ""}`}>{e.kind}</span>
              {e.name && <code>{e.name}</code>}
              <span className="muted tiny">{[ms(e.duration_ms), e.tokens ? `${e.tokens} token` : ""].filter(Boolean).join(" · ")}</span>
              {e.error && <span className="error small">{e.error.slice(0, 140)}</span>}
            </>
          );
          return (
            <li key={e.seq} className={`ev-${k}`}>
              {detail ? (
                <details>
                  <summary>{head}</summary>
                  {e.args != null && <><p className="tiny muted">args</p><pre>{JSON.stringify(e.args, null, 2)}</pre></>}
                  {e.result != null && <><p className="tiny muted">result</p><pre>{JSON.stringify(e.result, null, 2)}</pre></>}
                  {e.error && <pre className="error">{e.error}</pre>}
                </details>
              ) : <div>{head}</div>}
            </li>
          );
        })}
      </ol>
    </>
  );
}
