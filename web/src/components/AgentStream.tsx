import { useEffect, useRef, useState } from "react";
import type { InterruptPayload, StreamEvent } from "../api";
import { t } from "../i18n";
import "./components.css";

const KINDS = ["node_start", "node_end", "tool_call", "interrupt", "done", "error"] as const;
type Status = "connecting" | "running" | "reconnecting" | "waiting" | "done" | "failed" | "lost";

const STATUS_TEXT: Record<Status, [string, string]> = {
  connecting: ["Đang kết nối…", "Connecting…"],
  running: ["Agent đang chạy", "Agent is running"],
  reconnecting: ["Mất kết nối, đang kết nối lại…", "Connection lost, reconnecting…"],
  waiting: ["Đang chờ bạn", "Waiting for you"],
  done: ["Hoàn tất", "Done"],
  failed: ["Agent gặp lỗi", "Agent error"],
  lost: ["Mất kết nối tới máy chủ", "Lost connection to the server"],
};
const KIND_TEXT: Record<StreamEvent["kind"], [string, string]> = {
  node_start: ["bắt đầu", "start"],
  node_end: ["xong", "done"],
  tool_call: ["gọi tool", "tool call"],
  interrupt: ["dừng chờ người dùng", "waiting for user"],
  done: ["hoàn tất", "finished"],
  error: ["lỗi", "error"],
};

/** Tiến trình 1 lượt chạy, hiện dần từng bước qua SSE GET /api/runs/{run_id}/stream (đi qua proxy Vite nên cookie session
 * cùng origin). interrupt → onInterrupt(payload), done → onDone(), error → onError(). Ba sự kiện này đều đóng stream:
 * chạy tiếp bằng resume() sẽ có run_id mới. Mất kết nối giữa chừng thì trình duyệt tự nối lại. */
export default function AgentStream({ runId, onInterrupt, onDone, onError }: {
  runId: string;
  onInterrupt?: (p: InterruptPayload) => void;
  onDone?: () => void;
  onError?: () => void;
}) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<Status>("connecting");
  const cb = useRef({ onInterrupt, onDone, onError }); // callback đổi mỗi lần render không được mở lại stream
  cb.current = { onInterrupt, onDone, onError };

  useEffect(() => {
    setEvents([]);
    setStatus("connecting");
    const es = new EventSource(`/api/runs/${runId}/stream`);
    const seen = new Set<string>(); // server gửi kèm `id:` thì lúc tự nối lại có thể gửi trùng
    es.onopen = () => setStatus("running");
    for (const kind of KINDS) {
      es.addEventListener(kind, (e) => {
        if (!(e instanceof MessageEvent)) {
          // "error" trùng tên sự kiện lỗi kết nối của EventSource (không có data)
          setStatus(es.readyState === EventSource.CONNECTING ? "reconnecting" : "lost");
          return;
        }
        if (e.lastEventId) {
          if (seen.has(e.lastEventId)) return;
          seen.add(e.lastEventId);
        }
        const raw = JSON.parse(e.data);
        // SSE của P1 gửi thẳng payload ở interrupt và không có node/ts ở done
        const ev: StreamEvent = { ...raw, kind, node: raw.node ?? "workflow", ts: raw.ts ?? "", payload: kind === "interrupt" ? raw.payload ?? raw : raw.payload };
        setEvents((xs) => [...xs, ev]);
        if (kind === "interrupt" || kind === "done" || kind === "error") es.close();
        if (kind === "interrupt") {
          setStatus("waiting");
          cb.current.onInterrupt?.(ev.payload as InterruptPayload);
        } else if (kind === "done") {
          setStatus("done");
          cb.current.onDone?.();
        } else if (kind === "error") {
          setStatus("failed");
          cb.current.onError?.();
        }
      });
    }
    return () => es.close();
  }, [runId]);

  const busy = status === "running" || status === "connecting" || status === "reconnecting";
  return (
    <section className="trace" aria-live="polite">
      <p className={status === "failed" || status === "lost" ? "error" : status === "reconnecting" ? "warn" : undefined}>
        {busy && <span className="spinner small-spinner" aria-hidden />}
        <b>{t(...STATUS_TEXT[status])}</b> · {events.length} {t("bước", "steps")} · <code>{runId}</code>
      </p>
      <ol className="timeline">
        {events.map((e, i) => (
          <li key={i} className={e.kind === "error" ? "err" : undefined}>
            <time>{e.ts.slice(11, 19)}</time> <b>{e.node}</b> · {t(...KIND_TEXT[e.kind])}
            {(e.tool ?? e.name) && ` · ${e.tool ?? e.name}`}
            {e.duration_ms != null && ` · ${e.duration_ms} ms`}
            {e.kind === "error" && e.payload != null && ` · ${typeof e.payload === "string" ? e.payload : JSON.stringify(e.payload)}`}
          </li>
        ))}
      </ol>
    </section>
  );
}
