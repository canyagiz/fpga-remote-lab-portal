import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
      <div className="flex min-h-[calc(100vh-61px)] items-center justify-center px-6 py-8">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle className="text-2xl">Registration successful</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              You can now{" "}
              <Link to="/login" className="font-medium text-primary hover:underline">
                sign in
              </Link>
              .
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex min-h-[calc(100vh-61px)] items-center justify-center px-6 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Register</CardTitle>
        </CardHeader>
        <CardContent>
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

            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
              Register
            </Button>
          </form>
          <p className="mt-6 text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link to="/login" className="font-medium text-primary hover:underline">
              Sign in
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
