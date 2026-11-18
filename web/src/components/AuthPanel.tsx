import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, type ApiError, type User } from "../api";
import { getLang, t } from "../i18n";

type Mode = "login" | "register";

/** Khung đăng nhập / đăng ký. Màn rộng: hai form cạnh nhau, tấm ảnh Huế trượt qua che form không dùng.
 * Màn hẹp: hai form trượt ngang thay nhau. Form đang ẩn đặt inert nên không tab vào được. */
export default function AuthPanel({ onDone, onClose }: { onDone: (u: User) => void; onClose: () => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    root.current?.querySelector<HTMLInputElement>(`.auth-form.${mode} input`)?.focus();
  }, [mode]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const swap = (m: Mode) => { setMode(m); setError(""); };

  async function send(path: string, body: object) {
    setBusy(true);
    setError("");
    try {
      onDone(await api<User>(path, { json: body }));
    } catch (err) {
      const status = (err as ApiError).status;
      setError(status === 401 ? t("Email hoặc mật khẩu không đúng.", "Wrong email or password.")
        : status === 409 ? t("Email này đã có tài khoản, hãy đăng nhập.", "This email already has an account, please log in.")
        : status === 422 ? t("Thông tin chưa hợp lệ: kiểm tra email và mật khẩu (ít nhất 8 ký tự).", "Invalid details: check your email and password (at least 8 characters).")
        : (err as Error).message);
      setBusy(false);
    }
  }

  function login(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    send("/auth/login", { email: f.get("email"), password: f.get("password") });
  }

  function register(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (f.get("password") !== f.get("confirm")) return setError(t("Hai mật khẩu không khớp.", "Passwords do not match."));
    send("/auth/register", { display_name: f.get("name"), email: f.get("email"), password: f.get("password"), preferred_lang: f.get("lang") });
  }

  const signup = mode === "register";
  return (
    <div ref={root} className={signup ? "auth signup" : "auth"} role="dialog" aria-modal="true"
      aria-labelledby={signup ? "auth-register-title" : "auth-login-title"} onClick={(e) => e.stopPropagation()}>
      <button className="auth-close" aria-label={t("Đóng", "Close")} onClick={onClose}>×</button>

      <form className="auth-form login" inert={signup} onSubmit={login}>
        <h2 id="auth-login-title">{t("Đăng nhập", "Log in")}</h2>
        <p className="muted small">{t("Dùng email và mật khẩu bạn đã đăng ký.", "Use the email and password you signed up with.")}</p>
        <label>Email<input name="email" type="email" autoComplete="username" required maxLength={254} /></label>
        <label>{t("Mật khẩu", "Password")}<input name="password" type="password" autoComplete="current-password" required maxLength={128} /></label>
        {!signup && error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? t("Đang đăng nhập...", "Logging in...") : t("Đăng nhập", "Log in")}</button>
        <p className="auth-switch small">{t("Chưa có tài khoản?", "No account yet?")} <button type="button" className="link" onClick={() => swap("register")}>{t("Đăng ký", "Sign up")}</button></p>
      </form>

      <form className="auth-form register" inert={!signup} onSubmit={register}>
        <h2 id="auth-register-title">{t("Tạo tài khoản", "Create an account")}</h2>
        <label>{t("Tên hiển thị", "Display name")}<input name="name" autoComplete="nickname" required maxLength={80} /></label>
        <label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} /></label>
        <label>{t("Mật khẩu (ít nhất 8 ký tự)", "Password (at least 8 characters)")}<input name="password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} /></label>
        <label>{t("Nhập lại mật khẩu", "Confirm password")}<input name="confirm" type="password" autoComplete="new-password" required minLength={8} maxLength={128} /></label>
        <label>{t("Ngôn ngữ", "Language")}
          <select name="lang" defaultValue={getLang()}>
            <option value="vi">Tiếng Việt</option>
            <option value="en">English</option>
          </select>
        </label>
        {signup && error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? t("Đang tạo...", "Creating...") : t("Đăng ký", "Sign up")}</button>
        <p className="auth-switch small">{t("Đã có tài khoản?", "Already have an account?")} <button type="button" className="link" onClick={() => swap("login")}>{t("Đăng nhập", "Log in")}</button></p>
      </form>

      <div className="auth-overlay-wrap">
        <div className="auth-overlay">
          <div className="auth-panel left" inert={!signup}>
            <p className="auth-brand">Cố Đô Guide</p>
            <h2>{t("Đã có tài khoản?", "Welcome back")}</h2>
            <p>{t("Đăng nhập để xem lại chuyến đi, nhật ký và sở thích đã lưu.", "Log in to see your trips, journal and saved preferences.")}</p>
            <button type="button" onClick={() => swap("login")}>{t("Đăng nhập", "Log in")}</button>
          </div>
          <div className="auth-panel right" inert={signup}>
            <p className="auth-brand">Cố Đô Guide</p>
            <h2>{t("Lần đầu đến Huế?", "New to Hue?")}</h2>
            <p>{t("Tạo tài khoản để agent lập lịch, ghi nhật ký và nhớ sở thích của riêng bạn.", "Create an account so the agent can plan, keep your journal and remember your preferences.")}</p>
            <button type="button" onClick={() => swap("register")}>{t("Đăng ký", "Sign up")}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
