import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getCaptcha, getCsrfToken, register } from "../api/client";
import PasswordInput from "../components/PasswordInput";
import PasswordStrength from "../components/PasswordStrength";

export default function RegisterPage() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [captchaQuestion, setCaptchaQuestion] = useState("Loading...");
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const [csrfToken, setCsrfToken] = useState("");
  // Hidden from real users via CSS; bots that fill every field trip this.
  const [website, setWebsite] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function loadCaptchaAndCsrf() {
    // Sequential on purpose: both endpoints mutate the session cookie
    // (starlette's SessionMiddleware re-encodes the whole session on every
    // response). Firing them in parallel races two Set-Cookie responses -
    // whichever one the browser applies last silently wins, discarding the
    // other endpoint's write. That's exactly the bug where a correct
    // captcha answer got rejected: the CSRF and captcha writes stomped on
    // each other and only one survived.
    const captcha = await getCaptcha();
    setCaptchaQuestion(captcha.question);
    setCaptchaAnswer("");

    const csrf = await getCsrfToken();
    setCsrfToken(csrf.token);
  }

  useEffect(() => {
    loadCaptchaAndCsrf().catch(() => setCaptchaQuestion("Failed to load - try refreshing."));
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setSubmitting(true);
    try {
      await register({
        username,
        email,
        password,
        captcha_answer: parseInt(captchaAnswer, 10) || 0,
        csrf_token: csrfToken,
        website,
      });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
      await loadCaptchaAndCsrf();
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>Registration successful</h1>
          <p className="hint">
            You can now <Link to="/login">sign in</Link>.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
      <h1>Register</h1>
      <form onSubmit={handleSubmit}>
        <label htmlFor="username">Username</label>
        <input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required />

        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label htmlFor="password">Password</label>
        <PasswordInput
          id="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          minLength={8}
          required
        />
        <PasswordStrength password={password} />

        <label htmlFor="confirmPassword">Confirm password</label>
        <PasswordInput
          id="confirmPassword"
          value={confirmPassword}
          onChange={setConfirmPassword}
          autoComplete="new-password"
          required
        />
        {confirmPassword && password !== confirmPassword && (
          <p className="error">Passwords don't match</p>
        )}

        <label htmlFor="captcha">Security check: {captchaQuestion}</label>
        <input
          id="captcha"
          type="number"
          value={captchaAnswer}
          onChange={(e) => setCaptchaAnswer(e.target.value)}
          required
        />

        {/* Honeypot: hidden from sighted users via CSS, real bots fill it in. */}
        <div className="honeypot" aria-hidden="true">
          <label htmlFor="website">Website</label>
          <input
            id="website"
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </div>

        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={submitting}>
          Register
        </button>
      </form>
      <p className="hint auth-switch">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
      </div>
    </div>
  );
}
