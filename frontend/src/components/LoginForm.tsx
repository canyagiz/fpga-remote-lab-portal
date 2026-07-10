import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import PasswordInput from "./PasswordInput";

interface LoginFormProps {
  onSuccess: () => void;
  onSwitchToRegister: () => void;
}

export default function LoginForm({ onSuccess, onSwitchToRegister }: LoginFormProps) {
  const { login, verify2FA, resend2FA } = useAuth();
  const { showError, showSuccess } = useToast();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [awaiting2FA, setAwaiting2FA] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const { requires2FA } = await login(username, password);
      if (requires2FA) {
        setAwaiting2FA(true);
      } else {
        onSuccess();
      }
    } catch (err) {
      showError(err instanceof ApiError ? err.message : "Login failed");
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
      showError(err instanceof ApiError ? err.message : "Failed to resend code");
    }
  }

  if (awaiting2FA) {
    return (
      <>
        <CardHeader className="p-0">
          <CardTitle className="text-2xl">Verification code</CardTitle>
          <p className="text-sm text-muted-foreground">We sent a 6-digit code to your email.</p>
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
          <Button variant="link" className="mt-3 h-auto p-0" onClick={handleResend}>
            Resend code
          </Button>
        </CardContent>
      </>
    );
  }

  return (
    <>
      <CardHeader className="p-0">
        <CardTitle className="text-2xl">Sign in</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <form onSubmit={handleLogin} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="username">Username</Label>
            <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <PasswordInput
              id="password"
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
              required
            />
          </div>

          <Button type="submit" className="w-full" disabled={submitting}>
            Sign in
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-muted-foreground">
          No account?{" "}
          <button type="button" onClick={onSwitchToRegister} className="font-medium text-primary hover:underline">
            Register
          </button>
        </p>
      </CardContent>
    </>
  );
}
