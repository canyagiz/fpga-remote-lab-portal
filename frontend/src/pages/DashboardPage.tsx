import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import * as api from "../api/client";
import { Reservation, ReservationStatus } from "../api/types";
import { useAuth } from "../context/AuthContext";

const statusVariant: Record<ReservationStatus, "success" | "warning" | "secondary"> = {
  active: "success",
  pending: "warning",
  cancelled: "secondary",
  expired: "secondary",
  completed: "secondary",
};

export default function DashboardPage() {
  const { user } = useAuth();
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function refresh() {
    try {
      setReservations(await api.getMyReservations());
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Failed to load reservations");
    }
  }

  useEffect(() => {
    refresh();
    // Queue positions change as other users finish - poll like the old
    // portal did rather than requiring a manual refresh.
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, []);

  async function runAction(id: number, action: (id: number) => Promise<Reservation>) {
    setBusyId(id);
    setError(null);
    try {
      await action(id);
      await refresh();
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Welcome, {user?.username}</h1>
      <Link to="/labs" className="mt-1 inline-block text-sm font-medium text-primary hover:underline">
        Browse labs
      </Link>

      <h2 className="mt-8 mb-3 text-lg font-semibold">My reservations</h2>
      {error && <p className="mb-3 text-sm text-destructive">{error}</p>}
      {reservations.length === 0 ? (
        <p className="text-sm text-muted-foreground">No open reservations.</p>
      ) : (
        <ul className="space-y-3">
          {reservations.map((r) => (
            <li key={r.id}>
              <Card>
                <CardContent className="flex items-center justify-between p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="font-semibold">{r.lab_name}</strong>
                    <Badge variant={statusVariant[r.status]}>{r.status}</Badge>
                    {r.status === "pending" && r.queue_position > 0 && (
                      <span className="text-sm text-muted-foreground">
                        queue position {r.queue_position}
                      </span>
                    )}
                    {r.reservation_date && r.reservation_time && (
                      <span className="text-sm text-muted-foreground">
                        scheduled for {r.reservation_date} {r.reservation_time}
                      </span>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {r.status === "pending" && r.queue_position === 0 && (
                      <Button size="sm" disabled={busyId === r.id} onClick={() => runAction(r.id, api.startLabUsage)}>
                        Start
                      </Button>
                    )}
                    {r.status === "active" && (
                      <Button
                        size="sm"
                        disabled={busyId === r.id}
                        onClick={() => runAction(r.id, api.completeLabUsage)}
                      >
                        Finish
                      </Button>
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
          ))}
        </ul>
      )}
    </div>
  );
}
