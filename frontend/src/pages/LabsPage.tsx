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

const statusVariant: Record<LabStatus, "success" | "warning"> = {
  available: "success",
  occupied: "warning",
};

function defaultReservationDateTime() {
  const inTenMinutes = new Date(Date.now() + 10 * 60 * 1000);
  const date = inTenMinutes.toISOString().slice(0, 10);
  const time = inTenMinutes.toTimeString().slice(0, 5);
  return { date, time };
}

async function tryAccess(labId: number) {
  try {
    return await api.accessLab(labId);
  } catch (err) {
    if (err instanceof api.ApiError && err.status === 403) return null;
    throw err;
  }
}

export default function LabsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [labs, setLabs] = useState<Lab[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyLabId, setBusyLabId] = useState<number | null>(null);
  const [schedulingLabId, setSchedulingLabId] = useState<number | null>(null);
  const { date: defaultDate, time: defaultTime } = defaultReservationDateTime();
  const [reservationDate, setReservationDate] = useState(defaultDate);
  const [reservationTime, setReservationTime] = useState(defaultTime);

  const [newLabName, setNewLabName] = useState("");
  const [newLabDescription, setNewLabDescription] = useState("");

  async function refresh() {
    try {
      setLabs(await api.getLabs());
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Failed to load labs");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleAccess(lab: Lab) {
    setBusyLabId(lab.id);
    setError(null);
    try {
      // The user might already hold an active reservation (e.g. came back
      // to this page mid-session) - open the hardware directly if so.
      const existing = await tryAccess(lab.id);
      if (existing) {
        window.open(existing.backend_url, "_blank", "noopener,noreferrer");
        return;
      }

      // Otherwise join the queue. If the lab is free this promotes the
      // reservation straight to `active`, so retry the access check once.
      await api.joinQueue(lab.id);
      const afterJoin = await tryAccess(lab.id);
      if (afterJoin) {
        window.open(afterJoin.backend_url, "_blank", "noopener,noreferrer");
      } else {
        navigate("/dashboard");
      }
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 409) {
        // Already queued or active for this lab - check status on the dashboard.
        navigate("/dashboard");
      } else {
        setError(err instanceof api.ApiError ? err.message : "Failed to access lab");
      }
    } finally {
      setBusyLabId(null);
    }
  }

  async function handleSchedule(e: FormEvent, labId: number) {
    e.preventDefault();
    setBusyLabId(labId);
    setError(null);
    try {
      await api.makeReservation(labId, reservationDate, reservationTime);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Failed to reserve");
    } finally {
      setBusyLabId(null);
    }
  }

  async function handleCreateLab(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createLab(newLabName, newLabDescription);
      setNewLabName("");
      setNewLabDescription("");
      await refresh();
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Failed to create lab");
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Labs</h1>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}

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
