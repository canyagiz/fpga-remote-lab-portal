import { FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, getCaptcha, getCsrfToken, register } from "../api/client";
import { useToast } from "../context/ToastContext";
import PasswordInput from "./PasswordInput";
import PasswordStrength from "./PasswordStrength";

interface RegisterFormProps {
  onSwitchToLogin: () => void;
  /** Called once the post-registration countdown finishes - closes the modal. */
  onSuccess: () => void;
}

export default function RegisterForm({ onSwitchToLogin, onSuccess }: RegisterFormProps) {
  const { showError } = useToast();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [captchaQuestion, setCaptchaQuestion] = useState("Loading...");
  const [captchaAnswer, setCaptchaAnswer] = useState("");
  const [csrfToken, setCsrfToken] = useState("");
  // Hidden from real users via CSS; bots that fill every field trip this.
  const [website, setWebsite] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [countdown, setCountdown] = useState(3);

  useEffect(() => {
    if (!success) return;
    if (countdown <= 0) {
      onSuccess();
      return;
    }
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [success, countdown, onSuccess]);

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
      showError(err instanceof ApiError ? err.message : "Registration failed");
      await loadCaptchaAndCsrf();
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <>
        <CardHeader className="p-0">
          <CardTitle className="text-2xl">Registration successful</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <p className="text-sm text-muted-foreground">
            Redirecting to the main menu in {countdown}...
          </p>
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
            <Label htmlFor="captcha">Security check: {captchaQuestion}</Label>
            <Input
              id="captcha"
              type="number"
              value={captchaAnswer}
              onChange={(e) => setCaptchaAnswer(e.target.value)}
              required
            />
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
