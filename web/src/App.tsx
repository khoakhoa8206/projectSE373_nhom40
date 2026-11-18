import { useCallback, useEffect, useState } from "react";
import { api, type ApiError, type Poi, type User } from "./api";
import AuthPanel from "./components/AuthPanel";
import { getLang, setLang, t, type Lang } from "./i18n";
import Home from "./pages/Home";
import PoiPage from "./pages/Poi";
import { PlanPage, TripsPage } from "./pages/Plan";
import ProfilePage from "./pages/Profile";
import TripPage from "./pages/Trip";
import { CreditsPage, MemoryPage, NarratePage, VerifyPage } from "./pages/Tools";
import { Empty } from "./ui";

const NAV = () => [["/", t("Khám phá", "Explore")], ["/chat", t("Hội thoại", "Chat")], ["/plan", t("Lập lịch", "Plan")], ["/trips", t("Chuyến đi", "Trips")],
  ["/narrate", t("Thuyết minh", "Narration")], ["/memory", t("Bộ nhớ", "Memory")], ["/verify", t("Kiểm chứng", "Fact check")]];

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
  const [user, setUser] = useState<User | null>(null);
  const [pois, setPois] = useState<Poi[]>([]);
  const [llm, setLlm] = useState(true);
  const [login, setLogin] = useState(false);
  const [error, setError] = useState("");
  const [lang, setLangState] = useState<Lang>(getLang());
  const switchLang = (l: Lang) => { setLang(l); setLangState(l); }; // App render lại cả cây nên mọi t() đổi theo

  useEffect(() => {
    Promise.all([api<User | null>("/auth/me"), api<Poi[]>("/ui/catalog"), api<{ llm: boolean }>("/ui/meta")])
      .then(([me, catalog, meta]) => {
        setUser(me);
        setPois(catalog);
        setLlm(meta.llm);
      })
      .catch((e: ApiError) => setError(e.message));
  }, []);

  const askLogin = useCallback(() => setLogin(true), []);
  function signedIn(u: User) {
    setUser(u);
    setLogin(false);
    switchLang(u.preferred_lang);
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
    : <div className="wrap page"><Empty title={t("Đăng nhập để trò chuyện với agent", "Log in to chat with the agent")}><button className="primary" onClick={askLogin}>{t("Đăng nhập", "Log in")}</button></Empty></div>;
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
          <nav className="nav-main" aria-label={t("Điều hướng chính", "Main navigation")}>
            {NAV().map(([to, label]) => <a key={to} href={`#${to}`} aria-current={active(to) ? "page" : undefined}>{label}</a>)}
          </nav>
          <div className="lang-switch" role="group" aria-label={t("Ngôn ngữ giao diện", "Interface language")}>
            <button aria-pressed={lang === "vi"} title="Tiếng Việt" onClick={() => switchLang("vi")}>VN</button>
            <button aria-pressed={lang === "en"} title="English" onClick={() => switchLang("en")}>US</button>
          </div>
          {user ? (
            <div className="account">
              <span>{user.display_name.replace(/ \((hư cấu|fictional)\)/, "")}</span>
              <button className="ghost" onClick={logout}>{t("Đăng xuất", "Log out")}</button>
            </div>
          ) : <button className="primary" onClick={askLogin}>{t("Đăng nhập", "Log in")}</button>}
        </div>
      </header>
      <OfflineBanner />
      {error && <p className="banner-error" role="alert">{error}</p>}
      <main>{page}</main>
      <footer className="foot">
        <div className="wrap foot-row">
          <div>
            <b>Cố Đô Guide</b>
            <p className="muted small">{t("Đồ án SE373, đề tài 08.", "SE373 course project, topic 08.")}</p>
            {!llm && <p className="small"><b>{t("Đang chạy không có khoá LLM:", "Running without an LLM key:")}</b> {t("planner là bản giả, thuyết minh và nhật ký chưa dùng được. Graph, tool, validator, RAG và bộ nhớ là code thật của nhóm.", "the planner is a stub, narration and journal are unavailable. Graph, tools, validator, RAG and memory are the team's real code.")}</p>}
          </div>
          <p className="muted small">
            {t("Bản đồ", "Map")} <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a>.{" "}
            {t("Dữ liệu địa điểm OSM và Wikivoyage (CC BY-SA 4.0). Thời tiết: dự báo mock của nhóm; khi bật nguồn thứ hai:", "Place data from OSM and Wikivoyage (CC BY-SA 4.0). Weather: the team's mock forecast; when the second source is on:")}{" "}
            <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Weather data by Open-Meteo.com</a> (CC BY 4.0).{" "}
            <a href="#/credits">{t("Nguồn ảnh và giấy phép", "Photo credits and licences")}</a>
          </p>
        </div>
      </footer>
      <nav className="nav-bottom" aria-label={t("Điều hướng trên điện thoại", "Mobile navigation")}>
        {NAV().map(([to, label]) => <a key={to} href={`#${to}`} aria-current={active(to) ? "page" : undefined}>{label}</a>)}
      </nav>
      {login && (
        <div className="modal" onClick={() => setLogin(false)}>
          <AuthPanel onDone={signedIn} onClose={() => setLogin(false)} />
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
  return online ? null : <p className="banner-error" role="status">{t("Thiết bị đang mất mạng. Agent, lịch trình và bản đồ cần mạng; bật mạng rồi thử lại.", "You are offline. The agent, itineraries and map need a connection; reconnect and try again.")}</p>;
}
