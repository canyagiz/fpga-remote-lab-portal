import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import * as api from "../api/client";
import { LabUsageStat, MyStats, Reservation, ReservationStatus } from "../api/types";
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

const CHART_DAYS = 14;

interface DayBucket {
  label: string;
  count: number;
  isToday: boolean;
}

// Sign-in timestamps arrive as tz-aware UTC; bucketing uses the browser's
// local calendar day (toDateString), consistent with how every other
// date on the site is shown in local time.
function bucketLoginsByLocalDay(loginTimes: string[]): DayBucket[] {
  const counts = new Map<string, number>();
  for (const iso of loginTimes) {
    const key = new Date(iso).toDateString();
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const buckets: DayBucket[] = [];
  for (let i = CHART_DAYS - 1; i >= 0; i--) {
    const day = new Date();
    day.setDate(day.getDate() - i);
    buckets.push({
      label: day.toLocaleDateString(undefined, { day: "numeric", month: "numeric" }),
      count: counts.get(day.toDateString()) ?? 0,
      isToday: i === 0,
    });
  }
  return buckets;
}

function LoginChart({ loginTimes }: { loginTimes: string[] }) {
  const days = bucketLoginsByLocalDay(loginTimes);
  const max = Math.max(...days.map((d) => d.count), 1);
  const total = days.reduce((sum, d) => sum + d.count, 0);

  if (total === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No sign-ins recorded yet - tracking starts from today, so this chart fills in as you use
        the portal.
      </p>
    );
  }

  return (
    <div className="pt-4">
      <div className="flex h-28 items-end gap-1.5">
        {days.map((d, i) => (
          <div
            key={i}
            className="flex h-full flex-1 items-end"
            title={`${d.count} sign-in${d.count === 1 ? "" : "s"}`}
          >
            <div
              className={`relative w-full rounded-t ${
                d.count > 0 ? (d.isToday ? "bg-primary" : "bg-primary/60") : "bg-muted"
              }`}
              style={{ height: d.count > 0 ? `${(d.count / max) * 100}%` : "3px" }}
            >
              {d.count > 0 && (
                <span className="absolute -top-4 left-1/2 -translate-x-1/2 text-[10px] leading-none text-muted-foreground">
                  {d.count}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1 flex gap-1.5">
        {days.map((d, i) => (
          <span
            key={i}
            className={`flex-1 text-center text-[10px] ${
              d.isToday ? "font-semibold text-foreground" : "text-muted-foreground"
            }`}
          >
            {/* Every other label is dropped so 14 of them don't collide on
                narrow screens; today always shows. */}
            {i % 2 === 1 && !d.isToday ? "" : d.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function LabStatList({ items, emptyText }: { items: LabUsageStat[]; emptyText: string }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ul className="space-y-2.5">
      {items.map((s) => (
        <li key={s.lab_id} className="flex items-center gap-3">
          {s.image_url ? (
            <img src={s.image_url} alt="" className="h-9 w-9 rounded-md object-cover" />
          ) : (
            <div className="h-9 w-9 rounded-md bg-muted" />
          )}
          <span className="flex-1 truncate text-sm font-medium">{s.lab_name}</span>
          <Badge variant="secondary">
            {s.session_count} session{s.session_count === 1 ? "" : "s"}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { showError } = useToast();
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [stats, setStats] = useState<MyStats | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  async function refresh() {
    try {
      const [myReservations, myStats] = await Promise.all([
        api.getMyReservations(),
        api.getMyStats(),
      ]);
      setReservations(myReservations);
      setStats(myStats);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load dashboard");
    }
  }

  useEffect(() => {
    refresh();
    // Reservation status changes on its own (scheduled slots activate,
    // sessions expire) - poll rather than requiring a manual refresh. Kept
    // tight (the backend's own expiry/access-grace sweep now runs every
    // 5s - see services/queue.py) so this reflects a change from another
    // tab/device promptly instead of lagging up to 15s behind it.
    const interval = setInterval(refresh, 3000);
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
  // leaving a stale, now-pointless Finish button up. Same idea for a
  // scheduled reservation nobody accessed within its grace period -
  // access_now itself would already refuse it.
  const visible = reservations.filter((r) => {
    if (r.status === "active" && r.session_ends_at) {
      return new Date(r.session_ends_at).getTime() > now;
    }
    if (r.status === "pending" && r.access_deadline) {
      return new Date(r.access_deadline).getTime() > now;
    }
    return true;
  });

  const reservationSummary = stats
    ? [
        { label: "Total", value: stats.total_reservations },
        { label: "Completed", value: stats.completed_count },
        { label: "Cancelled", value: stats.cancelled_count },
        { label: "Expired", value: stats.expired_count },
        { label: "Upcoming", value: stats.upcoming_count },
      ]
    : [];

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Welcome, {user?.username}</h1>

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
            // Once the scheduled time arrives, access_now only honors this
            // reservation for a short grace period (access_deadline, from
            // the backend - see services/availability.py) before treating
            // it as missed. Count that down visibly instead of just
            // flipping "Not yet" to "Access" with no sense of urgency.
            const graceMs =
              canAccessScheduled && r.access_deadline ? new Date(r.access_deadline).getTime() - now : null;

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
                    <div className="flex shrink-0 items-center gap-2">
                      {graceMs !== null && graceMs > 0 && (
                        <span className="text-sm font-bold text-destructive">
                          {Math.ceil(graceMs / 1000)}s to Access
                        </span>
                      )}
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

      {stats && (
        <>
          <h2 className="mt-10 mb-3 text-lg font-semibold">Your activity</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Labs demoed</CardTitle>
                <CardDescription>Boards you have run at least one session on</CardDescription>
              </CardHeader>
              <CardContent>
                <LabStatList
                  items={stats.labs_demoed}
                  emptyText="Nothing yet - Access a lab to get started."
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Labs completed</CardTitle>
                <CardDescription>Boards with at least one session finished cleanly</CardDescription>
              </CardHeader>
              <CardContent>
                <LabStatList items={stats.labs_completed} emptyText="No completed sessions yet." />
              </CardContent>
            </Card>
          </div>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="text-base">Reservations</CardTitle>
              <CardDescription>Everything you have ever booked, by outcome</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-5 gap-2 max-sm:grid-cols-3">
                {reservationSummary.map((s) => (
                  <div key={s.label} className="rounded-lg border p-3 text-center">
                    <div className="text-2xl font-bold">{s.value}</div>
                    <div className="text-xs text-muted-foreground">{s.label}</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="mt-4">
            <CardHeader>
              <CardTitle className="text-base">Sign-in activity</CardTitle>
              <CardDescription>Your daily sign-ins over the last {CHART_DAYS} days</CardDescription>
            </CardHeader>
            <CardContent>
              <LoginChart loginTimes={stats.login_times} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
