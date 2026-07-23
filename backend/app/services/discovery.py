"""Network discovery - a "scan the LAN" for the fleet.

The agents already report what is plugged into a shuttle over USB. This
answers a different question: what is reachable on the lab network that
isn't a USB device at all - the Raspberry Pis that drive the boards'
switches, other shuttles, and any host worth knowing about before you
wire something up.

It is a plain TCP connect scan of the portal's own /24, plus a read of
the ARP table for vendor identification. Deliberately modest:

  * Admin-only (see the router), read-only, on the internal lab subnet.
  * A normal connect() then immediate close - no payload is ever sent,
    so probing a Pi's io_interface port cannot trigger any board action.
  * Bounded concurrency and a short timeout, so a full sweep is a few
    seconds and cannot flood the network.

Nothing here writes to the database or changes any state.
"""

from __future__ import annotations

import asyncio
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field

# The ports that actually tell us something on this network.
#   20000  the Raspberry Pi io_interface (GPIO / UART bridge)
#   22     ssh - a general "this is a real host" signal
#   8006   Proxmox VE - identifies a virtualisation host
#   8000   the portal itself
SCAN_PORTS = (20000, 22, 8006, 8000)
CONNECT_TIMEOUT = 0.6
CONCURRENCY = 96

# MAC prefixes (OUIs), lower-case no separators. Raspberry Pi has used
# several as it changed legal entity across board generations.
_PI_OUIS = {"b827eb", "dca632", "e45f01", "28cdc1", "d83add", "2ccf67"}
# Proxmox assigns container/VM NICs from this range on this host.
_PROXMOX_OUIS = {"bc2411"}


@dataclass
class DiscoveredHost:
    ip: str
    mac: str | None
    vendor: str
    kind: str  # "raspberry_pi" | "proxmox" | "host"
    open_ports: list[int] = field(default_factory=list)
    # A human-facing note tying this back to what we already know - "GPIO
    # for Cyclone IV", "enrolled shuttle", "this portal".
    note: str | None = None


@dataclass
class ScanResult:
    subnet: str
    duration_ms: int
    hosts: list[DiscoveredHost]


def _own_ip() -> str | None:
    """The portal's own address on the lab network. Derived from the
    outbound interface rather than hardcoded, so this still works if the
    portal is renumbered."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.30.70.1", 1))  # no packet is sent for UDP connect
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _arp_table() -> dict[str, str]:
    """ip -> mac for every neighbour the kernel currently knows. A
    connect attempt to a live host populates this even when the port is
    closed, so it doubles as the "which hosts are up" signal."""
    try:
        out = subprocess.run(
            ["ip", "neigh", "show"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    table: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if "lladdr" not in parts or "FAILED" in parts or "INCOMPLETE" in parts:
            continue
        ip = parts[0]
        mac = parts[parts.index("lladdr") + 1]
        if re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", mac, re.I):
            table[ip] = mac.lower()
    return table


def parse_endpoint(endpoint: str) -> tuple[str, int] | None:
    """Split "10.30.70.50:20000" into (host, port), or None if malformed."""
    endpoint = (endpoint or "").strip()
    if ":" not in endpoint:
        return None
    host, _, port = endpoint.rpartition(":")
    if not host:
        return None
    try:
        return host, int(port)
    except ValueError:
        return None


def is_reachable(host: str, port: int, timeout: float = CONNECT_TIMEOUT) -> bool:
    """A single synchronous connect - "is this actually on the network
    right now". Used to refuse binding a board to a controller that is
    not reachable, so a typo or an unplugged Pi is caught at the point of
    entry rather than surfacing later as a mysteriously broken lab."""
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


async def _probe(ip: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), CONNECT_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError):
        return False
    # Close immediately without sending anything - the Pi's io_interface
    # gets an empty read and loops; no command, no board action.
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 0.5)
    except (OSError, asyncio.TimeoutError):
        pass
    return True


async def _scan_host(ip: str) -> tuple[str, list[int]]:
    results = await asyncio.gather(*(_probe(ip, p) for p in SCAN_PORTS))
    return ip, [p for p, ok in zip(SCAN_PORTS, results) if ok]


async def _scan_subnet(base: str) -> dict[str, list[int]]:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bound(ip: str) -> tuple[str, list[int]]:
        async with sem:
            return await _scan_host(ip)

    hosts = [f"{base}.{i}" for i in range(1, 255)]
    pairs = await asyncio.gather(*(bound(h) for h in hosts))
    return {ip: ports for ip, ports in pairs if ports}


def _oui(mac: str | None) -> str | None:
    if not mac:
        return None
    return mac.replace(":", "")[:6].lower()


def _classify(mac: str | None, open_ports: list[int]) -> tuple[str, str]:
    """Returns (kind, vendor-label). A Pi that also answers on 20000 is
    still a Pi - the GPIO role is added to the note, not the kind."""
    oui = _oui(mac)
    if oui in _PI_OUIS:
        return "raspberry_pi", "Raspberry Pi"
    if oui in _PROXMOX_OUIS:
        return "proxmox", "Proxmox VM / container"
    if 20000 in open_ports:
        # Answers on the io_interface port but isn't a recognised Pi MAC -
        # still worth flagging as a probable controller.
        return "raspberry_pi", "GPIO controller (unrecognised MAC)"
    if 8006 in open_ports:
        return "proxmox", "Proxmox host"
    return "host", "Host"


def scan(
    known_shuttle_addresses: dict[str, str],
    known_gpio_endpoints: dict[str, str],
) -> ScanResult:
    """Run one scan. The two dicts (ip -> label) let discovered hosts be
    annotated with what we already know, so the result is not just raw
    IPs - a Pi shows as "GPIO for Cyclone IV" rather than an anonymous
    address the admin has to recognise."""
    started = time.monotonic()
    portal_ip = _own_ip()
    if portal_ip is None or len(portal_ip.split(".")) != 4:
        return ScanResult(subnet="unknown", duration_ms=0, hosts=[])
    base = ".".join(portal_ip.split(".")[:3])

    open_by_ip = asyncio.run(_scan_subnet(base))
    arp = _arp_table()

    # A host is "present" if it answered a port OR resolved in ARP.
    ips = set(open_by_ip) | {ip for ip in arp if ip.startswith(base + ".")}
    hosts: list[DiscoveredHost] = []
    for ip in sorted(ips, key=lambda a: tuple(int(x) for x in a.split("."))):
        ports = sorted(open_by_ip.get(ip, []))
        mac = arp.get(ip)
        kind, vendor = _classify(mac, ports)

        notes: list[str] = []
        if ip == portal_ip:
            notes.append("this portal")
        if ip in known_shuttle_addresses:
            notes.append(f"enrolled shuttle: {known_shuttle_addresses[ip]}")
        if ip in known_gpio_endpoints:
            notes.append(f"GPIO for {known_gpio_endpoints[ip]}")
        elif 20000 in ports and kind == "raspberry_pi":
            notes.append("io_interface open — usable as a GPIO endpoint")

        hosts.append(
            DiscoveredHost(
                ip=ip,
                mac=mac,
                vendor=vendor,
                kind=kind,
                open_ports=ports,
                note=" · ".join(notes) if notes else None,
            )
        )

    return ScanResult(
        subnet=f"{base}.0/24",
        duration_ms=int((time.monotonic() - started) * 1000),
        hosts=hosts,
    )
