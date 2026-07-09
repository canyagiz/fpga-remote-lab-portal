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

  async function handleJoinQueue(labId: number) {
    setBusyLabId(labId);
    setError(null);
    try {
      await api.joinQueue(labId);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Failed to join queue");
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
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Labs</h1>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}

      <ul className="mt-6 space-y-3">
        {labs.map((lab) => (
          <li key={lab.id}>
            <Card>
              <CardContent className="p-5">
                <h3 className="font-semibold">{lab.name}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{lab.description}</p>
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant={statusVariant[lab.status]}>{lab.status}</Badge>
                  {lab.queue_count > 0 && (
                    <span className="text-sm text-muted-foreground">{lab.queue_count} in queue</span>
                  )}
                </div>

                <div className="mt-4 flex gap-2">
                  <Button size="sm" disabled={busyLabId === lab.id} onClick={() => handleJoinQueue(lab.id)}>
                    Join queue now
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setSchedulingLabId(schedulingLabId === lab.id ? null : lab.id)}
                  >
                    Reserve for later
                  </Button>
                </div>

                {schedulingLabId === lab.id && (
                  <form
                    className="mt-4 flex flex-wrap items-end gap-3 border-t border-border pt-4"
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
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>

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
