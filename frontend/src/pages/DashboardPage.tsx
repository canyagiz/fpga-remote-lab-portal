import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import * as api from "../api/client";
import { Reservation, ReservationStatus } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { openLabWindow } from "../lib/labWindow";

const statusVariant: Record<ReservationStatus, "success" | "warning" | "secondary"> = {
  active: "success",
  pending: "warning",
  cancelled: "secondary",
  expired: "secondary",
  completed: "secondary",
};

function formatCountdown(ms: number): string {
  const totalSeconds = Math.max(Math.floor(ms / 1000), 0);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { showError } = useToast();
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  async function refresh() {
    try {
      setReservations(await api.getMyReservations());
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load reservations");
    }
  }

  useEffect(() => {
    refresh();
    // Reservation status changes on its own (scheduled slots activate,
    // sessions expire) - poll rather than requiring a manual refresh.
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, []);

  // Drives the countdowns and the active-session auto-hide below, on a
  // faster tick than the API poll so the UI doesn't wait up to 15s (or the
  // sweep's own interval) to reflect time simply running out.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  async function runAction(id: number, action: (id: number) => Promise<Reservation>) {
    setBusyId(id);
    try {
      await action(id);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  async function accessLab(labId: number, reservationId: number) {
    setBusyId(reservationId);
    try {
      // Activates a scheduled reservation whose time has come (or resumes
      // an already-active one) and opens the hardware - no need to visit
      // the Labs page separately.
      await api.accessNow(labId);
      const access = await api.accessLab(labId);
      openLabWindow(labId, access.backend_url);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to access lab");
    } finally {
      setBusyId(null);
    }
  }

  // A session past its allotted time is already over - Finish can no
  // longer close it (the backend rejects that; the background sweep marks
  // it expired shortly) - so drop it from view immediately instead of
  // leaving a stale, now-pointless Finish button up for up to a minute.
  const visible = reservations.filter((r) => {
    if (r.status !== "active" || !r.session_ends_at) return true;
    return new Date(r.session_ends_at).getTime() > now;
  });

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Welcome, {user?.username}</h1>
      <Link to="/labs" className="mt-1 inline-block text-sm font-medium text-primary hover:underline">
        Browse labs
      </Link>

      <h2 className="mt-8 mb-3 text-lg font-semibold">My reservations</h2>
      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">No open reservations.</p>
      ) : (
        <ul className="space-y-3">
          {visible.map((r) => {
            const scheduledStart =
              r.reservation_date && r.reservation_time
                ? new Date(`${r.reservation_date}T${r.reservation_time}Z`)
                : null;
            const canAccessScheduled = scheduledStart !== null && now >= scheduledStart.getTime();
            const remainingMs = r.session_ends_at ? new Date(r.session_ends_at).getTime() - now : null;

            return (
              <li key={r.id}>
                <Card>
                  <CardContent className="flex items-center justify-between p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <strong className="font-semibold">{r.lab_name}</strong>
                      <Badge variant={statusVariant[r.status]}>{r.status}</Badge>
                      {scheduledStart && (
                        <span className="text-sm text-muted-foreground">
                          scheduled for{" "}
                          {scheduledStart.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                        </span>
                      )}
                      {r.status === "active" && remainingMs !== null && (
                        <span className="text-sm text-muted-foreground">
                          {formatCountdown(remainingMs)} remaining
                        </span>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      {r.status === "pending" && (
                        <Button
                          size="sm"
                          disabled={busyId === r.id || !canAccessScheduled}
                          title={canAccessScheduled ? undefined : "Not available until the scheduled time"}
                          onClick={() => accessLab(r.lab_id, r.id)}
                        >
                          {canAccessScheduled ? "Access" : "Not yet"}
                        </Button>
                      )}
                      {r.status === "active" && (
                        <>
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={busyId === r.id}
                            onClick={() => accessLab(r.lab_id, r.id)}
                          >
                            Access
                          </Button>
                          <Button
                            size="sm"
                            disabled={busyId === r.id}
                            onClick={() => runAction(r.id, api.completeLabUsage)}
                          >
                            Finish
                          </Button>
                        </>
                      )}
                      {(r.status === "pending" || r.status === "active") && (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={busyId === r.id}
                          onClick={() => runAction(r.id, api.cancelReservation)}
                        >
                          Cancel
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
