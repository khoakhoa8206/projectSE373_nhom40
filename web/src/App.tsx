import { useCallback, useEffect, useState } from "react";
import { api, type ApiError, type Poi, type User } from "./api";
import Home from "./pages/Home";
import PoiPage from "./pages/Poi";
import { PlanPage, TripsPage } from "./pages/Plan";
import ProfilePage from "./pages/Profile";
import TripPage from "./pages/Trip";
import { CreditsPage, MemoryPage, NarratePage, VerifyPage } from "./pages/Tools";
import { Empty } from "./ui";

const NAV = [["/", "Khám phá"], ["/chat", "Hội thoại"], ["/plan", "Lập lịch"], ["/trips", "Chuyến đi"], ["/narrate", "Thuyết minh"], ["/memory", "Bộ nhớ"], ["/verify", "Kiểm chứng"]];
const ACCOUNT_NOTE: Record<string, string> = {
  "u-ha": "Đã có chuyến 3 ngày được duyệt, sự kiện và bộ nhớ",
  "u-minh": "Có lịch trình đang chờ bạn duyệt",
  "u-emma": "English, đã có chuyến 2 ngày được duyệt",
};

export type Shell = { user: User | null; pois: Poi[]; llm: boolean; askLogin: () => void };

function useHash() {
  const [hash, setHash] = useState(location.hash.slice(1) || "/");
  useEffect(() => {
    const on = () => {
      setHash(location.hash.slice(1) || "/");
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHash();
  const [users, setUsers] = useState<User[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [pois, setPois] = useState<Poi[]>([]);
  const [llm, setLlm] = useState(true);
  const [login, setLogin] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api<User[]>("/users"), api<{ user_id: string | null }>("/ui/me"), api<Poi[]>("/ui/catalog"), api<{ llm: boolean }>("/ui/meta")])
      .then(([all, me, catalog, meta]) => {
        setUsers(all);
        setUser(all.find((u) => u.user_id === me.user_id) ?? null);
        setPois(catalog);
        setLlm(meta.llm);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  const askLogin = useCallback(() => setLogin(true), []);
  async function choose(u: User) {
    await api("/session", { json: { user_id: u.user_id } });
    setUser(u);
    setLogin(false);
  }
  async function logout() {
    await api("/ui/logout", { method: "POST" });
    setUser(null);
    location.hash = "/";
  }

  const shell: Shell = { user, pois, llm, askLogin };
  const [path, query] = hash.split("?");
  const parts = path.split("/").filter(Boolean);
  let page;
  if (parts[0] === "poi" && parts[1]) page = <PoiPage key={parts[1]} id={parts[1]} shell={shell} />;
  else if (parts[0] === "chat") page = user
    ? <ProfilePage key={user.user_id} user={user} onExpired={askLogin} />
    : <div className="wrap page"><Empty title="Đăng nhập để trò chuyện với agent"><button className="primary" onClick={askLogin}>Đăng nhập</button></Empty></div>;
  else if (parts[0] === "plan") page = <PlanPage shell={shell} preset={new URLSearchParams(query).get("text") ?? ""} />;
  else if (parts[0] === "trips" && parts[1]) page = <TripPage key={parts[1]} id={parts[1]} run={new URLSearchParams(query).get("run")} shell={shell} />;
  else if (parts[0] === "trips") page = <TripsPage shell={shell} />;
  else if (parts[0] === "narrate") page = <NarratePage shell={shell} preset={new URLSearchParams(query).get("poi")} />;
  else if (parts[0] === "memory") page = <MemoryPage shell={shell} />;
  else if (parts[0] === "verify") page = <VerifyPage shell={shell} />;
  else if (parts[0] === "credits") page = <CreditsPage pois={pois} />;
  else page = <Home shell={shell} />;

  const active = (to: string) => (to === "/" ? parts.length === 0 || parts[0] === "poi" : parts[0] === to.slice(1));
  return (
    <div className="app">
      <header className="top">
        <div className="wrap top-row">
          <a className="logo" href="#/">Cố Đô <span>Guide</span></a>
          <nav className="nav-main" aria-label="Điều hướng chính">
            {NAV.map(([to, label]) => <a key={to} href={`#${to}`} aria-current={active(to) ? "page" : undefined}>{label}</a>)}
          </nav>
          {user ? (
            <div className="account">
              <span>{user.display_name.replace(/ \((hư cấu|fictional)\)/, "")}</span>
              <button className="ghost" onClick={logout}>Đăng xuất</button>
            </div>
          ) : <button className="primary" onClick={askLogin}>Đăng nhập</button>}
        </div>
      </header>
      <OfflineBanner />
      {error && <p className="banner-error" role="alert">{error}</p>}
      <main>{page}</main>
      <footer className="foot">
        <div className="wrap foot-row">
          <div>
            <b>Cố Đô Guide</b>
            <p className="muted small">Đồ án SE373, đề tài 08. Người dùng và lịch sử chuyến đi trong bản demo là hư cấu.</p>
            {!llm && <p className="small"><b>Đang chạy không có khoá LLM:</b> planner là bản giả, thuyết minh và nhật ký chưa dùng được. Graph, tool, validator, RAG và bộ nhớ là code thật của nhóm.</p>}
          </div>
          <p className="muted small">
            Bản đồ <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>.
            Dữ liệu địa điểm OSM và Wikivoyage (CC BY-SA 4.0). Thời tiết: dự báo mock của nhóm; khi bật nguồn thứ hai:{" "}
            <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Weather data by Open-Meteo.com</a> (CC BY 4.0).{" "}
            <a href="#/credits">Nguồn ảnh và giấy phép</a>
          </p>
        </div>
      </footer>
      <nav className="nav-bottom" aria-label="Điều hướng trên điện thoại">
        {NAV.map(([to, label]) => <a key={to} href={`#${to}`} aria-current={active(to) ? "page" : undefined}>{label}</a>)}
      </nav>
      {login && (
        <div className="modal" role="dialog" aria-modal="true" aria-label="Chọn tài khoản demo" onClick={() => setLogin(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h2>Chọn tài khoản demo</h2>
            <p className="muted">Ba người dùng hư cấu, không có dữ liệu thật và không cần mật khẩu.</p>
            {users.map((u) => (
              <button key={u.user_id} className="account-card" onClick={() => choose(u)}>
                <b>{u.display_name}</b>
                <small>{ACCOUNT_NOTE[u.user_id]}</small>
              </button>
            ))}
            <button className="ghost" onClick={() => setLogin(false)}>Đóng</button>
          </div>
        </div>
      )}
    </div>
  );
}

function OfflineBanner() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);
  return online ? null : <p className="banner-error" role="status">Thiết bị đang mất mạng. Agent, lịch trình và bản đồ cần mạng; bật mạng rồi thử lại.</p>;
}
