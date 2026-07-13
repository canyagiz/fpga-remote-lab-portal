import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import * as api from "../api/client";
import { Lab, LabStatus } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import { openLabWindow } from "../lib/labWindow";

const statusVariant: Record<LabStatus, "success" | "warning"> = {
  available: "success",
  occupied: "warning",
};

const pad = (n: number) => String(n).padStart(2, "0");

// The date/time inputs hold the user's *local* wall-clock time. A booking
// must start at least 5 minutes out (enforced server-side too). Default to
// now + 6 min, not +5: the input only holds whole minutes, so truncating
// "now" (which has seconds) down to HH:MM already loses up to 59s of the
// margin - by the time the form is actually submitted, +5 min from the
// truncated value can land a few seconds under the server's 5-minute
// floor, forcing the user to bump the time by hand. +6 min keeps at least
// ~60s of slack after truncation.
function defaultReservationDateTime() {
  const t = new Date(Date.now() + 6 * 60 * 1000);
  return {
    date: `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`,
    time: `${pad(t.getHours())}:${pad(t.getMinutes())}`,
  };
}

// Convert the local date/time the user picked into the UTC parts the
// backend stores and compares against (it works entirely in UTC).
function localToUtcParts(dateStr: string, timeStr: string) {
  const local = new Date(`${dateStr}T${timeStr}`);
  return {
    date: `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())}`,
    time: `${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}`,
  };
}

// "Available now", or the absolute local time plus a live countdown -
// e.g. "at 14:32 (in 3m 12s)".
function formatAvailability(nextAvailableAt: string | null, nowMs: number): string {
  if (nextAvailableAt === null) return "Available now";
  const targetMs = new Date(nextAvailableAt).getTime();
  const diffMs = targetMs - nowMs;
  if (diffMs <= 0) return "Available now";
  const totalSeconds = Math.floor(diffMs / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const relative = h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
  const clock = new Date(targetMs).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `Available at ${clock} (in ${relative})`;
}

export default function LabsPage() {
  const { user } = useAuth();
  const { showError } = useToast();
  const navigate = useNavigate();
  const [labs, setLabs] = useState<Lab[]>([]);
  const [busyLabId, setBusyLabId] = useState<number | null>(null);
  const [schedulingLabId, setSchedulingLabId] = useState<number | null>(null);
  const { date: defaultDate, time: defaultTime } = defaultReservationDateTime();
  const [reservationDate, setReservationDate] = useState(defaultDate);
  const [reservationTime, setReservationTime] = useState(defaultTime);

  const [newLabName, setNewLabName] = useState("");
  const [newLabDescription, setNewLabDescription] = useState("");
  const [now, setNow] = useState(() => Date.now());

  async function refresh() {
    try {
      setLabs(await api.getLabs());
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load labs");
    }
  }

  useEffect(() => {
    refresh();
    // Someone else's reservation can change a card's availability at any
    // time - poll rather than requiring a manual refresh. Kept tight (the
    // backend's own expiry/access-grace sweep now runs every 5s - see
    // services/queue.py) so a card showing "Available now" doesn't sit
    // stale for up to 15s after the board actually stopped being free.
    const poll = setInterval(refresh, 3000);
    return () => clearInterval(poll);
  }, []);

  // Drives the "Available in Xm Ys" countdown on a faster tick than the
  // API poll above, so it counts down smoothly instead of jumping every 15s.
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, []);

  async function handleAccess(lab: Lab) {
    setBusyLabId(lab.id);
    try {
      // Claim the board for right now: activates a scheduled reservation
      // whose time has come, or starts a fresh session if the board is
      // free. If it isn't available for us this instant, access-now throws
      // a 409 whose message we surface as a toast (no queue, no redirect).
      await api.accessNow(lab.id);
      const access = await api.accessLab(lab.id);
      openLabWindow(lab.id, access.backend_url);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to access lab");
      // The card's "Available now" was stale by the time this was clicked
      // (someone else just took the board, or the moment simply passed) -
      // don't leave it showing the wrong thing until the next 3s poll.
      await refresh();
    } finally {
      setBusyLabId(null);
    }
  }

  async function handleSchedule(e: FormEvent, labId: number) {
    e.preventDefault();
    setBusyLabId(labId);
    try {
      const utc = localToUtcParts(reservationDate, reservationTime);
      await api.makeReservation(labId, utc.date, utc.time);
      navigate("/dashboard");
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to reserve");
    } finally {
      setBusyLabId(null);
    }
  }

  async function handleCreateLab(e: FormEvent) {
    e.preventDefault();
    try {
      await api.createLab(newLabName, newLabDescription);
      setNewLabName("");
      setNewLabDescription("");
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to create lab");
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Labs</h1>

      <div className="mt-6 grid gap-6 sm:grid-cols-2 xl:grid-cols-3">
        {labs.map((lab) => (
          <Card key={lab.id} className="flex flex-col overflow-hidden pt-0">
            {lab.image_url && (
              <img
                src={lab.image_url}
                alt={lab.name}
                className="h-40 w-full border-b border-border bg-white object-contain p-4"
              />
            )}
            <div className="bg-blue-600 px-5 py-3">
              <h3 className="font-semibold text-white">{lab.name}</h3>
            </div>
            <CardContent className="flex flex-1 flex-col gap-4 pt-5">
              {lab.is_public && (
                <p
                  className={
                    "text-sm font-medium " +
                    (lab.next_available_at === null || new Date(lab.next_available_at).getTime() <= now
                      ? "text-success"
                      : "text-muted-foreground")
                  }
                >
                  {formatAvailability(lab.next_available_at, now)}
                </p>
              )}
              <p className="text-sm text-muted-foreground">{lab.description}</p>

              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={statusVariant[lab.status]}>{lab.status}</Badge>
                {lab.queue_count > 0 && (
                  <span className="text-sm text-muted-foreground">{lab.queue_count} in queue</span>
                )}
              </div>

              <div className="mt-auto space-y-2">
                <Button
                  className="w-full bg-blue-600 hover:bg-blue-700"
                  disabled={!lab.is_public || busyLabId === lab.id}
                  title={lab.is_public ? undefined : "This lab isn't publicly available yet"}
                  onClick={() => handleAccess(lab)}
                >
                  {lab.is_public ? "Access" : "Coming soon"}
                </Button>
                {lab.is_public && (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="w-full"
                    onClick={() => setSchedulingLabId(schedulingLabId === lab.id ? null : lab.id)}
                  >
                    Reserve for later
                  </Button>
                )}
              </div>

              {schedulingLabId === lab.id && (
                <form
                  className="flex flex-wrap items-end gap-3 border-t border-border pt-4"
                  onSubmit={(e) => handleSchedule(e, lab.id)}
                >
                  <div className="space-y-1.5">
                    <Label htmlFor={`date-${lab.id}`}>Date</Label>
                    <Input
                      id={`date-${lab.id}`}
                      type="date"
                      value={reservationDate}
                      onChange={(e) => setReservationDate(e.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor={`time-${lab.id}`}>Time</Label>
                    <Input
                      id={`time-${lab.id}`}
                      type="time"
                      value={reservationTime}
                      onChange={(e) => setReservationTime(e.target.value)}
                      required
                    />
                  </div>
                  <Button type="submit" size="sm" disabled={busyLabId === lab.id}>
                    Confirm reservation
                  </Button>
                </form>
              )}

              <div className="flex divide-x divide-border border-t border-border pt-3 text-xs">
                <details className="flex-1 px-2">
                  <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                    Keywords
                  </summary>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {lab.keywords?.map((k) => (
                      <Badge key={k} variant="outline">
                        {k}
                      </Badge>
                    ))}
                  </div>
                </details>
                <details className="flex-1 px-2">
                  <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                    Resources
                  </summary>
                  <p className="mt-2 text-muted-foreground">
                    {lab.status === "available" ? "1 board available" : "Currently in use"}
                  </p>
                </details>
                <details className="flex-1 px-2">
                  <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground">
                    Features
                  </summary>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {lab.features?.map((f) => (
                      <Badge key={f} variant="outline">
                        {f}
                      </Badge>
                    ))}
                  </div>
                </details>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {user?.role === "admin" && (
        <Card className="mt-10">
          <CardHeader>
            <CardTitle className="text-lg">Add a lab (admin)</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateLab} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="newLabName">Name</Label>
                <Input id="newLabName" value={newLabName} onChange={(e) => setNewLabName(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="newLabDescription">Description</Label>
                <textarea
                  id="newLabDescription"
                  value={newLabDescription}
                  onChange={(e) => setNewLabDescription(e.target.value)}
                  required
                  className="flex min-h-20 w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
              <Button type="submit">Create lab</Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
