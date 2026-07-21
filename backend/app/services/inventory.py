"""Turning an agent's report into the fleet's recorded state.

The master's job here is reconciliation, not storage: a report is the
complete truth about one shuttle at one moment, so ingesting it means
making the database agree with it - including recording what has
*stopped* being there.

Nothing in a report is trusted beyond its shape. A shuttle holds a
token, which proves which shuttle is speaking; it does not make the
contents true. The caps in schemas.AgentReport bound the damage a
compromised agent can do, and this module never lets a report create a
shuttle, grant anything, or touch a table other than its own devices.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, Shuttle
from app.schemas import AgentReport, SCHEMA_VERSION_SUPPORTED

# A node is considered online if it reported within this window. It has
# to be comfortably longer than the agent's own scan interval, or a
# single slow scan would flap the node offline and take its labs out of
# the catalogue for no reason.
OFFLINE_AFTER = timedelta(minutes=3)


def shuttle_status(shuttle: Shuttle, *, now: datetime | None = None) -> str:
    """Derived, never stored - storing it would mean a background job had
    to keep it fresh, and a stale 'online' is worse than none."""
    if shuttle.last_report_at is None:
        return "never_reported"
    now = now or datetime.utcnow()
    return "online" if now - shuttle.last_report_at <= OFFLINE_AFTER else "offline"


def _video_signal_by_serial(report: AgentReport) -> dict[str, bool | None]:
    """Collapse per-node video state into one answer per physical card.

    A capture card exposes several /dev nodes and only some of them
    answer the signal query - the Magewell reports on index0 and stays
    silent on index1. Taking the last node's answer would therefore
    report a working card as unknown, so a positive answer from any node
    wins, and False only stands when nothing said otherwise.
    """
    by_serial: dict[str, bool | None] = {}
    for item in report.video:
        if not item.usb_serial:
            continue
        current = by_serial.get(item.usb_serial, None)
        if current is True:
            continue
        if item.has_signal is True:
            by_serial[item.usb_serial] = True
        elif item.has_signal is False:
            by_serial[item.usb_serial] = False
        elif item.usb_serial not in by_serial:
            by_serial[item.usb_serial] = None
    return by_serial


def _match_existing(
    existing: list[Device], reported_serial: str | None, reported_path: str
) -> Device | None:
    """Find the row this reported device already occupies.

    Serial first: it survives the device being moved to another port,
    which is the whole reason identity is bound to it. Only when a
    device exposes no serial at all do we fall back to the port path,
    which is fragile by nature - a replug there looks like a new device.
    """
    if reported_serial:
        for device in existing:
            if device.usb_serial == reported_serial:
                return device
        return None
    for device in existing:
        if device.usb_serial is None and device.sysfs_path == reported_path:
            return device
    return None


def ingest(db: Session, shuttle: Shuttle, report: AgentReport) -> tuple[int, list[str]]:
    """Make the database agree with this report. Returns (count, notices)."""
    now = datetime.utcnow()
    notices: list[str] = []

    if report.schema_version != SCHEMA_VERSION_SUPPORTED:
        # Not fatal on purpose: agents are allowed to run ahead of the
        # master. Surfaced so a skew that later matters is already
        # visible rather than discovered during an outage.
        notices.append(
            f"agent reports schema {report.schema_version}, master expects "
            f"{SCHEMA_VERSION_SUPPORTED} - accepted, but verify the contract"
        )

    existing = list(db.scalars(select(Device).where(Device.shuttle_id == shuttle.id)))
    signal_by_serial = _video_signal_by_serial(report)
    seen: set[int] = set()

    for reported in report.devices:
        device = _match_existing(existing, reported.usb_serial, reported.sysfs_path)
        if device is None:
            device = Device(
                shuttle_id=shuttle.id,
                usb_serial=reported.usb_serial,
                first_seen_at=now,
            )
            db.add(device)
            existing.append(device)

        device.kind = reported.kind
        device.usb_vendor_id = reported.usb_vendor_id
        device.usb_product_id = reported.usb_product_id
        device.product = reported.product
        device.manufacturer = reported.manufacturer
        device.sysfs_path = reported.sysfs_path
        device.signature = reported.signature
        device.is_present = True
        device.last_seen_at = now

        # Only overwrite a known chain when this report actually probed
        # one. A passive scan carries jtag=None, and treating that as
        # "no chain" would erase the IDCODEs from the last real probe -
        # which, since probing is active and disruptive, may be the only
        # ones we get for a long while.
        if reported.jtag is not None and reported.jtag.ok:
            device.jtag_chain = [d.model_dump() for d in reported.jtag.devices]

        if reported.usb_serial and reported.usb_serial in signal_by_serial:
            device.has_video_signal = signal_by_serial[reported.usb_serial]

        db.flush()
        seen.add(device.id)

    # Whatever this report did not mention is gone. The row stays, so
    # "what was attached last week" remains answerable; only its presence
    # flips.
    for device in existing:
        if device.id not in seen and device.is_present:
            device.is_present = False

    shuttle.hostname = report.hostname
    shuttle.agent_version = report.agent_version
    shuttle.last_report_at = now
    db.commit()

    return len(report.devices), notices
