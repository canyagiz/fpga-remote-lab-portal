import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  LabRequirement,
  LabTemplate,
  ProvisionJobStatus,
  ProvisionRequest,
  ScanResult,
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

function describeDevice(manufacturer: string | null, product: string | null): string {
  const maker = manufacturer?.trim() ?? "";
  const name = product?.trim() ?? "";
  if (!maker) return name || "Unknown device";
  if (!name) return maker;
  return name.toLowerCase().startsWith(maker.toLowerCase()) ? name : `${maker} ${name}`;
}

function formatWhen(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function StatusBadge({ status }: { status: string }) {
  if (status === "online") return <Badge variant="success">online</Badge>;
  if (status === "offline") return <Badge variant="destructive">offline</Badge>;
  return <Badge variant="outline">awaiting first report</Badge>;
}

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

type Section = "overview" | "shuttles" | "boards" | "labs" | "deployments" | "discovery";

const SECTIONS: Section[] = ["overview", "shuttles", "boards", "labs", "deployments", "discovery"];

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

  const [searchParams, setSearchParams] = useSearchParams();
  const sectionParam = searchParams.get("section");
  const section: Section = (SECTIONS as string[]).includes(sectionParam ?? "")
    ? (sectionParam as Section)
    : "overview";
  const setSection = (next: Section) =>
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.set("section", next);
        return params;
      },
      { replace: true },
    );
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);

  const [issuedToken, setIssuedToken] = useState<{ name: string; token: string } | null>(null);
  const [claiming, setClaiming] = useState<UnclaimedDevice | null>(null);
  const [newShuttleName, setNewShuttleName] = useState("");
  // Which board/shuttle a network-backed endpoint is being set for.
  const [gpioBoard, setGpioBoard] = useState<Board | null>(null);
  const [addressShuttle, setAddressShuttle] = useState<Shuttle | null>(null);
  const [provTarget, setProvTarget] = useState<Shuttle | null>(null);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
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
      setLastRefresh(new Date().toISOString());
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to load fleet data");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    refresh();
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

  function handleAddress(shuttle: Shuttle) {
    setAddressShuttle(shuttle);
    if (!scan && !scanning) void handleScan();
  }

  async function saveAddress(shuttle: Shuttle, address: string) {
    if (!address.trim()) return;
    setBusy(`addr-${shuttle.id}`);
    try {
      await api.setShuttleAddress(shuttle.id, address.trim());
      showSuccess(`${shuttle.name} address set`);
      setAddressShuttle(null);
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
      `Which capture card watches ${board.label}?\n\n${options}\n\n` + `Enter the number, or 0 for none.`,
      "1",
    );
    if (answer === null) return;
    const index = Number(answer);
    if (Number.isNaN(index) || index < 0 || index > captureDevices.length) return;

    setBusy(`board-${board.id}`);
    try {
      await api.updateBoard(board.id, {
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

  function handleSetGpio(board: Board) {
    setGpioBoard(board);
    if (!scan && !scanning) void handleScan();
  }

  async function saveGpio(board: Board, endpoint: string) {
    setBusy(`board-${board.id}`);
    try {
      // Empty clears it. A non-empty endpoint the network cannot reach is
      // refused by the backend, which is the point of tying this to
      // Discovery - you cannot bind a Pi that is not there.
      await api.updateBoard(board.id, { gpio_endpoint: endpoint.trim() || "" });
      showSuccess(`${board.label} updated`);
      setGpioBoard(null);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to update board");
    } finally {
      setBusy(null);
    }
  }

  async function handleDeleteTemplate(template: LabTemplate) {
    if (!confirm(`Delete template "${template.name}"? Any lab bound to it must be unbound first.`)) return;
    setBusy(`tpl-${template.id}`);
    try {
      await api.deleteTemplate(template.id);
      showSuccess(`Template ${template.name} deleted`);
      await refresh();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to delete template");
    } finally {
      setBusy(null);
    }
  }

  async function handleDeleteBoard(board: Board) {
    if (!confirm(`Deregister "${board.label}"? The hardware stays; only its registration is removed.`)) return;
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

  async function handleScan() {
    setScanning(true);
    try {
      setScan(await api.scanNetwork());
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  }

  const captureDevices = devices.filter((d) => d.kind === "video_capture");
  // Serials an agent is reporting right now - so the Boards table can
  // show whether a recorded programmer/capture is still physically there.
  const presentSerials = new Set(devices.map((d) => d.usb_serial).filter(Boolean) as string[]);
  // Pis usable as GPIO endpoints, and hosts usable as shuttle addresses,
  // straight from the last network scan.
  const discoveredGpio = (scan?.hosts ?? [])
    .filter((h) => h.kind === "raspberry_pi" && h.open_ports.includes(20000))
    .map((h) => ({ value: `${h.ip}:20000`, label: `Raspberry Pi ${h.ip}`, note: h.note ?? undefined }));
  const discoveredAddresses = (scan?.hosts ?? [])
    .filter((h) => h.kind === "proxmox" || h.kind === "host")
    .map((h) => ({ value: h.ip, label: h.ip, note: h.vendor }));
  const knownSignatures = Array.from(
    new Set(devices.filter((d) => d.kind === "programmer" && d.signature).map((d) => d.signature as string)),
  ).sort();
  const onlineCount = shuttles.filter((s) => s.status === "online").length;
  const blockedGaps = gaps.filter((g) => !g.deployable);
  const readyLabs = gaps.filter((g) => g.deployable).length;
  const withdrawn = deployments.filter((d) => !d.available);

  // The one list that makes the overview worth opening: everything that
  // wants a human, each linking to the section where it is fixed.
  const attention: { text: string; section: Section }[] = [];
  unclaimed.forEach((u) =>
    attention.push({ text: `New hardware on ${u.shuttle_name}: ${u.usb_serial} — register it as a board`, section: "shuttles" }),
  );
  shuttles.filter((s) => s.status === "offline").forEach((s) => attention.push({ text: `${s.name} has stopped reporting`, section: "shuttles" }));
  shuttles.filter((s) => !s.address).forEach((s) => attention.push({ text: `${s.name} has no address set`, section: "shuttles" }));
  // Only the families whose own templates actually ask for a capture
  // card - a board whose family never needs one (Arty Z7's template has
  // no video_capture requirement at all) is not missing anything by
  // lacking a serial here, and flagging it anyway is exactly the "the
  // template exists, so it must be filled" assumption this list should
  // not make.
  const familiesNeedingCapture = new Set(
    templates
      .filter((t) => t.requirements.some((r) => r.type === "video_capture"))
      .map((t) => fpgaFamilyOf(t.requirements))
      .filter((f): f is string => f !== null),
  );
  boards
    .filter((b) => familiesNeedingCapture.has(b.family) && !b.video_capture_serial)
    .forEach((b) => attention.push({ text: `${b.label} has no capture card recorded`, section: "boards" }));
  blockedGaps.forEach((g) =>
    attention.push({ text: `${g.template_name} on ${g.shuttle_name}: ${g.missing_count} unmet requirement${g.missing_count === 1 ? "" : "s"}`, section: "labs" }),
  );
  withdrawn.forEach((d) => attention.push({ text: `${d.lab_name} withdrawn — ${d.reason}`, section: "deployments" }));

  const NAV: { id: Section; label: string; badge?: number; alert?: boolean }[] = [
    { id: "overview", label: "Overview", badge: attention.length || undefined, alert: attention.length > 0 },
    { id: "shuttles", label: "Shuttles", badge: shuttles.length || undefined, alert: unclaimed.length > 0 },
    { id: "boards", label: "Boards", badge: boards.length || undefined },
    { id: "labs", label: "Labs", badge: templates.length || undefined, alert: blockedGaps.length > 0 },
    { id: "deployments", label: "Deployments", badge: deployments.length || undefined, alert: withdrawn.length > 0 },
    { id: "discovery", label: "Discovery" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Fleet</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {shuttles.length} shuttle{shuttles.length === 1 ? "" : "s"} ({onlineCount} online) ·{" "}
            {boards.length} board{boards.length === 1 ? "" : "s"} · {readyLabs}/{gaps.length || 0} labs ready
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-xs text-muted-foreground">updated {formatWhen(lastRefresh)}</span>
          <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh"}
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link to="/admin/fleet/graph">Topology view →</Link>
          </Button>
        </div>
      </div>

      <div className="mt-6 flex flex-col gap-6 md:flex-row">
        {/* Sidebar */}
        <nav className="flex shrink-0 gap-1 overflow-x-auto md:w-48 md:flex-col md:overflow-visible">
          {NAV.map((item) => {
            const active = section === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setSection(item.id)}
                className={`flex items-center justify-between gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                  active ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
                }`}
              >
                <span className="flex items-center gap-1.5">
                  {item.alert && (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "var(--warning)" }} />
                  )}
                  {item.label}
                </span>
                {item.badge != null && (
                  <span className="rounded-full bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Detail pane */}
        <div className="min-w-0 flex-1 space-y-6">
          {/* -------------------------------- Overview -------------------------------- */}
          {section === "overview" && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Tile label="Shuttles" value={`${onlineCount}/${shuttles.length}`} sub="online" onClick={() => setSection("shuttles")} />
                <Tile label="Boards" value={String(boards.length)} sub="registered" onClick={() => setSection("boards")} />
                <Tile label="Labs ready" value={`${readyLabs}/${gaps.length || 0}`} sub="deployable" onClick={() => setSection("labs")} />
                <Tile
                  label="Attention"
                  value={String(attention.length)}
                  sub={attention.length ? "to resolve" : "all clear"}
                  alert={attention.length > 0}
                />
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>Needs attention</CardTitle>
                </CardHeader>
                <CardContent>
                  {attention.length === 0 ? (
                    <p className="py-4 text-center text-sm text-muted-foreground">
                      Nothing to resolve — every shuttle is reporting, every board is complete, and no lab is blocked.
                    </p>
                  ) : (
                    <ul className="space-y-1.5">
                      {attention.map((a, i) => (
                        <li key={i}>
                          <button
                            onClick={() => setSection(a.section)}
                            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-secondary/60"
                          >
                            <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "var(--warning)" }} />
                            <span className="flex-1">{a.text}</span>
                            <span className="text-xs text-muted-foreground">{a.section} →</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Find hardware on the network</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="mb-3 text-sm text-muted-foreground">
                    Scan the lab network for Raspberry Pis and shuttles — like a Wi-Fi scan, for wiring things up.
                  </p>
                  <Button size="sm" onClick={() => setSection("discovery")}>
                    Open Discovery →
                  </Button>
                </CardContent>
              </Card>
            </>
          )}

          {/* -------------------------------- Shuttles -------------------------------- */}
          {section === "shuttles" && (
            <>
              {unclaimed.length > 0 && (
                <Card className="border-warning-muted-foreground/40">
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
                      A programmer is attached that no board claims yet. An IDCODE identifies the chip, not the board
                      it sits on — so which board this is has to be recorded by a person, once.
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
                              <TableCell>{describeDevice(d.manufacturer, d.product)}</TableCell>
                              <TableCell className="text-muted-foreground">{d.shuttle_name}</TableCell>
                              <TableCell className="font-mono text-xs text-muted-foreground">
                                {d.jtag_chain?.length ? d.jtag_chain.map((c) => c.idcode).join(", ") : "not probed"}
                              </TableCell>
                              <TableCell className="text-muted-foreground">{formatWhen(d.first_seen_at)}</TableCell>
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

              <Card>
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
                          <EmptyRow colSpan={7}>No shuttles yet. Enrol one below, then install the agent on it.</EmptyRow>
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
                                {s.address ? s.address : <span className="text-warning-muted-foreground">not set</span>}
                                {s.hostname && <span className="block text-[10px] text-muted-foreground">{s.hostname}</span>}
                              </TableCell>
                              <TableCell>{s.device_count}</TableCell>
                              <TableCell className="text-muted-foreground">{s.agent_version ?? "—"}</TableCell>
                              <TableCell className="text-muted-foreground">{formatWhen(s.last_report_at)}</TableCell>
                              <TableCell className="text-right">
                                <div className="flex justify-end gap-2">
                                  <Button size="sm" variant="secondary" disabled={busy === `addr-${s.id}`} onClick={() => handleAddress(s)}>
                                    Set address
                                  </Button>
                                  <Button size="sm" variant="secondary" disabled={busy === `rotate-${s.id}`} onClick={() => handleRotate(s)}>
                                    New token
                                  </Button>
                                  <Button
                                    size="sm"
                                    disabled={s.role === "master"}
                                    title={s.role === "master" ? "The master runs the portal — provision new shuttles instead" : undefined}
                                    onClick={() => setProvTarget(s)}
                                  >
                                    Provision
                                  </Button>
                                  <Button size="sm" variant="destructive" disabled={busy === `del-${s.id}`} onClick={() => handleRemoveShuttle(s)}>
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
                      <Input id="shuttle-name" value={newShuttleName} onChange={(e) => setNewShuttleName(e.target.value)} placeholder="pc-3vrl07" />
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

              <Card>
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
                          <TableHead>Status</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {devices.length === 0 ? (
                          <EmptyRow colSpan={6}>
                            Nothing reported yet. An enrolled shuttle only appears here once its agent is installed and running.
                          </EmptyRow>
                        ) : (
                          devices.map((d) => {
                            const board = boards.find(
                              (b) => b.programmer_serial === d.usb_serial || b.video_capture_serial === d.usb_serial,
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
                                <TableCell className="font-mono text-xs text-muted-foreground">{d.sysfs_path}</TableCell>
                                <TableCell>
                                  {board ? board.label : <span className="text-muted-foreground">not claimed</span>}
                                </TableCell>
                                <TableCell>
                                  {/* Every reported device is connected right now (the list
                                      only shows present ones); a capture card additionally
                                      says whether an HDMI signal is arriving. */}
                                  {d.kind === "video_capture" ? (
                                    d.has_video_signal === true ? (
                                      <Badge variant="success">signal</Badge>
                                    ) : d.has_video_signal === false ? (
                                      <Badge variant="destructive">no signal</Badge>
                                    ) : (
                                      <Badge variant="outline">signal unknown</Badge>
                                    )
                                  ) : (
                                    <Badge variant="success">connected</Badge>
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
            </>
          )}

          {/* -------------------------------- Boards -------------------------------- */}
          {section === "boards" && (
            <Card>
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
                        <EmptyRow colSpan={7}>No boards registered. They appear here once you claim a detected programmer.</EmptyRow>
                      ) : (
                        boards.map((b) => (
                          <TableRow key={b.id}>
                            <TableCell className="font-medium">{b.label}</TableCell>
                            <TableCell>{familyLabel(b.family)}</TableCell>
                            <TableCell className="font-mono text-xs">
                              {b.programmer_serial}
                              {presentSerials.has(b.programmer_serial) ? (
                                <span className="ml-1.5 align-middle text-[10px] font-semibold" style={{ color: "var(--success)" }}>● present</span>
                              ) : (
                                <span className="ml-1.5 align-middle text-[10px] font-semibold" style={{ color: "var(--destructive)" }}>● absent</span>
                              )}
                            </TableCell>
                            <TableCell>
                              {b.shuttle_name ? b.shuttle_name : <span className="text-muted-foreground">not attached</span>}
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                              {b.video_capture_serial ? (
                                <>
                                  {b.video_capture_serial}
                                  {presentSerials.has(b.video_capture_serial) ? (
                                    <span className="ml-1.5 align-middle text-[10px] font-semibold" style={{ color: "var(--success)" }}>● present</span>
                                  ) : (
                                    <span className="ml-1.5 align-middle text-[10px] font-semibold" style={{ color: "var(--destructive)" }}>● absent</span>
                                  )}
                                </>
                              ) : (
                                <span className="text-warning-muted-foreground">not set</span>
                              )}
                            </TableCell>
                            <TableCell className="font-mono text-xs text-muted-foreground">{b.gpio_endpoint ?? "—"}</TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-2">
                                <Button size="sm" variant="secondary" disabled={busy === `board-${b.id}` || captureDevices.length === 0} onClick={() => handleSetCapture(b)}>
                                  Set capture
                                </Button>
                                <Button size="sm" variant="secondary" disabled={busy === `board-${b.id}`} onClick={() => handleSetGpio(b)}>
                                  Set GPIO
                                </Button>
                                <Button size="sm" variant="destructive" disabled={busy === `board-${b.id}`} onClick={() => handleDeleteBoard(b)}>
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
          )}

          {/* -------------------------------- Labs -------------------------------- */}
          {section === "labs" && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Lab templates</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="mb-3 text-sm text-muted-foreground">
                    A template states what a lab needs, once — creating one describes a possible lab, it does not
                    commit any shuttle to providing it. Below, the system compares it only against shuttles that
                    actually have the board it names; one with no such board yet has nothing to report.
                  </p>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Name</TableHead>
                          <TableHead>Requires</TableHead>
                          <TableHead />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {templates.length === 0 ? (
                          <EmptyRow colSpan={3}>No templates yet. Until one exists there is nothing to check hardware against.</EmptyRow>
                        ) : (
                          templates.map((t) => (
                            <TableRow key={t.id}>
                              <TableCell>
                                <div className="font-medium">{t.name}</div>
                                {t.description && <div className="text-xs text-muted-foreground">{t.description}</div>}
                              </TableCell>
                              <TableCell>
                                <div className="flex flex-wrap gap-1.5">
                                  {t.requirements.map((r, i) => {
                                    const d = describeRequirement(r);
                                    return (
                                      <Badge key={i} variant="outline" title={d.detail}>
                                        {d.label}: {d.detail}
                                      </Badge>
                                    );
                                  })}
                                </div>
                              </TableCell>
                              <TableCell className="text-right">
                                <Button size="sm" variant="destructive" disabled={busy === `tpl-${t.id}`} onClick={() => handleDeleteTemplate(t)}>
                                  Delete
                                </Button>
                              </TableCell>
                            </TableRow>
                          ))
                        )}
                      </TableBody>
                    </Table>
                  </div>
                  <TemplateForm signatures={knownSignatures} onDone={refresh} />
                </CardContent>
              </Card>

              <Card>
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
                      No lab templates defined yet — a template says what a lab requires, and this is where the answer to
                      "what is missing" appears.
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
                                <span className={r.status === "satisfied" ? "text-muted-foreground" : "text-foreground"}>
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
            </>
          )}

          {/* -------------------------------- Deployments -------------------------------- */}
          {section === "deployments" && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Labs &amp; serving</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="mb-3 text-sm text-muted-foreground">
                    A lab is served only when it is <strong className="font-semibold text-foreground">bound to a board</strong>
                    whose hardware is currently fit: the address is resolved from wherever the board actually is, and the
                    lab is withdrawn automatically the moment its hardware fails. An <strong className="font-semibold text-foreground">unbound</strong>
                    lab is not offered to students at all. Bind a lab below to serve it.
                  </p>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Lab</TableHead>
                          <TableHead>Serving from</TableHead>
                          <TableHead>Served</TableHead>
                          <TableHead>State</TableHead>
                          <TableHead />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {labs.length === 0 ? (
                          <EmptyRow colSpan={5}>No labs in the catalogue.</EmptyRow>
                        ) : (
                          labs.map((lab) => {
                            const dep = deployments.find((d) => d.lab_id === lab.id);
                            return (
                              <TableRow key={lab.id}>
                                <TableCell className="font-medium">{lab.name}</TableCell>
                                <TableCell>
                                  {dep ? (
                                    <span>
                                      {dep.board_label}
                                      <span className="text-muted-foreground"> :{dep.port}</span>
                                    </span>
                                  ) : (
                                    <span className="text-muted-foreground">static address</span>
                                  )}
                                </TableCell>
                                <TableCell>
                                  {dep && dep.available ? (
                                    <Badge variant="success">yes</Badge>
                                  ) : dep ? (
                                    <Badge variant="destructive">withdrawn</Badge>
                                  ) : (
                                    <Badge variant="outline">no</Badge>
                                  )}
                                </TableCell>
                                <TableCell>
                                  {!dep ? (
                                    <span className="text-xs" style={{ color: "var(--warning)" }}>not served — bind a board</span>
                                  ) : dep.available ? (
                                    <div className="flex flex-col gap-0.5">
                                      <Badge variant="success" className="w-fit">serving</Badge>
                                      <span className="font-mono text-[10px] text-muted-foreground">{dep.backend_url}</span>
                                    </div>
                                  ) : (
                                    <div className="flex flex-col gap-0.5">
                                      <Badge variant="destructive" className="w-fit">withdrawn</Badge>
                                      <span className="text-xs text-muted-foreground">{dep.reason}</span>
                                    </div>
                                  )}
                                </TableCell>
                                <TableCell className="text-right">
                                  {dep ? (
                                    <div className="flex justify-end gap-2">
                                      <Button size="sm" variant="secondary" disabled={busy === `dep-${dep.id}`} onClick={() => handleToggleDeployment(dep)}>
                                        {dep.is_enabled ? "Pause" : "Resume"}
                                      </Button>
                                      <Button size="sm" variant="destructive" disabled={busy === `dep-${dep.id}`} onClick={() => handleUnbind(dep)}>
                                        Unbind
                                      </Button>
                                    </div>
                                  ) : (
                                    <span className="text-xs text-muted-foreground">bind below to monitor</span>
                                  )}
                                </TableCell>
                              </TableRow>
                            );
                          })
                        )}
                      </TableBody>
                    </Table>
                  </div>
                  <DeploymentForm labs={labs} templates={templates} boards={boards} deployments={deployments} onDone={refresh} />
                </CardContent>
              </Card>

              {unused.length > 0 && (
                <Card>
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
                          <span className="text-muted-foreground">{describeDevice(d.manufacturer, d.product)}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </>
          )}

          {/* -------------------------------- Discovery -------------------------------- */}
          {section === "discovery" && (
            <Card>
              <CardHeader>
                <CardTitle>Discovery</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="max-w-xl text-sm text-muted-foreground">
                    Scan the lab network for what isn't a USB device — the Raspberry Pis that drive board switches, other
                    shuttles, any reachable host. Read-only; it only opens and closes a connection, nothing is sent.
                  </p>
                  <Button onClick={handleScan} disabled={scanning}>
                    {scanning ? "Scanning…" : scan ? "Scan again" : "Scan network"}
                  </Button>
                </div>

                {scan && (
                  <>
                    <p className="mt-4 text-xs text-muted-foreground">
                      {scan.subnet} · {scan.hosts.length} host{scan.hosts.length === 1 ? "" : "s"} · {scan.duration_ms} ms
                    </p>
                    <div className="mt-2 overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Address</TableHead>
                            <TableHead>What</TableHead>
                            <TableHead>Open ports</TableHead>
                            <TableHead>MAC</TableHead>
                            <TableHead>Note</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {scan.hosts.map((h) => (
                            <TableRow key={h.ip}>
                              <TableCell className="font-mono text-xs">{h.ip}</TableCell>
                              <TableCell>
                                <KindBadge kind={h.kind} />
                                <span className="ml-2 text-xs text-muted-foreground">{h.vendor}</span>
                              </TableCell>
                              <TableCell className="font-mono text-xs text-muted-foreground">
                                {h.open_ports.length ? h.open_ports.join(", ") : "—"}
                              </TableCell>
                              <TableCell className="font-mono text-[10px] text-muted-foreground">{h.mac ?? "—"}</TableCell>
                              <TableCell className="text-xs">
                                {h.note ? <span className="text-foreground">{h.note}</span> : <span className="text-muted-foreground">—</span>}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                    <p className="mt-3 text-xs text-muted-foreground">
                      A Pi flagged "usable as a GPIO endpoint" can be wired to a board from the Boards section with Set GPIO.
                    </p>
                  </>
                )}

                {!scan && !scanning && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    No scan yet. It takes a couple of seconds and only touches the portal's own subnet.
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <ClaimBoardDialog
        device={claiming}
        captureOptions={captureDevices}
        gpioOptions={discoveredGpio}
        hasScan={scan !== null}
        scanning={scanning}
        onScan={handleScan}
        onClose={() => setClaiming(null)}
        onDone={refresh}
      />
      <TokenDialog issued={issuedToken} onClose={() => setIssuedToken(null)} />
      <PickerDialog
        open={gpioBoard !== null}
        title={gpioBoard ? `GPIO controller for ${gpioBoard.label}` : ""}
        description="The Raspberry Pi that drives this board's switches. Pick one Discovery found, or type an address — the network is checked before it is saved, so a Pi that isn't there is refused."
        options={discoveredGpio}
        current={gpioBoard?.gpio_endpoint ?? ""}
        manualPlaceholder="10.30.70.50:20000"
        hasScan={scan !== null}
        scanning={scanning}
        onScan={handleScan}
        onClose={() => setGpioBoard(null)}
        onSave={(v) => gpioBoard && saveGpio(gpioBoard, v)}
      />
      <PickerDialog
        open={addressShuttle !== null}
        title={addressShuttle ? `Address for ${addressShuttle.name}` : ""}
        description="Where this shuttle's lab containers are reached — student browsers are sent here. Pick a host Discovery found, or type one."
        options={discoveredAddresses}
        current={addressShuttle?.address ?? ""}
        manualPlaceholder="10.30.70.23"
        hasScan={scan !== null}
        scanning={scanning}
        onScan={handleScan}
        onClose={() => setAddressShuttle(null)}
        onSave={(v) => addressShuttle && saveAddress(addressShuttle, v)}
      />
      <ProvisionWizard shuttle={provTarget} onClose={() => setProvTarget(null)} onDone={refresh} />
    </div>
  );
}

function Tile({
  label,
  value,
  sub,
  alert,
  onClick,
}: {
  label: string;
  value: string;
  sub: string;
  alert?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={!onClick}
      className={`rounded-xl border bg-card p-4 text-left transition-colors ${onClick ? "hover:border-ring/60" : ""}`}
    >
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="text-2xl font-bold tabular-nums" style={alert ? { color: "var(--warning)" } : undefined}>
          {value}
        </span>
        <span className="text-xs text-muted-foreground">{sub}</span>
      </div>
    </button>
  );
}

function KindBadge({ kind }: { kind: string }) {
  if (kind === "raspberry_pi") return <Badge variant="success">Raspberry Pi</Badge>;
  if (kind === "proxmox") return <Badge variant="secondary">Proxmox</Badge>;
  return <Badge variant="outline">Host</Badge>;
}

/** A pick-from-the-network-or-type dialog. The options come from the
 *  last discovery scan, so an admin binds a Pi or a shuttle address to
 *  something that is actually on the network, not a remembered guess. */
function PickerDialog({
  open,
  title,
  description,
  options,
  current,
  manualPlaceholder,
  hasScan,
  scanning,
  onScan,
  onSave,
  onClose,
}: {
  open: boolean;
  title: string;
  description: string;
  options: { value: string; label: string; note?: string }[];
  current: string;
  manualPlaceholder: string;
  hasScan: boolean;
  scanning: boolean;
  onScan: () => void;
  onSave: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(current);
  useEffect(() => {
    setValue(current);
  }, [current, open]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        <div className="mt-4 space-y-2">
          {options.length > 0 ? (
            <select
              value=""
              onChange={(e) => e.target.value && setValue(e.target.value)}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
            >
              <option value="">Choose from the network…</option>
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                  {o.note ? ` — ${o.note}` : ""}
                </option>
              ))}
            </select>
          ) : (
            <Button type="button" size="sm" variant="secondary" disabled={scanning} onClick={onScan}>
              {scanning ? "Scanning…" : hasScan ? "Nothing found — scan again" : "Scan network"}
            </Button>
          )}
          <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder={manualPlaceholder} />
          <p className="text-xs text-muted-foreground">Leave blank to clear.</p>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => onSave(value)}>Save</Button>
        </div>
      </DialogContent>
    </Dialog>
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
              Copy this now. Only its hash is stored, so it cannot be shown again — a lost token has to be replaced with a
              new one.
            </p>
            <pre className="mt-3 overflow-x-auto rounded-md border bg-muted p-3 font-mono text-xs">{issued.token}</pre>
            <p className="mt-3 text-sm text-muted-foreground">
              Put it in <code className="font-mono text-xs">/etc/fpga-lab-agent/agent.conf</code> on that machine, then
              start <code className="font-mono text-xs">fpga-lab-agent</code>.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(issued.token)}>
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
  gpioOptions,
  hasScan,
  scanning,
  onScan,
  onClose,
  onDone,
}: {
  device: UnclaimedDevice | null;
  captureOptions: Device[];
  gpioOptions: { value: string; label: string; note?: string }[];
  hasScan: boolean;
  scanning: boolean;
  onScan: () => void;
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
    setCapture(captureOptions.length === 1 ? (captureOptions[0].usb_serial ?? "") : "");
  }, [device?.device_id, captureOptions.length]);

  const suggestedIdcode = device?.jtag_chain?.length ? device.jtag_chain[device.jtag_chain.length - 1].idcode : null;

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
              Programmer <span className="font-mono text-xs">{device.usb_serial}</span> on {device.shuttle_name}. Identity
              binds to this serial, so the board keeps its registration when moved to another port or machine.
            </p>

            <div className="mt-4 space-y-3">
              <div>
                <Label htmlFor="board-label">Label</Label>
                <Input id="board-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="EduPow 2.1 CIV #10" autoFocus />
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
                    Probed IDCODE <span className="font-mono">{suggestedIdcode}</span> will be recorded, so a later
                    hardware swap is flagged. An IDCODE can be shared by several families — pick the one this board
                    actually is.
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
                  A capture card watches one board's HDMI output, so it is recorded per board. Without this the lab's
                  video cannot be checked.
                </p>
              </div>

              <div>
                <Label htmlFor="board-gpio">GPIO controller (optional)</Label>
                {gpioOptions.length > 0 ? (
                  <select
                    id="board-gpio-pick"
                    value=""
                    onChange={(e) => e.target.value && setGpio(e.target.value)}
                    className="mt-1 h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    <option value="">Choose a Pi Discovery found…</option>
                    {gpioOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                        {o.note ? ` — ${o.note}` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="mt-1">
                    <Button type="button" size="sm" variant="secondary" disabled={scanning} onClick={onScan}>
                      {scanning ? "Scanning…" : hasScan ? "No Pi found — scan again" : "Scan network for Pis"}
                    </Button>
                  </div>
                )}
                <Input id="board-gpio" className="mt-2" value={gpio} onChange={(e) => setGpio(e.target.value)} placeholder="10.30.70.50:20000" />
                <p className="mt-1 text-xs text-muted-foreground">
                  The Raspberry Pi driving this board's switches, if it has one. The address is checked against the network
                  before the board is saved.
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
        <select id="dep-lab" value={labId} onChange={(e) => setLabId(e.target.value)} className={selectClass}>
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
        <select id="dep-template" value={templateId} onChange={(e) => setTemplateId(e.target.value)} className={selectClass}>
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
        <select id="dep-board" value={boardId} onChange={(e) => setBoardId(e.target.value)} className={selectClass}>
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
          <Input id="dep-port" value={port} onChange={(e) => setPort(e.target.value)} placeholder="5001" inputMode="numeric" />
        </div>
        <Button type="submit" disabled={saving || !labId || !templateId || !boardId || !port}>
          Bind
        </Button>
      </div>
    </form>
  );
}

/** Human-readable summary of one stored requirement. Exhaustive with a
 *  `never` fallthrough. */
function fpgaFamilyOf(reqs: LabRequirement[]): string | null {
  for (const r of reqs) {
    if (r.type === "fpga") return r.family;
  }
  return null;
}

function describeRequirement(req: LabRequirement): { label: string; detail: string } {
  switch (req.type) {
    case "fpga":
      return { label: "FPGA board", detail: familyLabel(req.family) };
    case "programmer":
      return { label: "Programmer", detail: req.signature };
    case "video_capture":
      return { label: "HDMI capture", detail: req.require_signal ? "live signal required" : "card present is enough" };
    case "gpio":
      return { label: "GPIO controller", detail: "assigned to the board" };
    default: {
      const exhaustive: never = req;
      return { label: String(exhaustive), detail: "" };
    }
  }
}

const REQUIREMENT_KINDS: { type: LabRequirement["type"]; label: string; blank: LabRequirement }[] = [
  { type: "fpga", label: "FPGA board", blank: { type: "fpga", family: FAMILIES[0].value } },
  { type: "programmer", label: "Programmer", blank: { type: "programmer", signature: "" } },
  { type: "video_capture", label: "HDMI capture", blank: { type: "video_capture", require_signal: true } },
  { type: "gpio", label: "GPIO controller", blank: { type: "gpio" } },
];

/** Builds a lab template: what a lab needs, stated once. One requirement
 *  of each type at most. */
function TemplateForm({ signatures, onDone }: { signatures: string[]; onDone: () => Promise<void> }) {
  const { showError, showSuccess } = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [requirements, setRequirements] = useState<LabRequirement[]>([]);
  const [saving, setSaving] = useState(false);

  const used = new Set(requirements.map((r) => r.type));

  function add(blank: LabRequirement) {
    setRequirements((current) => [...current, blank]);
  }
  function removeAt(index: number) {
    setRequirements((current) => current.filter((_, i) => i !== index));
  }
  function updateAt(index: number, next: LabRequirement) {
    setRequirements((current) => current.map((r, i) => (i === index ? next : r)));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || requirements.length === 0) return;
    setSaving(true);
    try {
      await api.createTemplate({ name: name.trim(), description: description.trim() || null, requirements });
      showSuccess(`Template "${name.trim()}" created`);
      setName("");
      setDescription("");
      setRequirements([]);
      await onDone();
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Failed to create template");
    } finally {
      setSaving(false);
    }
  }

  const selectClass = "h-8 rounded-md border border-input bg-transparent px-2 text-sm focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none";

  return (
    <form onSubmit={handleSubmit} className="mt-5 border-t pt-4">
      <p className="text-sm font-medium">New template</p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="tpl-name">Name</Label>
          <Input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Cyclone IV Vision Lab" />
        </div>
        <div>
          <Label htmlFor="tpl-desc">Description (optional)</Label>
          <Input id="tpl-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Image processing with live HDMI capture" />
        </div>
      </div>

      <div className="mt-4">
        <Label>Requirements</Label>
        {requirements.length === 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">
            None yet. A template with no requirements would be trivially satisfied by every shuttle, which says nothing —
            add at least one below.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {requirements.map((req, index) => (
              <li key={`${req.type}-${index}`} className="flex flex-wrap items-center gap-2 rounded-md border bg-card px-3 py-2">
                <Badge variant="secondary">{describeRequirement(req).label}</Badge>

                {req.type === "fpga" && (
                  <select aria-label="FPGA family" className={selectClass} value={req.family} onChange={(e) => updateAt(index, { type: "fpga", family: e.target.value })}>
                    {FAMILIES.map((f) => (
                      <option key={f.value} value={f.value}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                )}

                {req.type === "programmer" && (
                  <>
                    <input
                      aria-label="Programmer signature"
                      list="known-signatures"
                      className={`${selectClass} min-w-[14rem] font-mono text-xs`}
                      value={req.signature}
                      placeholder="altera-usb-blaster"
                      onChange={(e) => updateAt(index, { type: "programmer", signature: e.target.value })}
                    />
                    <datalist id="known-signatures">
                      {signatures.map((s) => (
                        <option key={s} value={s} />
                      ))}
                    </datalist>
                  </>
                )}

                {req.type === "video_capture" && (
                  <select
                    aria-label="Signal requirement"
                    className={selectClass}
                    value={req.require_signal ? "yes" : "no"}
                    onChange={(e) => updateAt(index, { type: "video_capture", require_signal: e.target.value === "yes" })}
                  >
                    <option value="yes">live signal required</option>
                    <option value="no">card present is enough</option>
                  </select>
                )}

                {req.type === "gpio" && <span className="text-xs text-muted-foreground">the board must have a controller assigned</span>}

                <Button type="button" size="sm" variant="secondary" className="ml-auto" onClick={() => removeAt(index)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          {REQUIREMENT_KINDS.map((kind) => (
            <Button
              key={kind.type}
              type="button"
              size="sm"
              variant="secondary"
              disabled={used.has(kind.type)}
              title={used.has(kind.type) ? "Already in this template" : undefined}
              onClick={() => add(kind.blank)}
            >
              + {kind.label}
            </Button>
          ))}
        </div>
      </div>

      <div className="mt-4 flex justify-end">
        <Button type="submit" disabled={saving || !name.trim() || requirements.length === 0}>
          Create template
        </Button>
      </div>
    </form>
  );
}

const PROV_BOARDS: { value: string; label: string; intel: boolean }[] = [
  { value: "civ", label: "Cyclone IV (Intel)", intel: true },
  { value: "cx", label: "Cyclone V/X (Intel)", intel: true },
  { value: "cv", label: "Cyclone V (Intel)", intel: true },
  { value: "arty", label: "Arty Z7 (Xilinx)", intel: false },
];

function LabeledInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="grow">
      <Label>{label}</Label>
      <Input value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

/** The setup wizard: turns an enrolled-but-empty shuttle into a working
 *  node. Three steps - SSH credentials, the hardware map (the "detected
 *  devices" step), then a live log while the playbook runs on the machine.
 *  Everything is pulled fresh over that SSH connection; nothing is copied
 *  from here. The token is rotated and injected server-side, so it never
 *  appears in this UI. */
function ProvisionWizard({
  shuttle,
  onClose,
  onDone,
}: {
  shuttle: Shuttle | null;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const { showError } = useToast();
  const [step, setStep] = useState(1);

  const [sshUser, setSshUser] = useState("root");
  const [sshPassword, setSshPassword] = useState("");
  const [sshHost, setSshHost] = useState("");

  const [boards, setBoards] = useState<string[]>([]);
  const [usbBlaster, setUsbBlaster] = useState("/dev/usb-blaster");
  const [magewell, setMagewell] = useState("/dev/magewell");
  const [video0, setVideo0] = useState("/dev/video0");
  const [video1, setVideo1] = useState("/dev/video1");
  const [artyUsbBus, setArtyUsbBus] = useState("/dev/bus/usb");
  const [uart, setUart] = useState<Record<string, { host: string; port: string }>>({});
  const [quartusPath, setQuartusPath] = useState("");
  const [installerMode, setInstallerMode] = useState<"upload" | "path">("upload");
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);

  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<ProvisionJobStatus | null>(null);
  const [starting, setStarting] = useState(false);

  // Reset every field when the wizard is opened for a different shuttle.
  useEffect(() => {
    if (!shuttle) return;
    setStep(1);
    setSshUser("root");
    setSshPassword("");
    setSshHost(shuttle.address ?? "");
    setBoards([]);
    setUart({});
    setQuartusPath("");
    setJobId(null);
    setStatus(null);
    setStarting(false);
    setInstallerMode("upload");
    setUploading(false);
    setUploadPct(0);
  }, [shuttle]);

  const needsQuartus = boards.some((b) => PROV_BOARDS.find((x) => x.value === b)?.intel);
  const artySelected = boards.includes("arty");

  // Poll the job while it runs; stop the moment it finishes.
  useEffect(() => {
    if (!shuttle || !jobId) return;
    let active = true;
    let handle: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const s = await api.getProvisionStatus(shuttle.id, jobId);
        if (!active) return;
        setStatus(s);
        if (s.status === "succeeded" || s.status === "failed") {
          if (s.status === "succeeded") onDone();
          return;
        }
        handle = setTimeout(tick, 1500);
      } catch (err) {
        if (active) showError(err instanceof api.ApiError ? err.message : "Lost track of the provisioning job");
      }
    };
    tick();
    return () => {
      active = false;
      if (handle) clearTimeout(handle);
    };
  }, [shuttle, jobId]);

  function toggleBoard(v: string) {
    setBoards((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));
  }

  function setUartField(board: string, field: "host" | "port", value: string) {
    setUart((prev) => {
      const current = prev[board] ?? { host: "", port: "20000" };
      return { ...prev, [board]: { ...current, [field]: value } };
    });
  }

  async function handleInstallerPick(f: File | null) {
    if (!f || !shuttle) return;
    setUploading(true);
    setUploadPct(0);
    setQuartusPath("");
    try {
      const res = await api.uploadInstaller(
        shuttle.id,
        { ssh_user: sshUser.trim(), ssh_password: sshPassword, ssh_host: sshHost.trim() || null },
        f,
        (p) => setUploadPct(p),
      );
      setQuartusPath(res.path);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function start() {
    if (!shuttle) return;
    setStarting(true);
    try {
      const board_uart: Record<string, { host: string; port: number }> = {};
      for (const b of boards) {
        const u = uart[b];
        if (u && u.host.trim()) {
          board_uart[b] = { host: u.host.trim(), port: Number(u.port) || 20000 };
        }
      }
      const payload: ProvisionRequest = {
        ssh_user: sshUser.trim(),
        ssh_password: sshPassword,
        ssh_host: sshHost.trim() || null,
        boards,
        device_map: {
          usb_blaster: usbBlaster.trim(),
          magewell: magewell.trim(),
          video0: video0.trim(),
          video1: video1.trim(),
          arty_usb_bus: artyUsbBus.trim(),
        },
        board_uart,
        quartus_installer_path: quartusPath.trim(),
      };
      const started = await api.provisionShuttle(shuttle.id, payload);
      setStatus(null);
      setJobId(started.job_id);
      setStep(3);
    } catch (err) {
      showError(err instanceof api.ApiError ? err.message : "Could not start provisioning");
    } finally {
      setStarting(false);
    }
  }

  const phase = status?.status ?? (jobId ? "pending" : "idle");
  const running = phase === "pending" || phase === "running";
  const finished = phase === "succeeded" || phase === "failed";

  function requestClose() {
    onClose();
    if (phase === "succeeded") onDone();
  }

  return (
    <Dialog open={shuttle !== null} onOpenChange={(o) => !o && requestClose()}>
      <DialogContent className="max-w-2xl">
        {shuttle && (
          <>
            <h2 className="text-lg font-semibold">Provision {shuttle.name}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Builds the lab and agent containers on this machine over SSH. Everything is pulled fresh — no image is copied.
            </p>

            <div className="mt-3 flex gap-2 text-xs">
              {["SSH access", "Hardware", "Install"].map((label, i) => (
                <span
                  key={label}
                  className={
                    "rounded-full px-2 py-0.5 " +
                    (step === i + 1
                      ? "bg-primary text-primary-foreground"
                      : step > i + 1
                        ? "bg-muted text-foreground"
                        : "bg-muted text-muted-foreground")
                  }
                >
                  {i + 1}. {label}
                </span>
              ))}
            </div>

            {step === 1 && (
              <div className="mt-4 space-y-3">
                <p className="text-sm text-muted-foreground">
                  The machine must already run Proxmox VE and be reachable over SSH. These credentials are used only for
                  this run and are never stored.
                </p>
                <div>
                  <Label htmlFor="prov-host">Address (SSH)</Label>
                  <Input id="prov-host" value={sshHost} onChange={(e) => setSshHost(e.target.value)} placeholder="10.30.70.13" />
                </div>
                <div className="flex gap-2">
                  <div className="grow">
                    <Label htmlFor="prov-user">SSH user</Label>
                    <Input id="prov-user" value={sshUser} onChange={(e) => setSshUser(e.target.value)} placeholder="root" />
                  </div>
                  <div className="grow">
                    <Label htmlFor="prov-pass">SSH password</Label>
                    <Input id="prov-pass" type="password" value={sshPassword} onChange={(e) => setSshPassword(e.target.value)} />
                  </div>
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="secondary" onClick={requestClose}>
                    Cancel
                  </Button>
                  <Button disabled={!sshUser.trim() || !sshPassword || !sshHost.trim()} onClick={() => setStep(2)}>
                    Next
                  </Button>
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="mt-4 space-y-4">
                <div>
                  <Label>Boards attached to this shuttle</Label>
                  <div className="mt-1 grid grid-cols-2 gap-2">
                    {PROV_BOARDS.map((b) => (
                      <label key={b.value} className="flex items-center gap-2 rounded-md border p-2 text-sm">
                        <input type="checkbox" checked={boards.includes(b.value)} onChange={() => toggleBoard(b.value)} />
                        {b.label}
                      </label>
                    ))}
                  </div>
                </div>

                {boards.length > 0 && (
                  <div className="space-y-2">
                    <Label>Board UART bridge (host : port)</Label>
                    {boards.map((b) => (
                      <div key={b} className="flex items-center gap-2">
                        <span className="w-12 font-mono text-xs">{b}</span>
                        <Input value={uart[b]?.host ?? ""} onChange={(e) => setUartField(b, "host", e.target.value)} placeholder="10.30.70.50" />
                        <Input className="w-24" value={uart[b]?.port ?? "20000"} onChange={(e) => setUartField(b, "port", e.target.value)} placeholder="20000" />
                      </div>
                    ))}
                  </div>
                )}

                {needsQuartus && (
                  <div className="space-y-2 rounded-md border p-3">
                    <p className="text-xs text-muted-foreground">
                      Intel/Altera device paths — prefer stable udev symlinks over raw bus paths, which renumber on replug.
                    </p>
                    <LabeledInput label="USB-Blaster" value={usbBlaster} onChange={setUsbBlaster} />
                    <LabeledInput label="Magewell capture" value={magewell} onChange={setMagewell} />
                    <div className="flex gap-2">
                      <LabeledInput label="video0" value={video0} onChange={setVideo0} />
                      <LabeledInput label="video1" value={video1} onChange={setVideo1} />
                    </div>
                    <div className="space-y-2">
                      <Label>Quartus installer</Label>
                      <div className="flex gap-4 text-xs">
                        <label className="flex items-center gap-1">
                          <input type="radio" checked={installerMode === "upload"} onChange={() => setInstallerMode("upload")} />
                          Upload from this computer
                        </label>
                        <label className="flex items-center gap-1">
                          <input type="radio" checked={installerMode === "path"} onChange={() => setInstallerMode("path")} />
                          Already on the shuttle
                        </label>
                      </div>
                      {installerMode === "upload" ? (
                        <div className="space-y-1">
                          <input
                            type="file"
                            accept=".run"
                            disabled={uploading || !sshPassword}
                            onChange={(e) => handleInstallerPick(e.target.files?.[0] ?? null)}
                            className="block w-full text-xs file:mr-3 file:rounded-md file:border file:bg-muted file:px-3 file:py-1 file:text-xs"
                          />
                          {!sshPassword && (
                            <p className="text-xs text-warning-muted-foreground">Enter the SSH password in step 1 first.</p>
                          )}
                          {uploading && (
                            <p className="text-xs text-muted-foreground">
                              {uploadPct < 100 ? `Uploading to the portal… ${uploadPct}%` : "Transferring to the shuttle…"}
                            </p>
                          )}
                          {quartusPath && !uploading && (
                            <p className="text-xs text-muted-foreground">
                              ✓ On the shuttle at <code className="font-mono">{quartusPath}</code>
                            </p>
                          )}
                        </div>
                      ) : (
                        <Input value={quartusPath} onChange={(e) => setQuartusPath(e.target.value)} placeholder="/root/QuartusProgrammerSetup-25.1std.run" />
                      )}
                      <p className="text-xs text-muted-foreground">
                        Intel gates the download behind an account — either upload your licensed installer from your
                        machine, or place it on the shuttle and give its path.
                      </p>
                    </div>
                  </div>
                )}

                {artySelected && <LabeledInput label="Arty USB bus" value={artyUsbBus} onChange={setArtyUsbBus} />}

                <div className="flex justify-between gap-2 pt-2">
                  <Button variant="secondary" onClick={() => setStep(1)}>
                    Back
                  </Button>
                  <Button disabled={boards.length === 0 || (needsQuartus && !quartusPath.trim()) || starting} onClick={start}>
                    {starting ? "Starting…" : "Start provisioning"}
                  </Button>
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="mt-4 space-y-3">
                <div className="flex items-center gap-2 text-sm">
                  <StatusBadge status={phase === "succeeded" ? "online" : phase === "failed" ? "offline" : "never_reported"} />
                  <span className="text-muted-foreground">
                    {running && "Provisioning… a first run can take several minutes."}
                    {phase === "succeeded" && "Done. The agent should report within a minute."}
                    {phase === "failed" && `Failed (exit ${status?.returncode ?? "?"}). See the log below.`}
                  </span>
                </div>
                <pre className="max-h-80 overflow-auto rounded-md border bg-muted p-3 font-mono text-[11px] leading-relaxed">
                  {(status?.log ?? []).join("\n") || "Starting…"}
                </pre>
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" onClick={requestClose} disabled={running}>
                    {running ? "Running…" : finished ? "Close" : "Cancel"}
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

