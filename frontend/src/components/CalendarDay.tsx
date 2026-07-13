import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CalendarEntry } from "../api/types";

// A full local day, 00:00-24:00, drawn as a vertical scrollable strip in
// 5-minute resolution. 8px/min => 1h = 480px = one full viewport height, so
// the grid shows exactly one hour at a time. This isn't just a zoom
// preference: a short (e.g. 4-minute) session was only 16px tall at
// 4px/min, and a pin scheduled just 3-5 minutes out sat close enough to
// the "Now" line, and close enough to its own rounded/bordered pill
// edges, that it visually read as overlapping "now" even though the
// underlying timestamps (verified against the server) were exactly
// right - there was no timing bug, only too little vertical room to see
// the real gap.
const PX_PER_MIN = 8;
const DAY_MIN = 24 * 60;
const VIEWPORT_PX = 480;
const MAX_DAY_OFFSET = 6;

function startOfToday(): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

function minsSinceMidnight(d: Date): number {
  return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60;
}

function timeLabel(d: Date): string {
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

interface CalendarDayProps {
  labName: string;
  labImageUrl: string | null;
  entries: CalendarEntry[];
}

export default function CalendarDay({ labName, labImageUrl, entries }: CalendarDayProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [dayOffset, setDayOffset] = useState(0);
  // Re-render every 30s so the "Now" line and active pins stay live.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 30000);
    return () => clearInterval(id);
  }, []);

  const day0 = new Date(startOfToday().getTime() + dayOffset * DAY_MIN * 60000);
  const dayEnd = new Date(day0.getTime() + DAY_MIN * 60000);
  const now = new Date();
  const nowMins = minsSinceMidnight(now);
  const showNow = dayOffset === 0 && now >= day0 && now < dayEnd;

  // Center the viewport on "now" for today; default to mid-morning for
  // other days so the grid doesn't open scrolled to the middle of the night.
  useEffect(() => {
    if (!scrollRef.current) return;
    const target = showNow ? nowMins * PX_PER_MIN - VIEWPORT_PX / 2 : 8 * 60 * PX_PER_MIN;
    scrollRef.current.scrollTop = Math.max(target, 0);
    setExpanded(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dayOffset]);

  const dayEntries = entries
    .map((e) => ({ e, start: new Date(e.start_time), end: new Date(e.end_time) }))
    .filter(({ start }) => start >= day0 && start < dayEnd)
    .sort((a, b) => a.start.getTime() - b.start.getTime());

  const hourLines = Array.from({ length: 25 }, (_, h) => h);

  // 5-minute gridlines for every hour except the hour mark itself (already
  // drawn by hourLines above, with its own label) - :15/:30/:45 are drawn
  // heavier so the hour is still readable as a scroll of empty half-hours,
  // not a featureless gap.
  const minuteLines: { min: number; quarter: boolean }[] = [];
  for (let h = 0; h < 24; h++) {
    for (let m = 5; m < 60; m += 5) {
      minuteLines.push({ min: h * 60 + m, quarter: m === 15 || m === 30 || m === 45 });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-lg">
          <span className="flex items-center gap-2">
            {labImageUrl && (
              <img src={labImageUrl} alt="" className="h-6 w-6 rounded object-contain" />
            )}
            {labName}
          </span>
          <span className="flex items-center gap-1">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              disabled={dayOffset === 0}
              onClick={() => setDayOffset((d) => Math.max(d - 1, 0))}
              aria-label="Previous day"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="min-w-32 text-center text-sm font-normal text-muted-foreground">
              {day0.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
            </span>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              disabled={dayOffset === MAX_DAY_OFFSET}
              onClick={() => setDayOffset((d) => Math.min(d + 1, MAX_DAY_OFFSET))}
              aria-label="Next day"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="mb-2 text-xs text-muted-foreground">Tap a pin to see who booked it.</p>
        <div
          ref={scrollRef}
          className="relative overflow-y-auto rounded-md border border-border bg-card"
          style={{ height: VIEWPORT_PX }}
        >
          <div className="relative" style={{ height: DAY_MIN * PX_PER_MIN }}>
            {/* 5-minute gridlines - faint, except :15/:30/:45 which are
                heavier so an empty hour still reads as a ruled surface
                rather than a blank gap. */}
            {minuteLines.map(({ min, quarter }) => (
              <div
                key={min}
                className={
                  "absolute left-0 right-0 " +
                  (quarter ? "border-t-2 border-border/60" : "border-t border-border/25")
                }
                style={{ top: min * PX_PER_MIN }}
              />
            ))}

            {/* Hour gridlines + labels */}
            {hourLines.map((h) => (
              <div
                key={h}
                className="absolute left-0 right-0 border-t-2 border-border"
                style={{ top: h * 60 * PX_PER_MIN }}
              >
                <span className="absolute -top-2 left-1 bg-card px-1 text-[11px] tabular-nums text-muted-foreground">
                  {String(h % 24).padStart(2, "0")}:00
                </span>
              </div>
            ))}

            {/* Now line */}
            {showNow && (
              <div
                className="absolute left-0 right-0 z-20 flex items-center"
                style={{ top: nowMins * PX_PER_MIN }}
              >
                <span className="mr-1 rounded bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground">
                  Now
                </span>
                <span className="h-0.5 flex-1 bg-destructive" />
              </div>
            )}

            {/* Reservation pins - a single pill spanning exactly [start,
                end), flush at both ends. An earlier version centered a
                20px circle ON the start instant, which made a short (e.g.
                4-minute) session visually start ~5 minutes before its real
                start and blur into the end marker - the pill's edges, not
                an oversized circle's center, are what must land on the
                real timestamps. */}
            {dayEntries.map(({ e, start, end }, i) => {
              const top = minsSinceMidnight(start) * PX_PER_MIN;
              const barHeight = Math.max(minsSinceMidnight(end) * PX_PER_MIN - top, 8);
              const isActive = e.status === "active";
              const isOpen = expanded === i;
              const fill = isActive ? "bg-destructive" : "bg-warning";
              return (
                <div
                  key={i}
                  data-pin
                  title={`${e.username} (${timeLabel(start)} - ${timeLabel(end)})`}
                  className="absolute z-30"
                  style={{ top, height: barHeight }}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    setExpanded(isOpen ? null : i);
                  }}
                >
                  {/* The pill itself is the pin - its top/bottom edges are
                      the session's real start/end, not its center. `left`
                      here is relative to this container's own edge, not
                      padding-derived, so the 56px clearance for the HH:MM
                      labels is baked into the value directly. */}
                  <div
                    className={
                      "absolute left-14 h-full w-4 cursor-pointer rounded-full border-2 border-card shadow transition-transform hover:scale-x-125 " +
                      fill
                    }
                  >
                    {isActive && (
                      <span className="absolute inset-x-0 top-0 h-4 animate-ping rounded-full bg-destructive opacity-60" />
                    )}
                  </div>

                  {isOpen && (
                    <div
                      className={
                        "absolute left-[88px] top-0 origin-left animate-in fade-in-0 zoom-in-95 cursor-pointer rounded-lg px-3 py-1.5 shadow-md " +
                        (isActive
                          ? "bg-destructive text-destructive-foreground"
                          : "border border-warning bg-warning-muted text-warning-muted-foreground")
                      }
                    >
                      <div className="flex items-center gap-1.5 text-sm font-semibold">
                        {isActive && (
                          <span className="relative flex h-2 w-2">
                            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-75" />
                            <span className="relative inline-flex h-2 w-2 rounded-full bg-white" />
                          </span>
                        )}
                        {e.username}
                      </div>
                      <div className="text-xs opacity-90">
                        {timeLabel(start)} - {timeLabel(end)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
