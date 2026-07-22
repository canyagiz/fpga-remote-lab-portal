import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import * as api from "../api/client";
import { Board, Deployment, Device, GapReport, Shuttle } from "../api/types";
import { useToast } from "../context/ToastContext";

/** Manufacturer plus product, without saying the brand twice. */
function describeDevice(manufacturer: string | null, product: string | null): string {
  const maker = manufacturer?.trim() ?? "";
  const name = product?.trim() ?? "";
  if (!maker) return name || "Unknown device";
  if (!name) return maker;
  return name.toLowerCase().startsWith(maker.toLowerCase()) ? name : `${maker} ${name}`;
}

const FAMILY_LABELS: Record<string, string> = {
  cyclone_iv: "Cyclone IV",
  cyclone_v: "Cyclone V",
  cyclone_10: "Cyclone 10",
  zynq_7020: "Zynq-7020",
};

/** One row in the tree. `depth` drives the indent, and the connector
 *  lines are drawn from the row itself rather than computed positions,
 *  so the layout survives any amount of text wrapping. */
function Node({
  depth,
  last,
  children,
}: {
  depth: number;
  last?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="relative" style={{ paddingLeft: depth === 0 ? 0 : "1.75rem" }}>
      {depth > 0 && (
        <>
          {/* elbow into this row */}
          <span
            aria-hidden
            className="absolute left-[0.55rem] top-0 w-[1.2rem] border-b border-l border-border"
            style={{ height: "1.15rem", borderBottomLeftRadius: "0.4rem" }}
          />
          {/* the trunk continues past this row unless it is the last child */}
          {!last && (
            <span
              aria-hidden
              className="absolute bottom-0 left-[0.55rem] top-[1.15rem] border-l border-border"
            />
          )}
        </>
      )}
      {children}
    </div>
  );
}

function DeviceChip({
  device,
  role,
}: {
  device: Device;
  role: "programmer" | "capture";
}) {
  const signal =
    role === "capture"
      ? device.has_video_signal === true
        ? { variant: "success" as const, text: "signal" }
        : device.has_video_signal === false
          ? { variant: "destructive" as const, text: "no signal" }
          : { variant: "outline" as const, text: "signal unknown" }
      : null;

  return (
    <div className="my-1 flex flex-wrap items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm">
      <span className="font-medium">{describeDevice(device.manufacturer, device.product)}</span>
      <span className="font-mono text-xs text-muted-foreground">{device.usb_serial}</span>
      <span className="font-mono text-[10px] text-muted-foreground">port {device.sysfs_path}</span>
      <Badge variant="outline">{role}</Badge>
      {signal && <Badge variant={signal.variant}>{signal.text}</Badge>}
      {device.jtag_chain && device.jtag_chain.length > 0 && (
        <span
          className="font-mono text-[10px] text-muted-foreground"
          title={device.jtag_chain.map((c) => `${c.idcode} ${c.name ?? c.kind ?? ""}`).join("\n")}
        >
          jtag: {device.jtag_chain.map((c) => c.idcode).join(" · ")}
        </span>
      )}
    </div>
  );
}

export default function FleetGraphPage() {
  const { showError } = useToast();
  const [shuttles, setShuttles] = useState<Shuttle[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [boards, setBoards] = useState<Board[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [gaps, setGaps] = useState<GapReport[]>([]);

  async function refresh() {
    try {
      const [s, d, b, dep, g] = await Promise.all([
        api.getShuttles(),
        api.getFleetDevices(),
        api.getBoards(),
        api.getDeployments(),
        api.getGaps(),
      ]);
      setShuttles(s);
      setDevices(d);
      setBoards(b);
      setDeployments(dep);
      setGaps(g);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load topology");
    }
  }

  useEffect(() => {
    refresh();
    // Same cadence the agents report on, so a cable plugged in downstairs
    // shows up here without anyone reloading the page.
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Fleet topology</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            What is physically connected to what, right now.
          </p>
        </div>
        <Link
          to="/admin/fleet"
          className="text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          ← Back to fleet
        </Link>
      </div>

      {shuttles.length === 0 && (
        <p className="mt-10 text-center text-sm text-muted-foreground">
          No shuttles enrolled yet.
        </p>
      )}

      <div className="mt-8 space-y-10">
        {shuttles.map((shuttle) => {
          const shuttleDevices = devices.filter((d) => d.shuttle_id === shuttle.id);
          const shuttleSerials = new Set(
            shuttleDevices.map((d) => d.usb_serial).filter(Boolean) as string[],
          );
          // A board belongs to whichever shuttle currently reports its
          // programmer - the same rule the backend resolves by, so this
          // view cannot drift from what the gap report decided.
          const shuttleBoards = boards.filter((b) => shuttleSerials.has(b.programmer_serial));
          const claimed = new Set<string>();
          shuttleBoards.forEach((b) => {
            claimed.add(b.programmer_serial);
            if (b.video_capture_serial) claimed.add(b.video_capture_serial);
          });
          const loose = shuttleDevices.filter(
            (d) => !d.usb_serial || !claimed.has(d.usb_serial),
          );

          return (
            <section key={shuttle.id}>
              {/* Shuttle */}
              <Node depth={0}>
                <div className="flex flex-wrap items-center gap-2 rounded-lg border-2 bg-card px-4 py-2.5">
                  <span className="text-base font-semibold">{shuttle.name}</span>
                  {shuttle.status === "online" ? (
                    <Badge variant="success">online</Badge>
                  ) : shuttle.status === "offline" ? (
                    <Badge variant="destructive">offline</Badge>
                  ) : (
                    <Badge variant="outline">awaiting first report</Badge>
                  )}
                  <span className="font-mono text-xs text-muted-foreground">
                    {shuttle.address ?? "no address set"}
                  </span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {shuttleBoards.length} board{shuttleBoards.length === 1 ? "" : "s"} ·{" "}
                    {shuttleDevices.length} device{shuttleDevices.length === 1 ? "" : "s"}
                  </span>
                </div>
              </Node>

              <div className="mt-1">
                {shuttleBoards.map((board, boardIndex) => {
                  const programmer = shuttleDevices.find(
                    (d) => d.usb_serial === board.programmer_serial,
                  );
                  const capture = board.video_capture_serial
                    ? shuttleDevices.find((d) => d.usb_serial === board.video_capture_serial)
                    : undefined;
                  const deployment = deployments.find((d) => d.board_id === board.id);
                  // Readiness of whichever template covers this board's
                  // family on this shuttle - the same answer the fleet
                  // page shows, surfaced here so the topology explains
                  // itself rather than needing a second screen.
                  const gap = gaps.find(
                    (g) =>
                      g.shuttle_id === shuttle.id &&
                      g.results.some((r) => r.type === "fpga" && r.message.includes(board.label)),
                  );
                  const isLastBoard = boardIndex === shuttleBoards.length - 1 && loose.length === 0;

                  const childCount = 1 + (capture || board.video_capture_serial ? 1 : 0) + 1;

                  return (
                    <Node key={board.id} depth={1} last={isLastBoard}>
                      <div className="my-1 flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3.5 py-2">
                        <span className="font-semibold">{board.label}</span>
                        <Badge variant="secondary">
                          {FAMILY_LABELS[board.family] ?? board.family}
                        </Badge>
                        {deployment ? (
                          deployment.available ? (
                            <Badge variant="success">serving {deployment.lab_name}</Badge>
                          ) : (
                            <Badge variant="destructive">{deployment.lab_name} withdrawn</Badge>
                          )
                        ) : (
                          <Badge variant="outline">not bound to a lab</Badge>
                        )}
                        {gap &&
                          (gap.deployable ? (
                            <Badge variant="success">ready</Badge>
                          ) : (
                            <Badge variant="warning">{gap.missing_count} unmet</Badge>
                          ))}
                      </div>

                      <div>
                        {/* Programmer - the board's identity link. */}
                        <Node depth={1} last={childCount === 1}>
                          {programmer ? (
                            <DeviceChip device={programmer} role="programmer" />
                          ) : (
                            <div className="my-1 rounded-md border border-dashed px-3 py-1.5 text-sm text-muted-foreground">
                              programmer {board.programmer_serial} not reported
                            </div>
                          )}
                        </Node>

                        {/* Capture card, when one is recorded for this board. */}
                        {(capture || board.video_capture_serial) && (
                          <Node depth={1}>
                            {capture ? (
                              <DeviceChip device={capture} role="capture" />
                            ) : (
                              <div className="my-1 rounded-md border border-dashed px-3 py-1.5 text-sm text-destructive">
                                capture card {board.video_capture_serial} not attached
                              </div>
                            )}
                          </Node>
                        )}

                        {/* The GPIO controller is reached over the network,
                            not USB, so it never appears in a device scan -
                            it exists here only because a human recorded it. */}
                        <Node depth={1} last>
                          {board.gpio_endpoint ? (
                            <div className="my-1 flex flex-wrap items-center gap-2 rounded-md border border-dashed bg-card px-3 py-1.5 text-sm">
                              <span className="font-medium">GPIO controller</span>
                              <span className="font-mono text-xs text-muted-foreground">
                                {board.gpio_endpoint}
                              </span>
                              <Badge variant="outline">network · not probed</Badge>
                            </div>
                          ) : (
                            <div className="my-1 rounded-md border border-dashed px-3 py-1.5 text-sm text-muted-foreground">
                              no GPIO controller recorded
                            </div>
                          )}
                        </Node>
                      </div>
                    </Node>
                  );
                })}

                {/* Attached but claimed by no board. */}
                {loose.length > 0 && (
                  <Node depth={1} last>
                    <div className="my-1 rounded-lg border border-dashed px-3.5 py-2">
                      <span className="text-sm font-medium text-muted-foreground">
                        Not claimed by any board
                      </span>
                      <div className="mt-1">
                        {loose.map((d, i) => (
                          <Node key={d.id} depth={1} last={i === loose.length - 1}>
                            <div className="my-1 flex flex-wrap items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm">
                              <span>{describeDevice(d.manufacturer, d.product)}</span>
                              <span className="font-mono text-xs text-muted-foreground">
                                {d.usb_serial ?? d.sysfs_path}
                              </span>
                              <Badge variant="outline">{d.kind.replace("_", " ")}</Badge>
                            </div>
                          </Node>
                        ))}
                      </div>
                    </div>
                  </Node>
                )}

                {shuttleBoards.length === 0 && loose.length === 0 && (
                  <Node depth={1} last>
                    <p className="my-1 text-sm text-muted-foreground">
                      Nothing reported. This shuttle is enrolled but its agent has not run.
                    </p>
                  </Node>
                )}
              </div>
            </section>
          );
        })}
      </div>

      <p className="mt-10 text-xs text-muted-foreground">
        Solid boxes are hardware an agent actually sees over USB. Dashed boxes are things recorded
        by a person or reached over the network — they are not discovered, so their absence cannot
        be detected here.
      </p>
    </div>
  );
}
