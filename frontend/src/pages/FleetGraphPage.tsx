import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import * as api from "../api/client";
import { Board, Deployment, Device, GapReport, Shuttle } from "../api/types";
import { useToast } from "../context/ToastContext";

/* ------------------------------------------------------------------ *
 *  Fleet topology as a node-edge graph.
 *
 *  HTML nodes over an SVG edge layer - the technique the graph
 *  libraries use, done here with no dependency (React Flow alone pulls
 *  85 packages).
 *
 *  Layout is left-to-right and layered, not radial: the shuttle on the
 *  left, the devices plugged into it in the middle, the boards they
 *  serve on the right. Rows have a fixed height, so cards cannot
 *  collide the way a fan-on-a-circle let them. A device carries two
 *  edges - to the shuttle it plugs into and to the board it serves -
 *  which is the actual wiring, not a tree.
 *
 *  Colour is kept quiet: cards are neutral, and state shows as a small
 *  dot plus a coloured outline only when something is wrong. "Ready" is
 *  not meant to shout.
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
  bad?: boolean;
  info: { title: string; rows: InfoRow[] };
}
interface Built {
  nodes: GNode[];
  edges: GEdge[];
}

const SIZES: Record<NodeKind, { w: number; h: number }> = {
  portal: { w: 168, h: 78 },
  shuttle: { w: 168, h: 78 },
  board: { w: 208, h: 64 },
  device: { w: 196, h: 60 },
  gpio: { w: 196, h: 60 },
  loose: { w: 196, h: 60 },
};

const DOT: Record<NodeState, string> = {
  ok: "var(--success)",
  warn: "var(--warning)",
  bad: "var(--destructive)",
  neutral: "var(--muted-foreground)",
};

/** Border colour. Neutral unless something is wrong - "ready" should not
 *  paint the whole graph green. */
function borderColor(state: NodeState): string {
  if (state === "bad") return "var(--destructive)";
  if (state === "warn") return "var(--warning)";
  return "var(--border)";
}

type View = { mode: "fleet" } | { mode: "shuttle"; shuttleId: number };

// Column x-positions for the layered layout, and the fixed row height
// that keeps cards from ever overlapping.
const COL = { hub: 0, dev: 300, board: 620 };
const ROW_H = 88;
const rowY = (i: number, total: number) => (i - (total - 1) / 2) * ROW_H;

function buildFleet(shuttles: Shuttle[], boards: Board[], devices: Device[]): Built {
  const nodes: GNode[] = [];
  const edges: GEdge[] = [];
  const total = Math.max(shuttles.length, 1);

  nodes.push({
    id: "portal",
    kind: "portal",
    title: "Portal",
    sub: "master · CT210",
    state: "neutral",
    x: 360,
    y: 0,
    info: {
      title: "Portal (master)",
      rows: [
        { k: "role", v: "control plane" },
        { k: "shuttles", v: String(shuttles.length) },
      ],
    },
  });

  shuttles.forEach((s, i) => {
    const state: NodeState = s.status === "online" ? "ok" : s.status === "offline" ? "bad" : "neutral";
    nodes.push({
      id: `shuttle-${s.id}`,
      kind: "shuttle",
      title: s.name,
      sub: s.status === "online" ? "online · open →" : `${s.status} · open →`,
      state,
      x: 0,
      y: rowY(i, total),
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
      bad: s.status === "offline",
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

  // Build each board's block (board node + its device nodes + edges),
  // positions filled in the layout pass below.
  interface Block {
    boardNode: GNode;
    deviceNodes: GNode[];
  }
  const blocks: Block[] = [];

  myBoards.forEach((board) => {
    const gap = gaps.find(
      (g) =>
        g.shuttle_id === shuttleId &&
        g.results.some((r) => r.type === "fpga" && r.message.includes(board.label)),
    );
    const deployment = deployments.find((d) => d.board_id === board.id);
    const state: NodeState = gap ? (gap.deployable ? "ok" : "warn") : "neutral";
    const bid = `board-${board.id}`;
    const boardNode: GNode = {
      id: bid,
      kind: "board",
      title: board.label,
      sub: deployment ? `serving ${deployment.lab_name}` : "not bound to a lab",
      chip: FAMILY_LABELS[board.family] ?? board.family,
      state,
      x: 0,
      y: 0,
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
    };
    const deviceNodes: GNode[] = [];

    const prog = bySerial(board.programmer_serial);
    const isXilinx = board.family === "zynq_7020";
    const progId = `prog-${board.id}`;
    deviceNodes.push({
      id: progId,
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
                v: prog.jtag_chain?.length ? prog.jtag_chain.map((c) => c.idcode).join(" · ") : "not probed",
              },
            ]
          : [{ k: "serial", v: board.programmer_serial }, { k: "state", v: "not reported" }],
      },
    });
    edges.push({
      id: `e-${progId}-hub`,
      from: shuttleNodeId,
      to: progId,
      label: prog ? `USB ${prog.sysfs_path}` : "USB",
      dashed: !prog,
      info: {
        title: "USB connection",
        rows: [
          { k: "into", v: shuttle.name },
          { k: "port", v: prog?.sysfs_path ?? "—" },
        ],
      },
    });
    edges.push({
      id: `e-${progId}-board`,
      from: progId,
      to: bid,
      label: "JTAG",
      dashed: !prog,
      bad: !prog,
      info: {
        title: "JTAG programming link",
        rows: [
          { k: "programs", v: board.label },
          { k: "tool", v: isXilinx ? "openFPGALoader" : "quartus_pgm" },
        ],
      },
    });

    if (board.video_capture_serial) {
      const cap = bySerial(board.video_capture_serial);
      const sig = cap?.has_video_signal;
      const capId = `cap-${board.id}`;
      deviceNodes.push({
        id: capId,
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
                ? { text: "signal ?", state: "warn" }
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
      });
      edges.push({
        id: `e-${capId}-hub`,
        from: shuttleNodeId,
        to: capId,
        label: cap ? `USB ${cap.sysfs_path}` : "USB",
        dashed: !cap,
        info: {
          title: "USB connection",
          rows: [
            { k: "into", v: shuttle.name },
            { k: "port", v: cap?.sysfs_path ?? "—" },
          ],
        },
      });
      edges.push({
        id: `e-${capId}-board`,
        from: capId,
        to: bid,
        label: "HDMI",
        dashed: !cap,
        bad: sig === false,
        info: {
          title: "HDMI capture link",
          rows: [
            { k: "captures", v: board.label },
            { k: "signal", v: sig === true ? "present" : sig === false ? "none" : "unknown" },
          ],
        },
      });
    }

    if (board.gpio_endpoint) {
      const gpioId = `gpio-${board.id}`;
      deviceNodes.push({
        id: gpioId,
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
      });
      edges.push({
        id: `e-${gpioId}-hub`,
        from: shuttleNodeId,
        to: gpioId,
        label: "network",
        dashed: true,
        info: {
          title: "Network reach",
          rows: [
            { k: "from", v: shuttle.name },
            { k: "endpoint", v: board.gpio_endpoint },
            { k: "note", v: "not discovered — recorded by a person" },
          ],
        },
      });
      edges.push({
        id: `e-${gpioId}-board`,
        from: gpioId,
        to: bid,
        label: "switches",
        dashed: true,
        info: {
          title: "Drives the board's switches",
          rows: [
            { k: "board", v: board.label },
            { k: "endpoint", v: board.gpio_endpoint },
          ],
        },
      });
    }

    blocks.push({ boardNode, deviceNodes });
  });

  // Attached, claimed by no board.
  const claimed = new Set<string>();
  myBoards.forEach((b) => {
    claimed.add(b.programmer_serial);
    if (b.video_capture_serial) claimed.add(b.video_capture_serial);
  });
  const loose = myDevices.filter((d) => !d.usb_serial || !claimed.has(d.usb_serial));
  const looseNodes: GNode[] = loose.map((d) => {
    const id = `loose-${d.id}`;
    edges.push({
      id: `e-${id}-hub`,
      from: shuttleNodeId,
      to: id,
      label: `USB ${d.sysfs_path}`,
      dashed: true,
      info: { title: "Unclaimed device", rows: [{ k: "serial", v: d.usb_serial ?? "none" }] },
    });
    return {
      id,
      kind: "loose" as const,
      title: describeDevice(d.manufacturer, d.product),
      sub: d.usb_serial ?? d.sysfs_path,
      chip: d.kind.replace("_", " "),
      state: "warn" as NodeState,
      x: 0,
      y: 0,
      info: {
        title: describeDevice(d.manufacturer, d.product),
        rows: [
          { k: "role", v: d.kind.replace("_", " ") },
          { k: "serial", v: d.usb_serial ?? "none" },
          { k: "claimed", v: "no board claims this yet" },
        ],
      },
    };
  });

  // Layout: one row per device (and per loose device); each board sits
  // at the vertical centre of its own devices' rows.
  const totalRows = blocks.reduce((n, b) => n + Math.max(1, b.deviceNodes.length), 0) + looseNodes.length;
  let row = 0;
  blocks.forEach((block) => {
    const start = row;
    block.deviceNodes.forEach((dn) => {
      dn.x = COL.dev;
      dn.y = rowY(row, totalRows);
      nodes.push(dn);
      row++;
    });
    if (block.deviceNodes.length === 0) row++;
    const mid = (start + row - 1) / 2;
    block.boardNode.x = COL.board;
    block.boardNode.y = rowY(mid, totalRows);
    nodes.push(block.boardNode);
  });
  looseNodes.forEach((ln) => {
    ln.x = COL.dev;
    ln.y = rowY(row, totalRows);
    nodes.push(ln);
    row++;
  });

  const shuttleNode: GNode = {
    id: shuttleNodeId,
    kind: "shuttle",
    title: shuttle.name,
    sub: shuttle.address ?? "no address",
    state: shuttle.status === "online" ? "ok" : shuttle.status === "offline" ? "bad" : "neutral",
    x: COL.hub,
    y: 0,
    info: {
      title: shuttle.name,
      rows: [
        { k: "status", v: shuttle.status },
        { k: "address", v: shuttle.address ?? "not set" },
        { k: "boards", v: String(myBoards.length) },
      ],
    },
  };
  nodes.unshift(shuttleNode);

  return { nodes, edges };
}

function anchor(node: GNode, x: number, y: number, towardX: number, towardY: number) {
  const dx = towardX - x;
  const dy = towardY - y;
  const s = SIZES[node.kind];
  const hw = s.w / 2 + 2;
  const hh = s.h / 2 + 2;
  const scale = 1 / Math.max(Math.abs(dx) / hw, Math.abs(dy) / hh || 1e-6);
  return { x: x + dx * scale, y: y + dy * scale };
}

/* --- small inline icons: enough to say "machine" without a library --- */
function HostIcon({ color }: { color: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="7" rx="1.5" />
      <rect x="3" y="13" width="18" height="7" rx="1.5" />
      <circle cx="7" cy="7.5" r="0.9" fill={color} stroke="none" />
      <circle cx="7" cy="16.5" r="0.9" fill={color} stroke="none" />
    </svg>
  );
}
function MasterIcon({ color }: { color: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8">
      <circle cx="12" cy="12" r="2.4" fill={color} stroke="none" />
      <path d="M6.5 17.5a7 7 0 0 1 0-11M17.5 6.5a7 7 0 0 1 0 11" />
    </svg>
  );
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
  const [pan, setPan] = useState({ x: 300, y: 280 });
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
    const pad = 64;
    const bw = Math.max(maxX - minX, 1);
    const bh = Math.max(maxY - minY, 1);
    const z = Math.min(1.3, Math.max(0.4, Math.min((size.w - 2 * pad) / bw, (size.h - 2 * pad) / bh)));
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setZoom(z);
    setPan({ x: size.w / 2 - cx * z, y: size.h / 2 - cy * z });
  }, [built.nodes, overrides, size]);

  const structureKey =
    (view.mode === "fleet" ? "fleet" : `s${view.shuttleId}`) + "|" + built.nodes.map((n) => n.id).join(",");
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
    drag.current = { kind: "pan", startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y, moved: false };
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
    if (view.mode === "fleet" && n.drillShuttleId != null) setView({ mode: "shuttle", shuttleId: n.drillShuttleId });
    else setSelected({ kind: "node", id: n.id });
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

  const selectedShuttle = view.mode === "shuttle" ? shuttles.find((s) => s.id === view.shuttleId) : undefined;
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
              : "Shuttle on the left, the devices plugged into it in the middle, the boards they serve on the right. Hover an edge for what it is; click for details."}
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
            backgroundImage: "radial-gradient(color-mix(in srgb, var(--border) 70%, transparent) 1px, transparent 1px)",
            backgroundSize: `${24 * zoom}px ${24 * zoom}px`,
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
                const color = isSel || isHover ? "var(--primary)" : e.bad ? "var(--destructive)" : "var(--border)";
                // Smooth S-curve between columns - horizontal tangents, the
                // blueprint look, and it separates the two edges a device
                // has so they do not sit on top of each other.
                const cxo = Math.max(28, Math.abs(pb.x - pa.x) * 0.45);
                const dir = pb.x >= pa.x ? 1 : -1;
                const d = `M ${pa.x} ${pa.y} C ${pa.x + dir * cxo} ${pa.y}, ${pb.x - dir * cxo} ${pb.y}, ${pb.x} ${pb.y}`;
                const mx = (pa.x + pb.x) / 2;
                const my = (pa.y + pb.y) / 2;
                return (
                  <g key={e.id}>
                    <path
                      d={d}
                      fill="none"
                      stroke="transparent"
                      strokeWidth={16}
                      className="pointer-events-auto cursor-pointer"
                      onPointerDown={(ev) => {
                        ev.stopPropagation();
                        setSelected({ kind: "edge", id: e.id });
                      }}
                      onPointerEnter={() => setHoverEdge(e.id)}
                      onPointerLeave={() => setHoverEdge((h) => (h === e.id ? null : h))}
                    />
                    <path
                      d={d}
                      fill="none"
                      stroke={color}
                      strokeWidth={isSel || isHover ? 2.25 : 1.5}
                      strokeDasharray={e.dashed ? "6 5" : undefined}
                      strokeLinecap="round"
                      className="pointer-events-none"
                    />
                    {(isSel || isHover) && (
                      <g style={{ pointerEvents: "none" }}>
                        <rect
                          x={mx - e.label.length * 3.4 - 6}
                          y={my - 9}
                          width={e.label.length * 6.8 + 12}
                          height={17}
                          rx={5}
                          fill="var(--card)"
                          stroke="var(--border)"
                        />
                        <text x={mx} y={my + 3} textAnchor="middle" fontSize={10.5} fill="var(--foreground)">
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
              const hub = n.kind === "shuttle" || n.kind === "portal";
              const dashed = n.kind === "gpio" || n.kind === "loose";
              const drillable = view.mode === "fleet" && n.drillShuttleId != null;
              return (
                <div
                  key={n.id}
                  className="absolute flex items-center gap-2.5"
                  style={{
                    left: p.x,
                    top: p.y,
                    width: s.w,
                    height: s.h,
                    transform: "translate(-50%, -50%)",
                    cursor: "pointer",
                    borderRadius: 12,
                    background: hub ? "var(--muted)" : "var(--card)",
                    border: `${hub || n.kind === "board" ? 1.75 : 1.25}px ${dashed ? "dashed" : "solid"} ${
                      isSel ? "var(--primary)" : borderColor(n.state)
                    }`,
                    boxShadow: isSel
                      ? "0 0 0 3px color-mix(in srgb, var(--primary) 45%, transparent)"
                      : "0 1px 2px rgba(15,23,42,.06)",
                    padding: "0 12px",
                    overflow: "hidden",
                  }}
                  onPointerDown={(e) => onNodePointerDown(e, n)}
                  onPointerUp={() => onNodePointerUp(n)}
                >
                  {hub ? (
                    <span
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
                    >
                      {n.kind === "portal" ? (
                        <MasterIcon color="var(--primary)" />
                      ) : (
                        <HostIcon color="var(--foreground)" />
                      )}
                    </span>
                  ) : (
                    <span
                      className="mt-[3px] h-2 w-2 shrink-0 self-start rounded-full"
                      style={{ background: DOT[n.state] }}
                      title={n.state}
                    />
                  )}

                  <div className="min-w-0 flex-1">
                    {hub && (
                      <div
                        className="text-[9px] font-semibold uppercase tracking-[0.12em]"
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        {n.kind === "portal" ? "master" : "shuttle"}
                      </div>
                    )}
                    <div className="flex items-center gap-1.5">
                      <span
                        className="truncate font-semibold text-foreground"
                        style={{ fontSize: hub ? 14 : 12.5 }}
                      >
                        {n.title}
                      </span>
                      {n.chip && (
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
                        fontSize: 10.5,
                        color: drillable ? "var(--primary)" : "var(--muted-foreground)",
                        fontFamily:
                          n.kind === "device" || n.kind === "gpio" || n.kind === "loose"
                            ? "var(--font-mono, monospace)"
                            : undefined,
                      }}
                    >
                      {n.sub}
                    </div>
                  </div>

                  {n.badge && (
                    <span
                      className="shrink-0 self-start rounded px-1.5 py-px text-[9px] font-semibold"
                      style={{
                        color: DOT[n.badge.state],
                        border: `1px solid color-mix(in srgb, ${DOT[n.badge.state]} 40%, var(--border))`,
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
              <button className="text-muted-foreground hover:text-foreground" onClick={() => setSelected(null)} aria-label="Close">
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
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--warning)" }} /> needs attention
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--destructive)" }} /> fault
        </span>
        <span>solid: seen over USB · dashed: recorded / over the network</span>
      </div>
    </div>
  );
}
