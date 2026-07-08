import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import * as api from "../api/client";
import { Reservation } from "../api/types";
import { useAuth } from "../context/AuthContext";

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
    <div className="page">
      <h1>Welcome, {user?.username}</h1>
      <p>
        <Link to="/labs">Browse labs</Link>
      </p>

      <h2>My reservations</h2>
      {error && <p className="error">{error}</p>}
      {reservations.length === 0 ? (
        <p className="hint">No open reservations.</p>
      ) : (
        <ul className="reservation-list">
          {reservations.map((r) => (
            <li key={r.id} className="reservation-item">
              <div>
                <strong>{r.lab_name}</strong>
                <span className={`badge badge-${r.status}`}>{r.status}</span>
                {r.status === "pending" && r.queue_position > 0 && (
                  <span className="hint"> - queue position {r.queue_position}</span>
                )}
                {r.reservation_date && r.reservation_time && (
                  <span className="hint">
                    {" "}
                    - scheduled for {r.reservation_date} {r.reservation_time}
                  </span>
                )}
              </div>
              <div className="actions">
                {r.status === "pending" && r.queue_position === 0 && (
                  <button disabled={busyId === r.id} onClick={() => runAction(r.id, api.startLabUsage)}>
                    Start
                  </button>
                )}
                {r.status === "active" && (
                  <button disabled={busyId === r.id} onClick={() => runAction(r.id, api.completeLabUsage)}>
                    Finish
                  </button>
                )}
                {(r.status === "pending" || r.status === "active") && (
                  <button
                    className="secondary"
                    disabled={busyId === r.id}
                    onClick={() => runAction(r.id, api.cancelReservation)}
                  >
                    Cancel
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
