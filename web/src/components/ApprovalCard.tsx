import { useState, type FormEvent } from "react";
import type { Decision, InterruptPayload, MemoryItem } from "../api";
import "./components.css";

type Submit = (decision: Decision, response: unknown) => void;

/** Thẻ duyệt dùng chung cho mọi interrupt, hiển thị theo payload.kind. Chỉ thu quyết định, màn hình tự gọi
 * resume(tripId, {approval_id, decision, response}). response theo kind:
 *   ask_user           approved + {field: câu trả lời}
 *   itinerary_approval approved + null · edited + ghi chú cần sửa · rejected + lý do (hoặc null)
 *   memory_save        approved (giữ hết) / edited (bỏ bớt) / rejected (không lưu gì) + [key các mục được chọn] */
export default function ApprovalCard({ payload, onSubmit, busy = false }: { payload: InterruptPayload; onSubmit: Submit; busy?: boolean }) {
  if (payload.kind === "ask_user") return <AskUser key={payload.approval_id} questions={payload.data.questions} conflicts={payload.data.conflicts} onSubmit={onSubmit} busy={busy} />;
  if (payload.kind === "itinerary_approval") return <ItineraryApproval key={payload.approval_id} onSubmit={onSubmit} busy={busy} />;
  return <MemorySave key={payload.approval_id} items={payload.data.items} onSubmit={onSubmit} busy={busy} />;
}

function AskUser({ questions, conflicts = [], onSubmit, busy }: {
  questions: { field: string; text: string }[];
  conflicts?: unknown[];
  onSubmit: Submit;
  busy: boolean;
}) {
  const shown = questions.slice(0, 3); // hợp đồng: tối đa 3 câu mỗi lần hỏi
  const [answers, setAnswers] = useState<Record<string, string>>({});

  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit("approved", Object.fromEntries(shown.map((q) => [q.field, (answers[q.field] ?? "").trim()])));
  }

  return (
    <form className="approval" onSubmit={submit} aria-label="Agent cần bạn trả lời">
      <h2>Agent cần bạn trả lời</h2>
      {conflicts.length > 0 && (
        <ul className="warn small">
          {conflicts.map((c, i) => (
            <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>
          ))}
        </ul>
      )}
      {shown.map((q, i) => (
        <label key={q.field}>
          {q.text}
          <input required autoFocus={i === 0} value={answers[q.field] ?? ""} onChange={(e) => setAnswers({ ...answers, [q.field]: e.target.value })} />
        </label>
      ))}
      <div className="approval-actions">
        <button type="submit" className="primary" disabled={busy}>Gửi trả lời</button>
      </div>
    </form>
  );
}

function ItineraryApproval({ onSubmit, busy }: { onSubmit: Submit; busy: boolean }) {
  const [note, setNote] = useState("");
  const text = note.trim();
  return (
    <section className="approval" aria-label="Duyệt lịch trình">
      <h2>Duyệt lịch trình</h2>
      <p className="small">Xem lịch trình ở trên. Duyệt để chốt, hoặc ghi chú điều cần sửa để agent lập lại.</p>
      <label>
        Ghi chú <small>(bắt buộc khi yêu cầu sửa)</small>
        <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="vd bỏ Lăng Khải Định, thêm nghỉ trưa" />
      </label>
      <div className="approval-actions">
        <button className="primary" disabled={busy} onClick={() => onSubmit("approved", null)}>Duyệt</button>
        <button disabled={busy || !text} onClick={() => onSubmit("edited", text)}>Sửa</button>
        <button className="danger" disabled={busy} onClick={() => onSubmit("rejected", text || null)}>Từ chối</button>
      </div>
    </section>
  );
}

function MemorySave({ items, onSubmit, busy }: { items: MemoryItem[]; onSubmit: Submit; busy: boolean }) {
  // Mục nhạy cảm (dị ứng, sức khoẻ…) mặc định KHÔNG chọn: người dùng phải tự tick mới lưu
  const [keep, setKeep] = useState(() => new Set(items.filter((m) => m.sensitivity !== "sensitive").map((m) => m.key)));
  const toggle = (key: string) =>
    setKeep((s) => {
      const next = new Set(s);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  const save = () => onSubmit(keep.size === items.length ? "approved" : "edited", [...keep]);

  return (
    <section className="approval" aria-label="Lưu vào bộ nhớ">
      <h2>Lưu vào bộ nhớ cho chuyến sau?</h2>
      <ul className="memory">
        {items.map((m) => (
          <li key={m.key}>
            <label>
              <input type="checkbox" checked={keep.has(m.key)} onChange={() => toggle(m.key)} />
              {m.value}
              {m.sensitivity === "sensitive" && <span className="tag warn">nhạy cảm, chỉ lưu khi bạn chọn</span>}
            </label>
          </li>
        ))}
      </ul>
      <div className="approval-actions">
        <button className="primary" disabled={busy || keep.size === 0} onClick={save}>Lưu mục đã chọn</button>
        <button disabled={busy} onClick={() => onSubmit("rejected", [])}>Không lưu gì</button>
      </div>
    </section>
  );
}
