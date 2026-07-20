import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, getCaptcha, getCsrfToken, register } from "../api/client";
import { CaptchaResponse } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { useResendCooldown } from "../lib/useResendCooldown";
import PasswordInput from "./PasswordInput";
import PasswordStrength from "./PasswordStrength";
import PuzzleCaptcha from "./PuzzleCaptcha";

interface RegisterFormProps {
  onSwitchToLogin: () => void;
  /** Called once the post-registration email code has been verified. */
  onSuccess: () => void;
}

export default function RegisterForm({ onSwitchToLogin, onSuccess }: RegisterFormProps) {
  const { verify2FA, resend2FA } = useAuth();
  const { showError, showSuccess } = useToast();
  const resendCooldown = useResendCooldown();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [captcha, setCaptcha] = useState<CaptchaResponse | null>(null);
  const [captchaFailed, setCaptchaFailed] = useState(false);
  const [sliderX, setSliderX] = useState(0);
  const [csrfToken, setCsrfToken] = useState("");
  // Hidden from real users via CSS; bots that fill every field trip this.
  const [website, setWebsite] = useState("");

  const [submitting, setSubmitting] = useState(false);

  // Registration always ends with require_2fa (every new account starts
  // with two_factor_enabled=True - see backend/app/models.py), so the
  // email code step below happens right after signup, not deferred to
  // whatever this person's first sign-in happens to be.
  const [awaitingCode, setAwaitingCode] = useState(false);
  const [verificationMessage, setVerificationMessage] = useState("");
  const [code, setCode] = useState("");

  async function loadCaptchaAndCsrf() {
    // Sequential on purpose: both endpoints mutate the session cookie
    // (starlette's SessionMiddleware re-encodes the whole session on every
    // response). Firing them in parallel races two Set-Cookie responses -
    // whichever one the browser applies last silently wins, discarding the
    // other endpoint's write. That's exactly the bug where a correct
    // captcha answer got rejected: the CSRF and captcha writes stomped on
    // each other and only one survived.
    const captchaData = await getCaptcha();
    setCaptcha(captchaData);
    setCaptchaFailed(false);
    setSliderX(0);

    const csrf = await getCsrfToken();
    setCsrfToken(csrf.token);
  }

  useEffect(() => {
    loadCaptchaAndCsrf().catch(() => setCaptchaFailed(true));
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (password !== confirmPassword) {
      showError("Passwords don't match");
      return;
    }
    if (password.length < 8) {
      showError("Password must be at least 8 characters");
      return;
    }

    setSubmitting(true);
    try {
      const result = await register({
        username,
        email,
        password,
        captcha_answer: sliderX,
        csrf_token: csrfToken,
        website,
      });
      setVerificationMessage(result.message ?? "We sent a verification code to your email.");
      setAwaitingCode(true);
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Registration failed");
      await loadCaptchaAndCsrf();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await verify2FA(code);
      onSuccess();
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Verification failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    try {
      await resend2FA();
      showSuccess("A new code has been sent.");
    } catch (err) {
      if (err instanceof ApiError && err.retryAfterSeconds) {
        resendCooldown.start(err.retryAfterSeconds);
      }
      showError(err instanceof ApiError ? err.message : "Failed to resend code");
    }
  }

  if (awaitingCode) {
    return (
      <>
        <CardHeader className="p-0">
          <CardTitle className="text-2xl">Verify your email</CardTitle>
          <p className="text-sm text-muted-foreground">{verificationMessage}</p>
        </CardHeader>
        <CardContent className="p-0">
          <form onSubmit={handleVerify} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="code">Code</Label>
              <Input
                id="code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                maxLength={6}
                inputMode="numeric"
                autoFocus
                required
                className="text-center text-2xl tracking-[0.5em]"
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              Verify
            </Button>
          </form>
          <Button
            variant="link"
            className="mt-3 h-auto p-0"
            onClick={handleResend}
            disabled={resendCooldown.secondsLeft > 0}
          >
            {resendCooldown.secondsLeft > 0 ? `Resend code (${resendCooldown.label})` : "Resend code"}
          </Button>
        </CardContent>
      </>
    );
  }

  return (
    <>
      <CardHeader className="p-0">
        <CardTitle className="text-2xl">Register</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="username">Username</Label>
            <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <PasswordInput
              id="password"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
              minLength={8}
              required
            />
            <PasswordStrength password={password} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="confirmPassword">Confirm password</Label>
            <PasswordInput
              id="confirmPassword"
              value={confirmPassword}
              onChange={setConfirmPassword}
              autoComplete="new-password"
              required
            />
            {confirmPassword && password !== confirmPassword && (
              <p className="text-sm text-destructive">Passwords don't match</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label>Security check</Label>
            {captcha ? (
              <PuzzleCaptcha
                backgroundImage={captcha.background_image}
                pieceImage={captcha.piece_image}
                canvasWidth={captcha.canvas_width}
                canvasHeight={captcha.canvas_height}
                pieceWidth={captcha.piece_width}
                pieceHeight={captcha.piece_height}
                pieceTop={captcha.piece_top}
                value={sliderX}
                onChange={setSliderX}
                onReload={() => loadCaptchaAndCsrf().catch(() => setCaptchaFailed(true))}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                {captchaFailed ? "Failed to load - try refreshing." : "Loading..."}
              </p>
            )}
          </div>

          {/* Honeypot: hidden from sighted users, real bots fill it in. */}
          <div className="absolute -left-[9999px]" aria-hidden="true">
            <Label htmlFor="website">Website</Label>
            <Input
              id="website"
              tabIndex={-1}
              autoComplete="off"
              value={website}
              onChange={(e) => setWebsite(e.target.value)}
            />
          </div>

          <Button type="submit" className="w-full" disabled={submitting}>
            Register
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <button type="button" onClick={onSwitchToLogin} className="font-medium text-primary hover:underline">
            Sign in
          </button>
        </p>
      </CardContent>
    </>
  );
}
