import { useEffect, useState } from "react";
import { api, type ApiError, type MemoryList, type SavedMemory } from "../api";

const KIND_LABEL: Record<SavedMemory["kind"], string> = {
  interest: "Sở thích",
  pace: "Nhịp đi",
  food_like: "Món thích",
  food_dislike: "Món không thích",
  allergy: "Dị ứng",
  dietary: "Ăn kiêng",
  visited_city: "Thành phố đã đi",
  other: "Khác",
};

const day = (iso: string) => new Date(iso).toLocaleDateString("vi-VN");

/** UC-07: xem / sửa / xoá từng mục bộ nhớ, thu hồi đồng ý lưu mục nhạy cảm. Dữ liệu luôn của người dùng trong session. */
export default function Memory({ onExpired }: { onExpired: () => void }) {
  const [data, setData] = useState<MemoryList | null>(null);
  const [editing, setEditing] = useState<{ id: string; value: string } | null>(null);
  const [error, setError] = useState("");

  async function call(path: string, init?: Parameters<typeof api>[1]) {
    setError("");
    try {
      setData(await api<MemoryList>(path, init));
      setEditing(null);
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 401) onExpired();
      else setError(err.message);
    }
  }

  useEffect(() => {
    call("/memory");
  }, []);

  return (
    <main className="memory">
      <h2>Bộ nhớ của bạn</h2>
      <p className="muted small">
        Agent chỉ lưu những mục bạn đã đồng ý sau khi duyệt lịch trình, và dùng chúng để gợi ý cho chuyến sau. Mỗi mục tự
        hết hạn sau 180 ngày.
      </p>
      {error && <p className="error" role="alert">{error}</p>}
      {!data && !error && <p className="muted">Đang tải…</p>}
      {data && data.items.length === 0 && <p className="muted">Chưa có mục nào được lưu.</p>}
      {data && data.items.length > 0 && (
        <ul className="memlist">
          {data.items.map((m) => (
            <li key={m.memory_id}>
              <div className="memhead">
                <strong>{KIND_LABEL[m.kind]}</strong>
                {m.sensitivity === "sensitive" && <span className="tag warn">Nhạy cảm</span>}
                <small>Hết hạn {day(m.expires_at)}</small>
              </div>
              {editing?.id === m.memory_id ? (
                <form
                  className="memedit"
                  onSubmit={(e) => {
                    e.preventDefault();
                    call(`/memory/${m.memory_id}`, { method: "PATCH", json: { value: editing.value } });
                  }}
                >
                  <label className="sr-only" htmlFor={`mem-${m.memory_id}`}>
                    Giá trị mới
                  </label>
                  <input
                    id={`mem-${m.memory_id}`}
                    value={editing.value}
                    maxLength={200}
                    onChange={(e) => setEditing({ id: m.memory_id, value: e.target.value })}
                  />
                  <button className="primary" type="submit">Lưu</button>
                  <button type="button" onClick={() => setEditing(null)}>Huỷ</button>
                </form>
              ) : (
                <div className="memrow">
                  <span>{m.value}</span>
                  {m.kind !== "visited_city" && (
                    <button onClick={() => setEditing({ id: m.memory_id, value: m.value })}>Sửa</button>
                  )}
                  <button
                    onClick={() => confirm(`Xoá "${m.value}" khỏi bộ nhớ?`) && call(`/memory/${m.memory_id}`, { method: "DELETE" })}
                  >
                    Xoá
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {data?.sensitive_consent && (
        <button
          className="danger"
          onClick={() =>
            confirm("Thu hồi đồng ý sẽ xoá mọi mục nhạy cảm (dị ứng, ăn kiêng, đi lại). Tiếp tục?") &&
            call("/memory/consent/revoke", { method: "POST" })
          }
        >
          Thu hồi đồng ý lưu mục nhạy cảm
        </button>
      )}
    </main>
  );
}
