import { useEffect, useState } from "react";

// Drives a live "resend code" countdown against the backend's rate limit
// (see routers/auth.py - resend_two_factor) instead of just showing its
// error message once and leaving the button clickable again immediately.
export function useResendCooldown() {
  const [secondsLeft, setSecondsLeft] = useState(0);

  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft]);

  const minutes = Math.floor(secondsLeft / 60);
  const seconds = secondsLeft % 60;

  return {
    secondsLeft,
    start: setSecondsLeft,
    label: `${minutes}:${String(seconds).padStart(2, "0")}`,
  };
}
