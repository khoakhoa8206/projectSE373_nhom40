import { useState, type FormEvent } from "react";
import type { ApprovalCardProps } from "../api";

/** Điều khiển tạm P2; có thể thay bằng ApprovalCard P4 qua prop, không giả nhận component P4 đã có. */
export default function ApprovalAdapter({ request, busy, onAnswer }: ApprovalCardProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    void onAnswer({ decision: "approved", response: answers });
  }

  if (request.kind === "ask_user") {
    return (
      <form onSubmit={submit} className="approval">
        <h3>Bổ sung hồ sơ</h3>
        {request.data.conflicts?.length > 0 && <ul className="violations">
          {request.data.conflicts.map((conflict, index) => <li key={index}>{conflict}</li>)}
        </ul>}
        <fieldset disabled={busy}>
          {request.data.questions.map((question) => <label key={question.field}>
            {question.text}
            <input required maxLength={1000} value={answers[question.field] ?? ""}
              onChange={(event) => setAnswers({ ...answers, [question.field]: event.target.value })} />
          </label>)}
          <button className="primary" type="submit">Gửi câu trả lời</button>
        </fieldset>
      </form>
    );
  }
  return (
    <section className="approval">
      <h3>Bạn quyết định lịch trình</h3>
      <p className="muted">Duyệt không xoá vi phạm hoặc xác nhận các dữ kiện còn thiếu.</p>
      <fieldset disabled={busy}>
        <label>Ghi chú muốn sửa
          <textarea maxLength={4000} value={feedback} onChange={(event) => setFeedback(event.target.value)} />
        </label>
        <div className="actions">
          <button className="primary" onClick={() => void onAnswer({ decision: "approved", response: null })}>Duyệt lịch</button>
          <button disabled={!feedback.trim()} onClick={() => void onAnswer({ decision: "edited", response: feedback })}>Yêu cầu sửa</button>
          <button onClick={() => void onAnswer({ decision: "rejected", response: null })}>Không duyệt</button>
        </div>
      </fieldset>
    </section>
  );
}
