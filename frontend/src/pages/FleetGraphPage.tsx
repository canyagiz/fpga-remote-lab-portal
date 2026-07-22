import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import * as api from "../api/client";
import { Board, Deployment, Device, GapReport, Shuttle } from "../api/types";
import { useToast } from "../context/ToastContext";

/* ------------------------------------------------------------------ *
 *  Fleet topology as a real node-edge graph.
 *
 *  HTML nodes over an SVG edge layer - the same technique the graph
 *  libraries use, which is the actual reason they look good, done here
 *  with no dependency (React Flow alone pulls 85 packages). Nodes are
 *  real DOM, so they get proper type, padding and truncation; edges are
 *  SVG underneath. Both share one pan/zoom transform.
 *
 *  Two levels, entered by clicking a shuttle. The shuttle level is a
 *  mesh, not a tree: a USB device is wired to the shuttle it plugs into
 *  AND to the board it serves, so it carries both edges.
 * ------------------------------------------------------------------ */

const FAMILY_LABELS: Record<string, string> = {
  cyclone_iv: "Cyclone IV",
  cyclone_v: "Cyclone V",
  cyclone_10: "Cyclone 10",
  zynq_7020: "Zynq-7020",
};

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

type NodeState = "ok" | "warn" | "bad" | "neutral";
type NodeKind = "portal" | "shuttle" | "board" | "device" | "gpio" | "loose";

interface InfoRow {
  k: string;
  v: string;
}
interface GNode {
  id: string;
  kind: NodeKind;
  title: string;
  sub: string;
  chip?: string;
  badge?: { text: string; state: NodeState };
  state: NodeState;
  x: number;
  y: number;
  drillShuttleId?: number;
  info: { title: string; rows: InfoRow[] };
}
interface GEdge {
  id: string;
  from: string;
  to: string;
  label: string;
  dashed?: boolean;
  state: NodeState;
  info: { title: string; rows: InfoRow[] };
}
interface Built {
  nodes: GNode[];
  edges: GEdge[];
}

const SIZES: Record<NodeKind, { w: number; h: number; round?: boolean }> = {
  portal: { w: 96, h: 96, round: true },
  shuttle: { w: 108, h: 108, round: true },
  board: { w: 200, h: 66 },
  device: { w: 190, h: 60 },
  gpio: { w: 190, h: 60 },
  loose: { w: 190, h: 60 },
};

function stateColor(state: NodeState): string {
  switch (state) {
    case "ok":
      return "var(--success)";
    case "warn":
      return "var(--warning)";
    case "bad":
      return "var(--destructive)";
    default:
      return "var(--border)";
  }
}

function ring(cx: number, cy: number, count: number, radius: number, start = -Math.PI / 2) {
  if (count === 0) return [];
  return Array.from({ length: count }, (_, i) => {
    const a = start + (i * 2 * Math.PI) / count;
    return { x: cx + radius * Math.cos(a), y: cy + radius * Math.sin(a), angle: a };
  });
}

type View = { mode: "fleet" } | { mode: "shuttle"; shuttleId: number };

function buildFleet(shuttles: Shuttle[], boards: Board[], devices: Device[]): Built {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];

  nodes.push({
    id: "portal",
    kind: "portal",
    title: "Portal",
    sub: "master · CT210",
    state: "neutral",
    x: 0,
    y: 0,
    info: {
      title: "Portal (master)",
      rows: [
        { k: "role", v: "control plane" },
        { k: "shuttles", v: String(shuttles.length) },
      ],
    },
  });

  const pos = ring(0, 0, shuttles.length, Math.max(260, shuttles.length * 90));
  shuttles.forEach((s, i) => {
    const state: NodeState = s.status === "online" ? "ok" : s.status === "offline" ? "bad" : "neutral";
    nodes.push({
      id: `shuttle-${s.id}`,
      kind: "shuttle",
      title: s.name,
      sub: "open →",
      state,
      x: pos[i].x,
      y: pos[i].y,
      drillShuttleId: s.id,
      info: {
        title: s.name,
        rows: [
          { k: "status", v: s.status },
          { k: "address", v: s.address ?? "not set" },
          { k: "agent", v: s.agent_version ?? "—" },
          { k: "last report", v: formatWhen(s.last_report_at) },
          { k: "boards", v: String(boards.filter((b) => b.shuttle_id === s.id).length) },
          { k: "devices", v: String(devices.filter((d) => d.shuttle_id === s.id).length) },
        ],
      },
    });
    edges.push({
      id: `report-${s.id}`,
      from: `shuttle-${s.id}`,
      to: "portal",
      label: "reports",
      dashed: s.status !== "online",
      state,
      info: {
        title: `${s.name} → Portal`,
        rows: [
          { k: "link", v: "inventory reporting" },
          { k: "interval", v: "every 30s" },
          { k: "status", v: s.status },
          { k: "last report", v: formatWhen(s.last_report_at) },
        ],
      },
    });
  });
  return { nodes, edges };
}

function buildShuttle(
  shuttleId: number,
  shuttles: Shuttle[],
  boards: Board[],
  devices: Device[],
  deployments: Deployment[],
  gaps: GapReport[],
): Built {
  const shuttle = shuttles.find((s) => s.id === shuttleId);
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  if (!shuttle) return { nodes, edges };

  const myDevices = devices.filter((d) => d.shuttle_id === shuttleId);
  const myBoards = boards.filter((b) => b.shuttle_id === shuttleId);
  const bySerial = (serial: string | null) =>
    serial ? myDevices.find((d) => d.usb_serial === serial) : undefined;

  const shuttleNodeId = `shuttle-${shuttleId}`;
  nodes.push({
    id: shuttleNodeId,
    kind: "shuttle",
    title: shuttle.name,
    sub: shuttle.address ?? "no address",
    state: shuttle.status === "online" ? "ok" : shuttle.status === "offline" ? "bad" : "neutral",
    x: 0,
    y: 0,
    info: {
      title: shuttle.name,
      rows: [
        { k: "status", v: shuttle.status },
        { k: "address", v: shuttle.address ?? "not set" },
        { k: "boards", v: String(myBoards.length) },
      ],
    },
  });

  const R_BOARD = 340;
  const R_DEV = 185;
  const boardPos = ring(0, 0, myBoards.length, R_BOARD);

  myBoards.forEach((board, bi) => {
    const theta = boardPos[bi].angle;
    const gap = gaps.find(
      (g) =>
        g.shuttle_id === shuttleId &&
        g.results.some((r) => r.type === "fpga" && r.message.includes(board.label)),
    );
    const deployment = deployments.find((d) => d.board_id === board.id);
    const state: NodeState = gap ? (gap.deployable ? "ok" : "warn") : "neutral";
    const bid = `board-${board.id}`;
    nodes.push({
      id: bid,
      kind: "board",
      title: board.label,
      sub: deployment ? `serving ${deployment.lab_name}` : "not bound to a lab",
      chip: FAMILY_LABELS[board.family] ?? board.family,
      state,
      x: boardPos[bi].x,
      y: boardPos[bi].y,
      info: {
        title: board.label,
        rows: [
          { k: "family", v: FAMILY_LABELS[board.family] ?? board.family },
          {
            k: "readiness",
            v: gap ? (gap.deployable ? "ready" : `${gap.missing_count} unmet`) : "no template",
          },
          { k: "lab", v: deployment ? deployment.lab_name : "not bound" },
          { k: "serving", v: deployment ? (deployment.available ? "yes" : "withdrawn") : "—" },
        ],
      },
    });

    type Spec = {
      id: string;
      node: GNode;
      toShuttle: { label: string; dashed: boolean; state: NodeState; info: GEdge["info"] };
      toBoard: { label: string; dashed: boolean; state: NodeState; info: GEdge["info"] };
    };
    const specs: Spec[] = [];

    const prog = bySerial(board.programmer_serial);
    const isXilinx = board.family === "zynq_7020";
    specs.push({
      id: `prog-${board.id}`,
      node: {
        id: `prog-${board.id}`,
        kind: "device",
        title: prog ? describeDevice(prog.manufacturer, prog.product) : "Programmer",
        sub: board.programmer_serial,
        chip: "programmer",
        state: prog ? "ok" : "bad",
        x: 0,
        y: 0,
        info: {
          title: prog ? describeDevice(prog.manufacturer, prog.product) : "Programmer (not attached)",
          rows: prog
            ? [
                { k: "role", v: "JTAG programmer" },
                { k: "serial", v: prog.usb_serial ?? "—" },
                { k: "USB port", v: prog.sysfs_path },
                {
                  k: "JTAG chain",
                  v: prog.jtag_chain?.length
                    ? prog.jtag_chain.map((c) => c.idcode).join(" · ")
                    : "not probed",
                },
              ]
            : [{ k: "serial", v: board.programmer_serial }, { k: "state", v: "not reported" }],
        },
      },
      toShuttle: {
        label: prog ? `USB ${prog.sysfs_path}` : "USB",
        dashed: !prog,
        state: "neutral",
        info: {
          title: "USB connection",
          rows: [
            { k: "into", v: shuttle.name },
            { k: "port", v: prog?.sysfs_path ?? "—" },
          ],
        },
      },
      toBoard: {
        label: "JTAG",
        dashed: !prog,
        state: prog ? "neutral" : "bad",
        info: {
          title: "JTAG programming link",
          rows: [
            { k: "programs", v: board.label },
            { k: "tool", v: isXilinx ? "openFPGALoader" : "quartus_pgm" },
          ],
        },
      },
    });

    if (board.video_capture_serial) {
      const cap = bySerial(board.video_capture_serial);
      const sig = cap?.has_video_signal;
      specs.push({
        id: `cap-${board.id}`,
        node: {
          id: `cap-${board.id}`,
          kind: "device",
          title: cap ? describeDevice(cap.manufacturer, cap.product) : "Capture card",
          sub: board.video_capture_serial,
          chip: "capture",
          badge:
            sig === true
              ? { text: "signal", state: "ok" }
              : sig === false
                ? { text: "no signal", state: "bad" }
                : cap
                  ? { text: "signal unknown", state: "warn" }
                  : { text: "not attached", state: "bad" },
          state: !cap ? "bad" : sig === false ? "bad" : sig === true ? "ok" : "warn",
          x: 0,
          y: 0,
          info: {
            title: cap ? describeDevice(cap.manufacturer, cap.product) : "Capture card (not attached)",
            rows: [
              { k: "role", v: "HDMI capture" },
              { k: "serial", v: board.video_capture_serial },
              { k: "signal", v: sig === true ? "present" : sig === false ? "none" : "unknown" },
            ],
          },
        },
        toShuttle: {
          label: cap ? `USB ${cap.sysfs_path}` : "USB",
          dashed: !cap,
          state: "neutral",
          info: {
            title: "USB connection",
            rows: [
              { k: "into", v: shuttle.name },
              { k: "port", v: cap?.sysfs_path ?? "—" },
            ],
          },
        },
        toBoard: {
          label: "HDMI",
          dashed: !cap,
          state: sig === false ? "bad" : "neutral",
          info: {
            title: "HDMI capture link",
            rows: [
              { k: "captures", v: board.label },
              { k: "signal", v: sig === true ? "present" : sig === false ? "none" : "unknown" },
            ],
          },
        },
      });
    }

    if (board.gpio_endpoint) {
      specs.push({
        id: `gpio-${board.id}`,
        node: {
          id: `gpio-${board.id}`,
          kind: "gpio",
          title: "GPIO controller",
          sub: board.gpio_endpoint,
          chip: "network",
          state: "neutral",
          x: 0,
          y: 0,
          info: {
            title: "GPIO controller",
            rows: [
              { k: "endpoint", v: board.gpio_endpoint },
              { k: "drives", v: `${board.label} switches` },
              { k: "reached", v: "over the network, not USB" },
              { k: "verified", v: "no — assignment only" },
            ],
          },
        },
        toShuttle: {
          label: "network",
          dashed: true,
          state: "neutral",
          info: {
            title: "Network reach",
            rows: [
              { k: "from", v: shuttle.name },
              { k: "endpoint", v: board.gpio_endpoint },
              { k: "note", v: "not discovered — recorded by a person" },
            ],
          },
        },
        toBoard: {
          label: "switches",
          dashed: true,
          state: "neutral",
          info: {
            title: "Drives the board's switches",
            rows: [
              { k: "board", v: board.label },
              { k: "endpoint", v: board.gpio_endpoint },
            ],
          },
        },
      });
    }

    const spread = Math.min(0.9, 0.34 * specs.length);
    specs.forEach((spec, i) => {
      const frac = specs.length === 1 ? 0 : i / (specs.length - 1) - 0.5;
      const a = theta + frac * spread;
      spec.node.x = R_DEV * Math.cos(a);
      spec.node.y = R_DEV * Math.sin(a);
      nodes.push(spec.node);
      edges.push({
        id: `e-${spec.id}-shuttle`,
        from: spec.id,
        to: shuttleNodeId,
        label: spec.toShuttle.label,
        dashed: spec.toShuttle.dashed,
        state: spec.toShuttle.state,
        info: spec.toShuttle.info,
      });
      edges.push({
        id: `e-${spec.id}-board`,
        from: spec.id,
        to: bid,
        label: spec.toBoard.label,
        dashed: spec.toBoard.dashed,
        state: spec.toBoard.state,
        info: spec.toBoard.info,
      });
    });
  });

  const claimed = new Set<string>();
  myBoards.forEach((b) => {
    claimed.add(b.programmer_serial);
    if (b.video_capture_serial) claimed.add(b.video_capture_serial);
  });
  const loose = myDevices.filter((d) => !d.usb_serial || !claimed.has(d.usb_serial));
  const loosePos = ring(0, 0, loose.length, R_DEV, Math.PI / 2);
  loose.forEach((d, i) => {
    const id = `loose-${d.id}`;
    nodes.push({
      id,
      kind: "loose",
      title: describeDevice(d.manufacturer, d.product),
      sub: d.usb_serial ?? d.sysfs_path,
      chip: d.kind.replace("_", " "),
      state: "warn",
      x: loosePos[i].x,
      y: loosePos[i].y,
      info: {
        title: describeDevice(d.manufacturer, d.product),
        rows: [
          { k: "role", v: d.kind.replace("_", " ") },
          { k: "serial", v: d.usb_serial ?? "none" },
          { k: "claimed", v: "no board claims this yet" },
        ],
      },
    });
    edges.push({
      id: `e-loose-${d.id}`,
      from: id,
      to: shuttleNodeId,
      label: `USB ${d.sysfs_path}`,
      dashed: true,
      state: "warn",
      info: { title: "Unclaimed device", rows: [{ k: "serial", v: d.usb_serial ?? "none" }] },
    });
  });

  return { nodes, edges };
}

function anchor(node: GNode, x: number, y: number, towardX: number, towardY: number) {
  const dx = towardX - x;
  const dy = towardY - y;
  const len = Math.hypot(dx, dy) || 1;
  const size = SIZES[node.kind];
  if (size.round) {
    const r = size.w / 2;
    return { x: x + (dx / len) * r, y: y + (dy / len) * r };
  }
  const hw = size.w / 2 + 2;
  const hh = size.h / 2 + 2;
  const scale = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh);
  return { x: x + dx * scale, y: y + dy * scale };
}

export default function FleetGraphPage() {
  const { showError } = useToast();
  const [shuttles, setShuttles] = useState<Shuttle[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [boards, setBoards] = useState<Board[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [gaps, setGaps] = useState<GapReport[]>([]);

  const [view, setView] = useState<View>({ mode: "fleet" });
  const [selected, setSelected] = useState<{ kind: "node" | "edge"; id: string } | null>(null);
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, { x: number; y: number }>>({});
  const [isFull, setIsFull] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 900, h: 560 });
  const [pan, setPan] = useState({ x: 450, y: 280 });
  const [zoom, setZoom] = useState(1);

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
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, []);

  useLayoutEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      setSize({ w: r.width, h: r.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const h = () => setIsFull(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", h);
    return () => document.removeEventListener("fullscreenchange", h);
  }, []);

  const built = useMemo<Built>(() => {
    if (view.mode === "fleet") return buildFleet(shuttles, boards, devices);
    return buildShuttle(view.shuttleId, shuttles, boards, devices, deployments, gaps);
  }, [view, shuttles, boards, devices, deployments, gaps]);

  const nodePos = useMemo(() => {
    const m: Record<string, { x: number; y: number }> = {};
    built.nodes.forEach((n) => (m[n.id] = overrides[n.id] ?? { x: n.x, y: n.y }));
    return m;
  }, [built, overrides]);

  const fitView = useCallback(() => {
    if (built.nodes.length === 0 || size.w < 10) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    built.nodes.forEach((n) => {
      const p = overrides[n.id] ?? { x: n.x, y: n.y };
      const s = SIZES[n.kind];
      minX = Math.min(minX, p.x - s.w / 2);
      minY = Math.min(minY, p.y - s.h / 2);
      maxX = Math.max(maxX, p.x + s.w / 2);
      maxY = Math.max(maxY, p.y + s.h / 2);
    });
    const pad = 56;
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    const z = Math.min(1.4, Math.max(0.35, Math.min((size.w - 2 * pad) / bw, (size.h - 2 * pad) / bh)));
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setZoom(z);
    setPan({ x: size.w / 2 - cx * z, y: size.h / 2 - cy * z });
  }, [built.nodes, overrides, size]);

  const structureKey =
    (view.mode === "fleet" ? "fleet" : `s${view.shuttleId}`) +
    "|" +
    built.nodes.map((n) => n.id).join(",");
  const fittedRef = useRef("");
  useEffect(() => {
    const key = `${structureKey}@${Math.round(size.w)}x${Math.round(size.h)}`;
    if (fittedRef.current === key || built.nodes.length === 0 || size.w < 10) return;
    fittedRef.current = key;
    setSelected(null);
    fitView();
  }, [structureKey, size.w, size.h]); // eslint-disable-line react-hooks/exhaustive-deps

  const drag = useRef<
    | { kind: "node"; id: string; offX: number; offY: number; moved: boolean }
    | { kind: "pan"; startX: number; startY: number; panX: number; panY: number; moved: boolean }
    | null
  >(null);

  function toWorld(clientX: number, clientY: number) {
    const r = canvasRef.current!.getBoundingClientRect();
    return { x: (clientX - r.left - pan.x) / zoom, y: (clientY - r.top - pan.y) / zoom };
  }

  function onNodePointerDown(e: React.PointerEvent, n: GNode) {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const w = toWorld(e.clientX, e.clientY);
    const p = nodePos[n.id];
    drag.current = { kind: "node", id: n.id, offX: w.x - p.x, offY: w.y - p.y, moved: false };
  }

  function onCanvasPointerDown(e: React.PointerEvent) {
    canvasRef.current?.setPointerCapture(e.pointerId);
    drag.current = {
      kind: "pan",
      startX: e.clientX,
      startY: e.clientY,
      panX: pan.x,
      panY: pan.y,
      moved: false,
    };
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) return;
    if (d.kind === "node") {
      d.moved = true;
      const w = toWorld(e.clientX, e.clientY);
      setOverrides((o) => ({ ...o, [d.id]: { x: w.x - d.offX, y: w.y - d.offY } }));
    } else {
      const dx = e.clientX - d.startX;
      const dy = e.clientY - d.startY;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      setPan({ x: d.panX + dx, y: d.panY + dy });
    }
  }

  function onNodePointerUp(n: GNode) {
    const d = drag.current;
    drag.current = null;
    if (!d || d.kind !== "node" || d.moved) return;
    if (view.mode === "fleet" && n.drillShuttleId != null) {
      setView({ mode: "shuttle", shuttleId: n.drillShuttleId });
    } else {
      setSelected({ kind: "node", id: n.id });
    }
  }

  function onCanvasPointerUp() {
    const d = drag.current;
    drag.current = null;
    if (d?.kind === "pan" && !d.moved) setSelected(null);
  }

  function onWheel(e: React.WheelEvent) {
    const r = canvasRef.current!.getBoundingClientRect();
    const cx = e.clientX - r.left;
    const cy = e.clientY - r.top;
    const wx = (cx - pan.x) / zoom;
    const wy = (cy - pan.y) / zoom;
    const next = Math.min(2.2, Math.max(0.35, zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    setPan({ x: cx - wx * next, y: cy - wy * next });
    setZoom(next);
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) containerRef.current?.requestFullscreen();
    else document.exitFullscreen();
  }

  const selectedShuttle =
    view.mode === "shuttle" ? shuttles.find((s) => s.id === view.shuttleId) : undefined;
  const panel = selected
    ? selected.kind === "node"
      ? built.nodes.find((n) => n.id === selected.id)?.info
      : built.edges.find((e) => e.id === selected.id)?.info
    : undefined;

  const transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <button
              className={view.mode === "fleet" ? "font-medium text-foreground" : "hover:text-foreground"}
              onClick={() => setView({ mode: "fleet" })}
            >
              Fleet
            </button>
            {view.mode === "shuttle" && (
              <>
                <span>/</span>
                <span className="font-medium text-foreground">{selectedShuttle?.name}</span>
              </>
            )}
          </div>
          <h1 className="mt-0.5 text-2xl font-bold tracking-tight">Fleet topology</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {view.mode === "fleet"
              ? "Click a shuttle to open it. Drag nodes, drag the canvas to pan, scroll to zoom."
              : "Each device is wired to the shuttle it plugs into and the board it serves. Hover an edge for what it is; click it for details."}
          </p>
        </div>
        <Link to="/admin/fleet" className="text-sm font-medium text-muted-foreground hover:text-foreground">
          Table view →
        </Link>
      </div>

      <div ref={containerRef} className="relative mt-5 overflow-hidden rounded-xl border bg-background">
        <div className="absolute left-3 top-3 z-20 flex items-center gap-1.5">
          {view.mode === "shuttle" && (
            <Button size="sm" variant="secondary" onClick={() => setView({ mode: "fleet" })}>
              ← Fleet
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={fitView}>
            Fit
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setOverrides({});
              fittedRef.current = "";
              setTimeout(fitView, 0);
            }}
          >
            Reset
          </Button>
          <Button size="sm" variant="secondary" onClick={toggleFullscreen}>
            {isFull ? "Exit full screen" : "Full screen"}
          </Button>
        </div>

        <div
          ref={canvasRef}
          className={`relative w-full touch-none select-none ${isFull ? "h-screen" : "h-[64vh]"}`}
          style={{
            cursor: drag.current?.kind === "pan" ? "grabbing" : "grab",
            backgroundImage: "radial-gradient(var(--border) 1px, transparent 1px)",
            backgroundSize: `${26 * zoom}px ${26 * zoom}px`,
            backgroundPosition: `${pan.x}px ${pan.y}px`,
          }}
          onPointerDown={onCanvasPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onCanvasPointerUp}
          onWheel={onWheel}
        >
          <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible">
            <g style={{ transform, transformOrigin: "0 0" }}>
              {built.edges.map((e) => {
                const a = built.nodes.find((n) => n.id === e.from);
                const b = built.nodes.find((n) => n.id === e.to);
                if (!a || !b) return null;
                const pa0 = nodePos[a.id];
                const pb0 = nodePos[b.id];
                const pa = anchor(a, pa0.x, pa0.y, pb0.x, pb0.y);
                const pb = anchor(b, pb0.x, pb0.y, pa0.x, pa0.y);
                const isSel = selected?.kind === "edge" && selected.id === e.id;
                const isHover = hoverEdge === e.id;
                const color = isSel ? "var(--primary)" : stateColor(e.state);
                const mx = (pa.x + pb.x) / 2;
                const my = (pa.y + pb.y) / 2;
                return (
                  <g key={e.id}>
                    <line
                      x1={pa.x}
                      y1={pa.y}
                      x2={pb.x}
                      y2={pb.y}
                      stroke="transparent"
                      strokeWidth={18}
                      className="pointer-events-auto cursor-pointer"
                      onPointerDown={(ev) => {
                        ev.stopPropagation();
                        setSelected({ kind: "edge", id: e.id });
                      }}
                      onPointerEnter={() => setHoverEdge(e.id)}
                      onPointerLeave={() => setHoverEdge((h) => (h === e.id ? null : h))}
                    />
                    <line
                      x1={pa.x}
                      y1={pa.y}
                      x2={pb.x}
                      y2={pb.y}
                      stroke={color}
                      strokeWidth={isSel || isHover ? 2.5 : 1.6}
                      strokeDasharray={e.dashed ? "6 5" : undefined}
                      strokeLinecap="round"
                      className="pointer-events-none"
                    />
                    {(isSel || isHover) && (
                      <g style={{ pointerEvents: "none" }}>
                        <rect
                          x={mx - e.label.length * 3.6 - 6}
                          y={my - 18}
                          width={e.label.length * 7.2 + 12}
                          height={17}
                          rx={5}
                          fill="var(--card)"
                          stroke="var(--border)"
                        />
                        <text x={mx} y={my - 6} textAnchor="middle" fontSize={11} fill="var(--foreground)">
                          {e.label}
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>

          <div className="absolute inset-0" style={{ transform, transformOrigin: "0 0" }}>
            {built.nodes.map((n) => {
              const p = nodePos[n.id];
              const s = SIZES[n.kind];
              const isSel = selected?.kind === "node" && selected.id === n.id;
              const color = stateColor(n.state);
              const drillable = view.mode === "fleet" && n.drillShuttleId != null;
              const round = s.round;
              const dashed = n.kind === "gpio" || n.kind === "loose";
              return (
                <div
                  key={n.id}
                  className="absolute flex flex-col justify-center"
                  style={{
                    left: p.x,
                    top: p.y,
                    width: s.w,
                    height: s.h,
                    transform: "translate(-50%, -50%)",
                    cursor: "pointer",
                    borderRadius: round ? 9999 : 12,
                    background: "var(--card)",
                    border: `${n.kind === "board" || round ? 2.5 : 1.5}px ${dashed ? "dashed" : "solid"} ${
                      round && n.kind === "portal" ? "var(--primary)" : color
                    }`,
                    boxShadow: isSel
                      ? "0 0 0 3px color-mix(in srgb, var(--primary) 55%, transparent)"
                      : "0 1px 2px rgba(0,0,0,.05)",
                    padding: round ? 0 : "8px 12px 8px 14px",
                    alignItems: round ? "center" : "stretch",
                    textAlign: round ? "center" : "left",
                    overflow: "hidden",
                  }}
                  onPointerDown={(e) => onNodePointerDown(e, n)}
                  onPointerUp={() => onNodePointerUp(n)}
                >
                  {!round && (
                    <span
                      className="absolute left-0 top-0 h-full"
                      style={{ width: 5, background: color, borderTopLeftRadius: 12, borderBottomLeftRadius: 12 }}
                    />
                  )}
                  <div className="flex items-center gap-1.5" style={{ minWidth: 0 }}>
                    <span className="truncate font-semibold text-foreground" style={{ fontSize: round ? 13 : 12.5 }}>
                      {n.title}
                    </span>
                    {n.chip && !round && (
                      <span
                        className="shrink-0 rounded-full px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide"
                        style={{ background: "var(--muted)", color: "var(--muted-foreground)" }}
                      >
                        {n.chip}
                      </span>
                    )}
                  </div>
                  <div
                    className="truncate"
                    style={{
                      fontSize: round ? 10 : 10.5,
                      color: drillable ? "var(--primary)" : "var(--muted-foreground)",
                      fontFamily:
                        n.kind === "device" || n.kind === "gpio" || n.kind === "loose"
                          ? "var(--font-mono, monospace)"
                          : undefined,
                    }}
                  >
                    {n.sub}
                  </div>
                  {n.badge && !round && (
                    <span
                      className="mt-0.5 w-fit rounded px-1.5 py-px text-[9px] font-semibold"
                      style={{
                        color: stateColor(n.badge.state),
                        border: `1px solid color-mix(in srgb, ${stateColor(n.badge.state)} 40%, var(--border))`,
                      }}
                    >
                      {n.badge.text}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {built.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <p className="text-sm text-muted-foreground">
                {shuttles.length === 0 ? "No shuttles enrolled yet." : "Nothing to show."}
              </p>
            </div>
          )}
        </div>

        {panel && (
          <div className="absolute right-3 top-3 z-20 w-64 rounded-lg border bg-card/95 p-3 shadow-lg backdrop-blur">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-semibold">{panel.title}</p>
              <button
                className="text-muted-foreground hover:text-foreground"
                onClick={() => setSelected(null)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <dl className="mt-2 space-y-1">
              {panel.rows.map((row, i) => (
                <div key={i} className="flex justify-between gap-3 text-xs">
                  <dt className="text-muted-foreground">{row.k}</dt>
                  <dd className="text-right font-medium">{row.v}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--success)" }} /> ok
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--warning)" }} /> needs
          attention
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--destructive)" }} /> fault
        </span>
        <span>solid: seen over USB · dashed: recorded / over the network</span>
      </div>
    </div>
  );
}
