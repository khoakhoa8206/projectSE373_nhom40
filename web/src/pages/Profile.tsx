import { useEffect, useState, type ComponentType, type FormEvent } from "react";
import { api, ApiError, watchRun, type ApprovalAnswer, type ApprovalCardProps, type ApprovalRequest, type Itinerary, type User } from "../api";
import ApprovalAdapter from "../components/ApprovalAdapter";
import { t } from "../i18n";
import ItineraryPage from "./Itinerary";

type ChatMessage = { role: "user" | "assistant"; text: string };
type Saved = { tripId: string | null; runId: string | null };

function restore(userId: string): Saved {
  try {
    const data = JSON.parse(sessionStorage.getItem(`hue.chat.${userId}`) ?? "null");
    return { tripId: typeof data?.tripId === "string" ? data.tripId : null,
      runId: typeof data?.runId === "string" ? data.runId : null };
  } catch { return { tripId: null, runId: null }; }
}

export default function ProfilePage({ user, onExpired, ApprovalCard = ApprovalAdapter }: {
  user: User;
  onExpired: () => void;
  ApprovalCard?: ComponentType<ApprovalCardProps>;
}) {
  const [saved] = useState(() => restore(user.user_id));
  const [tripId, setTripId] = useState<string | null>(saved.tripId);
  const [activeRun, setActiveRun] = useState<{ id: string } | null>(saved.runId ? { id: saved.runId } : null);
  const [pending, setPending] = useState<ApprovalRequest | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [itinerary, setItinerary] = useState<Itinerary | null>(null);

  useEffect(() => {
    try { sessionStorage.setItem(`hue.chat.${user.user_id}`, JSON.stringify({ tripId, runId: activeRun?.id ?? null })); }
    catch { /* Không lưu nội dung hội thoại/key; storage bị chặn không làm hỏng trang. */ }
  }, [tripId, activeRun, user.user_id]);

  // Hội thoại lấy từ server (bảng messages): rời trang rồi quay lại vẫn thấy, agent vẫn chạy nền trong lúc đó.
  async function loadMessages(trip = tripId) {
    if (!trip) return;
    try {
      const rows = await api<{ role: ChatMessage["role"]; content: string }[]>(`/ui/trips/${encodeURIComponent(trip)}/messages`);
      setMessages(rows.map((r) => ({ role: r.role, text: r.content })));
    } catch { /* giữ nội dung đang hiện nếu chưa tải được */ }
  }
  useEffect(() => { void loadMessages(); }, []);

  async function loadItinerary() {
    if (!tripId) return;
    try { setItinerary(await api<Itinerary>(`/trips/${encodeURIComponent(tripId)}/itinerary`)); }
    catch (cause) { if ((cause as ApiError).status !== 404) setError((cause as Error).message); }
  }

  useEffect(() => {
    if (!activeRun) return;
    setBusy(true);
    return watchRun(activeRun.id, {
      onInterrupt: (request) => {
        setPending(request);
        setBusy(false);
        void loadMessages(); // câu hỏi ask_user đã được lưu thành tin nhắn của agent
        if (request.kind !== "ask_user") void loadItinerary();
      },
      onDone: (data) => {
        setBusy(false);
        setActiveRun(null);
        void loadMessages();
        void loadItinerary();
      },
      onError: (message) => { setBusy(false); setError(message); },
    });
  }, [activeRun, tripId]);

  function showError(cause: unknown) {
    const failure = cause as ApiError;
    if (failure.status === 401) onExpired();
    setError(failure.status === 404 || failure.status === 405
      ? t("Backend hiện chưa có API messages/resume của P1. Bạn có thể dùng Nhập nhanh; không có kết quả hội thoại giả.", "The backend does not have the messages/resume API yet. Use quick entry instead; no fake chat results are shown.")
      : failure.message);
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy || pending || activeRun) return;
    const content = text.trim();
    setBusy(true); setError("");
    try {
      const trip = tripId ?? (await api<{ trip_id: string }>("/trips", { json: {} })).trip_id;
      setTripId(trip);
      const result = await api<{ run_id: string }>(`/trips/${encodeURIComponent(trip)}/messages`, { json: { text: content } });
      setMessages((old) => [...old, { role: "user", text: content }]);
      setText(""); setActiveRun({ id: result.run_id });
    } catch (cause) { setBusy(false); showError(cause); }
  }

  async function resume(answer: ApprovalAnswer) {
    if (!pending || !tripId || busy) return;
    setBusy(true); setError("");
    try {
      const result = await api<{ run_id: string }>(`/trips/${encodeURIComponent(tripId)}/resume`, {
        json: { approval_id: pending.approval_id, ...answer },
      });
      if (pending.kind === "ask_user") setMessages((old) => [...old, { role: "user", text: JSON.stringify(answer.response) }]);
      setPending(null); setActiveRun({ id: result.run_id });
    } catch (cause) { setBusy(false); showError(cause); }
  }

  return <main className="chat-page">
    <section className="chat-card">
      <h2>{t("Trao đổi hồ sơ chuyến đi", "Trip profile chat")}</h2>
      <p className="muted">{t("Chỉ hỗ trợ Huế. Agent hỏi tối đa 3 câu/lượt, không tự đoán dữ kiện thiếu.", "Hue only. The agent asks at most 3 questions per turn and never guesses missing details.")}</p>
      {saved.tripId && <p className="muted">{t("Đang tiếp tục chuyến trước. Agent vẫn chạy nền khi bạn sang trang khác.", "Continuing your previous trip. The agent keeps running in the background when you leave this page.")}</p>}
      <div role="log" aria-label={t("Hội thoại chuyến đi", "Trip chat")} aria-live="polite" className="chat-log">
        {messages.map((message, index) => <p key={index} className={`bubble ${message.role}`}>
          <strong>{message.role === "user" ? t("Bạn", "You") : "Agent"}: </strong>{message.text}
        </p>)}
      </div>
      <form onSubmit={send}>
        <label>{t("Yêu cầu của bạn", "Your request")}
          <textarea required maxLength={4000} value={text} disabled={busy || !!pending || !!activeRun}
            placeholder={t("Từ 27/11 đến 29/11/2026 nhà mình đi Huế…", "From 27/11 to 29/11/2026 our family is visiting Hue…")} onChange={(event) => setText(event.target.value)} />
        </label>
        <button type="submit" className="primary" disabled={busy || !!pending || !!activeRun || !text.trim()}>{t("Gửi", "Send")}</button>
      </form>
      {busy && <p role="status">{t("Agent đang xử lý… Không gửi lại yêu cầu.", "The agent is working… Please don't resend.")}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {error && activeRun && <button disabled={busy} onClick={() => { setError(""); setActiveRun({ id: activeRun.id }); }}>{t("Kết nối lại run", "Reconnect to run")}</button>}
      {pending && <ApprovalCard key={pending.approval_id} request={pending} busy={busy} onAnswer={resume} />}
    </section>
    {itinerary && <ItineraryPage itinerary={itinerary} />}
  </main>;
}
