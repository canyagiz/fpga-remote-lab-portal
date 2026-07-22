import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import * as api from "../api/client";
import {
  Board,
  Deployment,
  Device,
  GapReport,
  Lab,
  LabTemplate,
  Shuttle,
  UnclaimedDevice,
} from "../api/types";
import { useToast } from "../context/ToastContext";

const FAMILIES = [
  { value: "cyclone_iv", label: "Cyclone IV" },
  { value: "cyclone_v", label: "Cyclone V" },
  { value: "cyclone_10", label: "Cyclone 10" },
  { value: "zynq_7020", label: "Zynq-7020 (Arty Z7)" },
];

function familyLabel(value: string): string {
  return FAMILIES.find((f) => f.value === value)?.label ?? value;
}

/** Manufacturer plus product, without saying the brand twice.
 *  Some devices already carry the vendor in their product string -
 *  Digilent's programmer reports manufacturer "Digilent" and product
 *  "Digilent Adept USB Device" - so joining them blindly reads as
 *  "Digilent Digilent Adept USB Device". */
function describeDevice(manufacturer: string | null, product: string | null): string {
  const maker = manufacturer?.trim() ?? "";
  const name = product?.trim() ?? "";
  if (!maker) return name || "Unknown device";
  if (!name) return maker;
  return name.toLowerCase().startsWith(maker.toLowerCase()) ? name : `${maker} ${name}`;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Shuttle liveness. "never_reported" is its own state, not an error -
 *  an enrolled shuttle whose agent has not been installed yet is a
 *  normal step in bringing one up, not a fault. */
function StatusBadge({ status }: { status: string }) {
  if (status === "online") return <Badge variant="success">online</Badge>;
  if (status === "offline") return <Badge variant="destructive">offline</Badge>;
  return <Badge variant="outline">awaiting first report</Badge>;
}

/** The three requirement states. Kept visually distinct because they
 *  mean different things to whoever has to act: missing is "find one",
 *  degraded is "something here is broken". */
function RequirementBadge({ status }: { status: string }) {
  if (status === "satisfied") return <Badge variant="success">ok</Badge>;
  if (status === "degraded") return <Badge variant="warning">degraded</Badge>;
  return <Badge variant="destructive">missing</Badge>;
}

function EmptyRow({ colSpan, children }: { colSpan: number; children: React.ReactNode }) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="py-6 text-center text-sm text-muted-foreground">
        {children}
      </TableCell>
    </TableRow>
  );
}

export default function FleetPage() {
  const { showError, showSuccess } = useToast();

  const [shuttles, setShuttles] = useState<Shuttle[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [unclaimed, setUnclaimed] = useState<UnclaimedDevice[]>([]);
  const [boards, setBoards] = useState<Board[]>([]);
  const [templates, setTemplates] = useState<LabTemplate[]>([]);
  const [gaps, setGaps] = useState<GapReport[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [unused, setUnused] = useState<Device[]>([]);
  const [labs, setLabs] = useState<Lab[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  // The enrolment token is returned once and never again, so it is held
  // in a modal until the admin dismisses it rather than shown in a toast
  // that could scroll away unread.
  const [issuedToken, setIssuedToken] = useState<{ name: string; token: string } | null>(null);
  const [claiming, setClaiming] = useState<UnclaimedDevice | null>(null);
  const [newShuttleName, setNewShuttleName] = useState("");

  async function refresh() {
    try {
      const [s, d, u, b, t, g, dep, un, l] = await Promise.all([
        api.getShuttles(),
        api.getFleetDevices(),
        api.getUnclaimedDevices(),
        api.getBoards(),
        api.getTemplates(),
        api.getGaps(),
        api.getDeployments(),
        api.getUnusedDevices(),
        api.getLabs(),
      ]);
      setShuttles(s);
      setDevices(d);
      setUnclaimed(u);
      setBoards(b);
      setTemplates(t);
      setGaps(g);
      setDeployments(dep);
      setUnused(un);
      setLabs(l);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load fleet data");
    }
  }

  useEffect(() => {
    refresh();
    // Agents report every 30s, so the page follows at the same cadence -
    // without this an admin watching for a board they just plugged in
    // would sit on a stale screen and reasonably conclude nothing worked.
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, []);

  async function handleEnrol(e: FormEvent) {
    e.preventDefault();
    const name = newShuttleName.trim();
    if (!name) return;
    setBusy("enrol");
    try {
      const result = await api.enrolShuttle(name);
      setIssuedToken({ name: result.shuttle.name, token: result.token });
      setNewShuttleName("");
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to enrol shuttle");
    } finally {
      setBusy(null);
    }
  }

  async function handleRotate(shuttle: Shuttle) {
    if (
      !confirm(
        `Issue a new token for ${shuttle.name}? Its agent stops reporting until you reconfigure it with the new one.`,
      )
    )
      return;
    setBusy(`rotate-${shuttle.id}`);
    try {
      const result = await api.rotateShuttleToken(shuttle.id);
      setIssuedToken({ name: shuttle.name, token: result.token });
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to rotate token");
    } finally {
      setBusy(null);
    }
  }

  async function handleAddress(shuttle: Shuttle) {
    const address = prompt(
      `Address where ${shuttle.name}'s lab containers are reached (e.g. 10.30.70.23).\n\n` +
        `This is what student browsers are sent to, which is why it is set here rather than taken from the agent's own report.`,
      "",
    );
    if (!address?.trim()) return;
    setBusy(`addr-${shuttle.id}`);
    try {
      await api.setShuttleAddress(shuttle.id, address.trim());
      showSuccess(`${shuttle.name} address set`);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to set address");
    } finally {
      setBusy(null);
    }
  }

  async function handleRemoveShuttle(shuttle: Shuttle) {
    if (!confirm(`Remove ${shuttle.name} from the fleet? Its recorded devices go with it.`)) return;
    setBusy(`del-${shuttle.id}`);
    try {
      await api.deleteShuttle(shuttle.id);
      showSuccess(`${shuttle.name} removed`);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to remove shuttle");
    } finally {
      setBusy(null);
    }
  }

  async function handleSetCapture(board: Board) {
    const options = captureDevices
      .map((d, i) => `${i + 1}. ${d.usb_serial} (${describeDevice(d.manufacturer, d.product)})`)
      .join("\n");
    const answer = prompt(
      `Which capture card watches ${board.label}?\n\n${options}\n\n` +
        `Enter the number, or 0 for none.`,
      "1",
    );
    if (answer === null) return;
    const index = Number(answer);
    if (Number.isNaN(index) || index < 0 || index > captureDevices.length) return;

    setBusy(`board-${board.id}`);
    try {
      await api.updateBoard(board.id, {
        // Empty string clears it; a serial sets it.
        video_capture_serial: index === 0 ? "" : (captureDevices[index - 1].usb_serial ?? ""),
      });
      showSuccess(`${board.label} updated`);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to update board");
    } finally {
      setBusy(null);
    }
  }

  async function handleDeleteBoard(board: Board) {
    if (!confirm(`Deregister "${board.label}"? The hardware stays; only its registration is removed.`))
      return;
    setBusy(`board-${board.id}`);
    try {
      await api.deleteBoard(board.id);
      showSuccess(`${board.label} deregistered`);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to deregister board");
    } finally {
      setBusy(null);
    }
  }

  async function handleToggleDeployment(deployment: Deployment) {
    setBusy(`dep-${deployment.id}`);
    try {
      await api.setDeploymentEnabled(deployment.id, !deployment.is_enabled);
      showSuccess(
        deployment.is_enabled
          ? `${deployment.lab_name} taken out of service`
          : `${deployment.lab_name} back in service`,
      );
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to update deployment");
    } finally {
      setBusy(null);
    }
  }

  async function handleUnbind(deployment: Deployment) {
    if (
      !confirm(
        `Unbind ${deployment.lab_name} from ${deployment.board_label}?\n\n` +
          `The lab reverts to its static address and stops being governed by the inventory.`,
      )
    )
      return;
    setBusy(`dep-${deployment.id}`);
    try {
      const result = await api.deleteDeployment(deployment.id);
      showSuccess(result.message);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to unbind");
    } finally {
      setBusy(null);
    }
  }

  const captureDevices = devices.filter((d) => d.kind === "video_capture");
  const onlineCount = shuttles.filter((s) => s.status === "online").length;
  const blockedGaps = gaps.filter((g) => !g.deployable);

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">Fleet</h1>
        <Link
          to="/admin/fleet/graph"
          className="text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          Topology view →
        </Link>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        {shuttles.length} shuttle{shuttles.length === 1 ? "" : "s"} ({onlineCount} online) ·{" "}
        {devices.length} device{devices.length === 1 ? "" : "s"} attached · {boards.length} registered
        board{boards.length === 1 ? "" : "s"}
      </p>

      {/* New hardware waiting for a human. Deliberately first on the page:
          it is the only section that represents someone standing at a
          machine waiting for a response. */}
      {unclaimed.length > 0 && (
        <Card className="mt-6 border-warning-muted-foreground/40">
          <CardHeader>
            <CardTitle>
              New hardware detected
              <Badge variant="warning" className="ml-2">
                {unclaimed.length}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">
              A programmer is attached that no board claims yet. An IDCODE identifies the chip, not
              the board it sits on — so which board this is has to be recorded by a person, once.
            </p>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Serial</TableHead>
                    <TableHead>Device</TableHead>
                    <TableHead>Shuttle</TableHead>
                    <TableHead>JTAG</TableHead>
                    <TableHead>Seen</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {unclaimed.map((d) => (
                    <TableRow key={d.device_id}>
                      <TableCell className="font-mono text-xs">{d.usb_serial}</TableCell>
                      <TableCell>
                        {describeDevice(d.manufacturer, d.product)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">{d.shuttle_name}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {d.jtag_chain?.length
                          ? d.jtag_chain.map((c) => c.idcode).join(", ")
                          : "not probed"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatWhen(d.first_seen_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" onClick={() => setClaiming(d)}>
                          Register as board
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Shuttles */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Shuttles</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Address</TableHead>
                  <TableHead>Devices</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Last report</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {shuttles.length === 0 ? (
                  <EmptyRow colSpan={7}>
                    No shuttles yet. Enrol one below, then install the agent on it.
                  </EmptyRow>
                ) : (
                  shuttles.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell className="font-medium">
                        {s.name}
                        {s.role === "master" && (
                          <Badge variant="outline" className="ml-2">
                            master
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={s.status} />
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {/* The admin-set address, not the agent's
                            self-reported hostname - this column drives
                            where students are sent, so it has to show
                            the value that actually does that. Hostname
                            sits underneath as a diagnostic. */}
                        {s.address ? (
                          s.address
                        ) : (
                          <span className="text-warning-muted-foreground">not set</span>
                        )}
                        {s.hostname && (
                          <span className="block text-[10px] text-muted-foreground">
                            {s.hostname}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>{s.device_count}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {s.agent_version ?? "—"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatWhen(s.last_report_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={busy === `addr-${s.id}`}
                            onClick={() => handleAddress(s)}
                          >
                            Set address
                          </Button>
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={busy === `rotate-${s.id}`}
                            onClick={() => handleRotate(s)}
                          >
                            New token
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={busy === `del-${s.id}`}
                            onClick={() => handleRemoveShuttle(s)}
                          >
                            Remove
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          <form onSubmit={handleEnrol} className="mt-4 flex flex-wrap items-end gap-2">
            <div className="grow">
              <Label htmlFor="shuttle-name">Enrol a shuttle</Label>
              <Input
                id="shuttle-name"
                value={newShuttleName}
                onChange={(e) => setNewShuttleName(e.target.value)}
                placeholder="pc-3vrl07"
              />
            </div>
            <Button type="submit" disabled={busy === "enrol" || !newShuttleName.trim()}>
              Enrol
            </Button>
          </form>
          <p className="mt-2 text-xs text-muted-foreground">
            Enrolling issues an agent token, shown once. A machine cannot add itself to the fleet.
          </p>
        </CardContent>
      </Card>

      {/* What each lab still needs */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>
            Lab readiness
            {blockedGaps.length > 0 && (
              <Badge variant="destructive" className="ml-2">
                {blockedGaps.length} blocked
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {gaps.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              No lab templates defined yet — a template says what a lab requires, and this is where
              the answer to "what is missing" appears.
            </p>
          ) : (
            <div className="space-y-4">
              {gaps.map((g) => (
                <div key={`${g.template_id}-${g.shuttle_id}`} className="rounded-lg border p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="font-medium">
                      {g.template_name}
                      <span className="text-muted-foreground"> on {g.shuttle_name}</span>
                    </div>
                    {g.deployable ? (
                      <Badge variant="success">deployable</Badge>
                    ) : (
                      <Badge variant="destructive">
                        {g.missing_count} unmet requirement{g.missing_count === 1 ? "" : "s"}
                      </Badge>
                    )}
                  </div>
                  <ul className="mt-3 space-y-1.5">
                    {g.results.map((r, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                        <RequirementBadge status={r.status} />
                        <span className="font-mono text-xs text-muted-foreground">{r.type}</span>
                        <span
                          className={
                            r.status === "satisfied" ? "text-muted-foreground" : "text-foreground"
                          }
                        >
                          {r.message}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Everything the agents can see, board or not. Without this the
          capture cards and any other supporting hardware are recorded but
          invisible - they are not boards, so the Boards table has no row
          for them, and they are not programmers, so the claim queue never
          lists them. */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Attached hardware</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Serial</TableHead>
                  <TableHead>Device</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Port</TableHead>
                  <TableHead>Used by</TableHead>
                  <TableHead>Health</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {devices.length === 0 ? (
                  <EmptyRow colSpan={6}>
                    Nothing reported yet. An enrolled shuttle only appears here once its
                    agent is installed and running.
                  </EmptyRow>
                ) : (
                  devices.map((d) => {
                    const board = boards.find(
                      (b) =>
                        b.programmer_serial === d.usb_serial ||
                        b.video_capture_serial === d.usb_serial,
                    );
                    return (
                      <TableRow key={d.id}>
                        <TableCell className="font-mono text-xs">
                          {d.usb_serial ?? <span className="text-muted-foreground">none</span>}
                        </TableCell>
                        <TableCell>{describeDevice(d.manufacturer, d.product)}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{d.kind.replace("_", " ")}</Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-muted-foreground">
                          {d.sysfs_path}
                        </TableCell>
                        <TableCell>
                          {board ? (
                            board.label
                          ) : (
                            <span className="text-muted-foreground">not claimed</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {/* Only capture cards report a signal. For anything
                              else this is genuinely not applicable, which is
                              different from unknown. */}
                          {d.kind !== "video_capture" ? (
                            <span className="text-muted-foreground">—</span>
                          ) : d.has_video_signal === true ? (
                            <Badge variant="success">signal</Badge>
                          ) : d.has_video_signal === false ? (
                            <Badge variant="destructive">no signal</Badge>
                          ) : (
                            <Badge variant="outline">unknown</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Registered boards */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Boards</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Label</TableHead>
                  <TableHead>Family</TableHead>
                  <TableHead>Programmer serial</TableHead>
                  <TableHead>Currently on</TableHead>
                  <TableHead>Capture</TableHead>
                  <TableHead>GPIO</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {boards.length === 0 ? (
                  <EmptyRow colSpan={7}>
                    No boards registered. They appear here once you claim a detected programmer.
                  </EmptyRow>
                ) : (
                  boards.map((b) => (
                    <TableRow key={b.id}>
                      <TableCell className="font-medium">{b.label}</TableCell>
                      <TableCell>{familyLabel(b.family)}</TableCell>
                      <TableCell className="font-mono text-xs">{b.programmer_serial}</TableCell>
                      <TableCell>
                        {b.shuttle_name ? (
                          b.shuttle_name
                        ) : (
                          <span className="text-muted-foreground">not attached</span>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {/* Flagged rather than left blank: a board with no
                            capture card recorded cannot have its video
                            verified, which blocks any lab that needs one. */}
                        {b.video_capture_serial ?? (
                          <span className="text-warning-muted-foreground">not set</span>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {b.gpio_endpoint ?? "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={busy === `board-${b.id}` || captureDevices.length === 0}
                            onClick={() => handleSetCapture(b)}
                          >
                            Set capture
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={busy === `board-${b.id}`}
                            onClick={() => handleDeleteBoard(b)}
                          >
                            Deregister
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Deployments */}
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Deployments</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-sm text-muted-foreground">
            A deployment binds a catalogue entry to a real board. Until a lab has one it keeps its
            static address and is listed exactly as before — and unbinding returns it to that state.
          </p>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Lab</TableHead>
                  <TableHead>Board</TableHead>
                  <TableHead>Resolved address</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {deployments.length === 0 ? (
                  <EmptyRow colSpan={5}>
                    No labs are bound to a board yet, so every lab still uses its static address.
                  </EmptyRow>
                ) : (
                  deployments.map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="font-medium">{d.lab_name}</TableCell>
                      <TableCell>
                        {d.board_label}
                        <span className="text-muted-foreground"> :{d.port}</span>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {d.backend_url ?? <span className="text-muted-foreground">unresolved</span>}
                      </TableCell>
                      <TableCell>
                        {d.available ? (
                          <Badge variant="success">serving</Badge>
                        ) : (
                          <div className="flex flex-col gap-1">
                            <Badge variant="destructive" className="w-fit">
                              withdrawn
                            </Badge>
                            <span className="text-xs text-muted-foreground">{d.reason}</span>
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            disabled={busy === `dep-${d.id}`}
                            onClick={() => handleToggleDeployment(d)}
                          >
                            {d.is_enabled ? "Pause" : "Resume"}
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={busy === `dep-${d.id}`}
                            onClick={() => handleUnbind(d)}
                          >
                            Unbind
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          <DeploymentForm
            labs={labs}
            templates={templates}
            boards={boards}
            deployments={deployments}
            onDone={refresh}
          />
        </CardContent>
      </Card>

      {/* Spare hardware */}
      {unused.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Unused hardware</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">
              Attached, but no lab template asks for it — worth knowing before anyone buys another.
            </p>
            <ul className="space-y-1 text-sm">
              {unused.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{d.usb_serial ?? d.sysfs_path}</span>
                  <span className="text-muted-foreground">
                    {describeDevice(d.manufacturer, d.product)}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      <ClaimBoardDialog
        device={claiming}
        captureOptions={captureDevices}
        onClose={() => setClaiming(null)}
        onDone={refresh}
      />
      <TokenDialog issued={issuedToken} onClose={() => setIssuedToken(null)} />
    </div>
  );
}

/** Shown once, and only once — the server keeps a hash, so this value
 *  cannot be recovered afterwards. Deliberately a modal the admin has to
 *  dismiss rather than a toast that disappears on its own. */
function TokenDialog({
  issued,
  onClose,
}: {
  issued: { name: string; token: string } | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={issued !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        {issued && (
          <>
            <h2 className="text-lg font-semibold">Agent token for {issued.name}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Copy this now. Only its hash is stored, so it cannot be shown again — a lost token has
              to be replaced with a new one.
            </p>
            <pre className="mt-3 overflow-x-auto rounded-md border bg-muted p-3 font-mono text-xs">
              {issued.token}
            </pre>
            <p className="mt-3 text-sm text-muted-foreground">
              Put it in <code className="font-mono text-xs">/etc/fpga-lab-agent/agent.conf</code> on
              that machine, then start <code className="font-mono text-xs">fpga-lab-agent</code>.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="secondary"
                onClick={() => {
                  navigator.clipboard?.writeText(issued.token);
                }}
              >
                Copy
              </Button>
              <Button onClick={onClose}>Done</Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Recording what a detected programmer is actually attached to. */
function ClaimBoardDialog({
  device,
  captureOptions,
  onClose,
  onDone,
}: {
  device: UnclaimedDevice | null;
  captureOptions: Device[];
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const { showError, showSuccess } = useToast();
  const [label, setLabel] = useState("");
  const [family, setFamily] = useState(FAMILIES[0].value);
  const [gpio, setGpio] = useState("");
  const [capture, setCapture] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLabel("");
    setFamily(FAMILIES[0].value);
    setGpio("");
    // Pre-select when the shuttle has exactly one card - with a single
    // candidate there is nothing to choose, and making the operator
    // choose it anyway is how the field ends up skipped.
    setCapture(captureOptions.length === 1 ? (captureOptions[0].usb_serial ?? "") : "");
  }, [device?.device_id, captureOptions.length]);

  // A probed chain is offered as the expected IDCODE so a later swap is
  // noticed. Zynq parts report their ARM core alongside the fabric, so
  // the last entry is the one worth pinning.
  const suggestedIdcode = device?.jtag_chain?.length
    ? device.jtag_chain[device.jtag_chain.length - 1].idcode
    : null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!device || !label.trim()) return;
    setSaving(true);
    try {
      await api.registerBoard({
        label: label.trim(),
        family,
        programmer_serial: device.usb_serial,
        expected_idcode: suggestedIdcode,
        video_capture_serial: capture || null,
        gpio_endpoint: gpio.trim() || null,
      });
      showSuccess(`${label.trim()} registered`);
      onClose();
      await onDone();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to register board");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={device !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        {device && (
          <form onSubmit={handleSubmit}>
            <h2 className="text-lg font-semibold">Register board</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Programmer <span className="font-mono text-xs">{device.usb_serial}</span> on{" "}
              {device.shuttle_name}. Identity binds to this serial, so the board keeps its
              registration when moved to another port or machine.
            </p>

            <div className="mt-4 space-y-3">
              <div>
                <Label htmlFor="board-label">Label</Label>
                <Input
                  id="board-label"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="EduPow 2.1 CIV #10"
                  autoFocus
                />
              </div>

              <div>
                <Label htmlFor="board-family">FPGA family</Label>
                <select
                  id="board-family"
                  value={family}
                  onChange={(e) => setFamily(e.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
                >
                  {FAMILIES.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
                {suggestedIdcode ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Probed IDCODE{" "}
                    <span className="font-mono">{suggestedIdcode}</span> will be recorded, so a
                    later hardware swap is flagged. An IDCODE can be shared by several families —
                    pick the one this board actually is.
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">
                    This programmer has not been JTAG-probed, so the family cannot be guessed.
                  </p>
                )}
              </div>

              <div>
                <Label htmlFor="board-capture">HDMI capture card</Label>
                <select
                  id="board-capture"
                  value={capture}
                  onChange={(e) => setCapture(e.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <option value="">None</option>
                  {captureOptions.map((c) => (
                    <option key={c.id} value={c.usb_serial ?? ""}>
                      {describeDevice(c.manufacturer, c.product)} — {c.usb_serial}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-muted-foreground">
                  A capture card watches one board's HDMI output, so it is recorded per board.
                  Without this the lab's video cannot be checked.
                </p>
              </div>

              <div>
                <Label htmlFor="board-gpio">GPIO controller (optional)</Label>
                <Input
                  id="board-gpio"
                  value={gpio}
                  onChange={(e) => setGpio(e.target.value)}
                  placeholder="10.30.70.50:20000"
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  The Raspberry Pi driving this board's switches, if it has one.
                </p>
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving || !label.trim()}>
                Register
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Binding a catalogue entry to a board. Only offered for labs that are
 *  not already bound, so the 409 the API would return is never reachable
 *  through the UI. */
function DeploymentForm({
  labs,
  templates,
  boards,
  deployments,
  onDone,
}: {
  labs: Lab[];
  templates: LabTemplate[];
  boards: Board[];
  deployments: Deployment[];
  onDone: () => Promise<void>;
}) {
  const { showError, showSuccess } = useToast();
  const bound = new Set(deployments.map((d) => d.lab_id));
  const available = labs.filter((l) => !bound.has(l.id));

  const [labId, setLabId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [boardId, setBoardId] = useState("");
  const [port, setPort] = useState("");
  const [saving, setSaving] = useState(false);

  if (available.length === 0 || templates.length === 0 || boards.length === 0) {
    return (
      <p className="mt-4 text-xs text-muted-foreground">
        {templates.length === 0
          ? "Define a lab template first — a deployment needs to know what the lab requires."
          : boards.length === 0
            ? "Register a board first — a deployment needs hardware to point at."
            : "Every lab is already bound to a board."}
      </p>
    );
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!labId || !templateId || !boardId || !port) return;
    setSaving(true);
    try {
      await api.createDeployment({
        lab_id: Number(labId),
        template_id: Number(templateId),
        board_id: Number(boardId),
        port: Number(port),
      });
      showSuccess("Lab bound to board");
      setLabId("");
      setTemplateId("");
      setBoardId("");
      setPort("");
      await onDone();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to create deployment");
    } finally {
      setSaving(false);
    }
  }

  const selectClass =
    "mt-1 h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none";

  return (
    <form onSubmit={handleSubmit} className="mt-5 grid gap-3 border-t pt-4 sm:grid-cols-4">
      <div>
        <Label htmlFor="dep-lab">Lab</Label>
        <select
          id="dep-lab"
          value={labId}
          onChange={(e) => setLabId(e.target.value)}
          className={selectClass}
        >
          <option value="">Select…</option>
          {available.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <Label htmlFor="dep-template">Template</Label>
        <select
          id="dep-template"
          value={templateId}
          onChange={(e) => setTemplateId(e.target.value)}
          className={selectClass}
        >
          <option value="">Select…</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <Label htmlFor="dep-board">Board</Label>
        <select
          id="dep-board"
          value={boardId}
          onChange={(e) => setBoardId(e.target.value)}
          className={selectClass}
        >
          <option value="">Select…</option>
          {boards.map((b) => (
            <option key={b.id} value={b.id}>
              {b.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-end gap-2">
        <div className="grow">
          <Label htmlFor="dep-port">Port</Label>
          <Input
            id="dep-port"
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="5001"
            inputMode="numeric"
          />
        </div>
        <Button type="submit" disabled={saving || !labId || !templateId || !boardId || !port}>
          Bind
        </Button>
      </div>
    </form>
  );
}
