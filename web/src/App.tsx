import { useEffect, useState } from "react";
import { api, type ApiError, type User } from "./api";
import MapView from "./MapView";

const USER_KEY = "tourguide.user";

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
      {user ? (
        <main className="home">
          <MapView />
        </main>
      ) : (
        <UserPicker onPick={pick} />
      )}
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
