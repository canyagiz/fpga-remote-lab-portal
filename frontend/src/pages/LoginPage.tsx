import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import PasswordInput from "../components/PasswordInput";
import { useAuth } from "../context/AuthContext";

export default function LoginPage() {
  const { login, verify2FA, resend2FA } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [awaiting2FA, setAwaiting2FA] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendMessage, setResendMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { requires2FA } = await login(username, password);
      if (requires2FA) {
        setAwaiting2FA(true);
      } else {
        navigate("/dashboard");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await verify2FA(code);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verification failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    setResendMessage(null);
    try {
      await resend2FA();
      setResendMessage("A new code has been sent.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to resend code");
    }
  }

  if (awaiting2FA) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>Verification code</h1>
          <p className="hint">We sent a 6-digit code to your email.</p>
          <form onSubmit={handleVerify}>
            <label htmlFor="code">Code</label>
            <input
              id="code"
              className="code-input"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              maxLength={6}
              inputMode="numeric"
              autoFocus
              required
            />
            {error && <p className="error">{error}</p>}
            <button type="submit" disabled={submitting}>
              Verify
            </button>
          </form>
          <button className="link-button" onClick={handleResend}>
            Resend code
          </button>
          {resendMessage && <p className="hint">{resendMessage}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <h1>Sign in</h1>
        <form onSubmit={handleLogin}>
          <label htmlFor="username">Username</label>
          <input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required />

          <label htmlFor="password">Password</label>
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="current-password" required />

          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting}>
            Sign in
          </button>
        </form>
        <p className="hint auth-switch">
          No account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  );
}
