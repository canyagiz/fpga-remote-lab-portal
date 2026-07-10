import { useEffect, useState } from "react";
import CalendarDay from "../components/CalendarDay";
import * as api from "../api/client";
import { CalendarEntry, Lab } from "../api/types";
import { useToast } from "../context/ToastContext";

const pad = (n: number) => String(n).padStart(2, "0");

export default function CalendarPage() {
  const { showError, showSuccess } = useToast();
  const [entries, setEntries] = useState<CalendarEntry[]>([]);
  const [labs, setLabs] = useState<Lab[]>([]);

  async function refresh() {
    try {
      const [cal, allLabs] = await Promise.all([api.getCalendar(), api.getLabs()]);
      setEntries(cal);
      setLabs(allLabs);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load calendar");
    }
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 15000);
    return () => clearInterval(interval);
  }, []);

  async function reserveSlot(labId: number, labName: string, start: Date) {
    const label = start.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    if (!window.confirm(`Reserve ${labName} at ${label}?`)) return;
    try {
      // The backend works in UTC; convert the picked local time.
      const date = `${start.getUTCFullYear()}-${pad(start.getUTCMonth() + 1)}-${pad(start.getUTCDate())}`;
      const time = `${pad(start.getUTCHours())}:${pad(start.getUTCMinutes())}`;
      await api.makeReservation(labId, date, time);
      showSuccess(`Reserved ${labName} at ${label}.`);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to reserve");
    }
  }

  // Only boards you can actually book/use get a calendar; each shows its
  // full day even with zero reservations.
  const bookableLabs = labs.filter((l) => l.is_public);

  return (
    <div className="mx-auto max-w-xl px-6 py-10">
      <h1 className="text-2xl font-bold tracking-tight">Calendar</h1>
      <p className="mt-1 text-sm text-muted-foreground">Who has each board, and when - by username only.</p>

      {bookableLabs.length === 0 ? (
        <p className="mt-8 text-sm text-muted-foreground">No bookable boards available yet.</p>
      ) : (
        <div className="mt-8 space-y-6">
          {bookableLabs.map((lab) => (
            <CalendarDay
              key={lab.id}
              labName={lab.name}
              labImageUrl={lab.image_url}
              entries={entries.filter((e) => e.lab_id === lab.id)}
              onReserveSlot={(start) => reserveSlot(lab.id, lab.name, start)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
