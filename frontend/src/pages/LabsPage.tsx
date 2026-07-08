import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api/client";
import { Lab } from "../api/types";
import { useAuth } from "../context/AuthContext";

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
    <div className="page">
      <h1>Labs</h1>
      {error && <p className="error">{error}</p>}

      <ul className="lab-list">
        {labs.map((lab) => (
          <li key={lab.id} className="lab-card">
            <div>
              <h3>{lab.name}</h3>
              <p>{lab.description}</p>
              <span className={`badge badge-${lab.status}`}>{lab.status}</span>
              {lab.queue_count > 0 && <span className="hint"> - {lab.queue_count} in queue</span>}
            </div>

            <div className="actions">
              <button disabled={busyLabId === lab.id} onClick={() => handleJoinQueue(lab.id)}>
                Join queue now
              </button>
              <button
                className="secondary"
                onClick={() => setSchedulingLabId(schedulingLabId === lab.id ? null : lab.id)}
              >
                Reserve for later
              </button>
            </div>

            {schedulingLabId === lab.id && (
              <form className="inline-form" onSubmit={(e) => handleSchedule(e, lab.id)}>
                <label htmlFor={`date-${lab.id}`}>Date</label>
                <input
                  id={`date-${lab.id}`}
                  type="date"
                  value={reservationDate}
                  onChange={(e) => setReservationDate(e.target.value)}
                  required
                />
                <label htmlFor={`time-${lab.id}`}>Time</label>
                <input
                  id={`time-${lab.id}`}
                  type="time"
                  value={reservationTime}
                  onChange={(e) => setReservationTime(e.target.value)}
                  required
                />
                <button type="submit" disabled={busyLabId === lab.id}>
                  Confirm reservation
                </button>
              </form>
            )}
          </li>
        ))}
      </ul>

      {user?.role === "admin" && (
        <div className="admin-panel">
          <h2>Add a lab (admin)</h2>
          <form onSubmit={handleCreateLab}>
            <label htmlFor="newLabName">Name</label>
            <input id="newLabName" value={newLabName} onChange={(e) => setNewLabName(e.target.value)} required />
            <label htmlFor="newLabDescription">Description</label>
            <textarea
              id="newLabDescription"
              value={newLabDescription}
              onChange={(e) => setNewLabDescription(e.target.value)}
              required
            />
            <button type="submit">Create lab</button>
          </form>
        </div>
      )}
    </div>
  );
}
