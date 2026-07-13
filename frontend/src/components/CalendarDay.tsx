import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CalendarEntry } from "../api/types";

// A full local day, 00:00-24:00, drawn as a vertical scrollable strip in
// 5-minute resolution. 2px/min => 5 min = 10px, 1h = 120px, 24h = 2880px.
const PX_PER_MIN = 2;
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
  onReserveSlot: (start: Date) => void;
}

export default function CalendarDay({ labName, labImageUrl, entries, onReserveSlot }: CalendarDayProps) {
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

  function handleGridClick(e: React.MouseEvent<HTMLDivElement>) {
    // Ignore clicks that bubbled up from a pin.
    if ((e.target as HTMLElement).closest("[data-pin]")) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const y = e.clientY - rect.top + e.currentTarget.scrollTop;
    const mins = Math.floor(y / PX_PER_MIN / 5) * 5;
    onReserveSlot(new Date(day0.getTime() + mins * 60000));
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
        <p className="mb-2 text-xs text-muted-foreground">
          Tap an empty slot to reserve it &middot; tap a pin to see who booked it.
        </p>
        <div
          ref={scrollRef}
          className="relative overflow-y-auto rounded-md border border-border bg-card"
          style={{ height: VIEWPORT_PX }}
        >
          <div
            className="relative cursor-pointer"
            style={{ height: DAY_MIN * PX_PER_MIN }}
            onClick={handleGridClick}
          >
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

            {/* Reservation pins - a duration bar from start to end (the
                real lab session length), capped by a circle at each end,
                so the timeline shows how long the board is actually
                occupied instead of a single dot with no sense of extent. */}
            {dayEntries.map(({ e, start, end }, i) => {
              const top = minsSinceMidnight(start) * PX_PER_MIN;
              const barHeight = Math.max(minsSinceMidnight(end) * PX_PER_MIN - top, 6);
              const isActive = e.status === "active";
              const isOpen = expanded === i;
              const dot = isActive ? "bg-destructive" : "bg-warning";
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
                  {/* Duration bar - offsets are absolute (not padding-
                      derived): a positioned descendant's `left` is relative
                      to this container's own edge, not indented by any
                      padding, so the 56px clearance for the HH:MM labels is
                      baked into each of these three elements directly. */}
                  <span
                    className={"absolute left-16 top-0 w-1 rounded-full " + dot + " opacity-50"}
                    style={{ height: barHeight }}
                  />
                  {/* Start marker */}
                  <span
                    className={"absolute left-14 block h-5 w-5 rounded-full border-2 border-card shadow transition-transform hover:scale-125 " + dot}
                    style={{ top: -10 }}
                  >
                    {isActive && (
                      <span className="absolute inline-flex h-5 w-5 animate-ping rounded-full bg-destructive opacity-60" />
                    )}
                  </span>
                  {/* End marker */}
                  <span
                    className={"absolute block h-3 w-3 rounded-full border-2 border-card shadow " + dot}
                    style={{ top: barHeight - 6, left: 60 }}
                  />

                  {isOpen && (
                    <div
                      className={
                        "absolute left-14 top-0 origin-left animate-in fade-in-0 zoom-in-95 cursor-pointer rounded-lg px-3 py-1.5 shadow-md " +
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
