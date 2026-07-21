"""Where a lab actually lives right now, and whether it should be offered.

Everything here is opt-in per lab. `resolve` returns None for a lab with
no deployment, and every caller falls back to the behaviour that was
already there - the static backend_url from labs.yaml. That is what lets
this ship in front of a running teaching lab without changing anything
until an admin deliberately binds a lab to a board.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Board, Device, Lab, LabDeployment, Shuttle
from app.services import matching


@dataclass
class Resolved:
    """A deployment's current state, recomputed rather than stored.

    Storing availability would mean a background job had to keep it
    fresh, and a stale "available" is worse than none - it sends a
    student into a lab that is not there.
    """

    deployment: LabDeployment
    shuttle: Shuttle | None
    backend_url: str | None
    available: bool
    reason: str | None

    @property
    def status(self) -> str:
        if self.available:
            return "healthy"
        return "unavailable"


def _shuttle_holding(db: Session, board: Board) -> Shuttle | None:
    """Which machine currently reports this board's programmer."""
    return db.scalar(
        select(Shuttle)
        .join(Device, Device.shuttle_id == Shuttle.id)
        .where(
            Device.usb_serial == board.programmer_serial,
            Device.is_present.is_(True),
        )
        .limit(1)
    )


def resolve(db: Session, lab: Lab) -> Resolved | None:
    """Current state of this lab's deployment, or None if it has none."""
    deployment = db.scalar(select(LabDeployment).where(LabDeployment.lab_id == lab.id))
    if deployment is None:
        return None

    if not deployment.is_enabled:
        return Resolved(deployment, None, None, False, "Taken out of service by an administrator")

    shuttle = _shuttle_holding(db, deployment.board)
    if shuttle is None:
        # The board is registered but nothing is reporting it - unplugged,
        # or its shuttle's agent has stopped.
        return Resolved(
            deployment,
            None,
            None,
            False,
            f"{deployment.board.label} is not attached to any shuttle right now",
        )

    if matching.shuttle_status_is_offline(db, shuttle):
        return Resolved(
            deployment,
            shuttle,
            None,
            False,
            f"{shuttle.name} has stopped reporting",
        )

    if not shuttle.address:
        # Refused rather than guessed. The address is the one field that
        # decides where a student's browser is sent, so falling back to
        # an agent-reported hostname here would undo the reason it is
        # admin-set in the first place.
        return Resolved(
            deployment,
            shuttle,
            None,
            False,
            f"{shuttle.name} has no address configured",
        )

    report = matching.evaluate(deployment.template, matching.build_inventory(db, shuttle))
    if not report.deployable:
        # Name the first real problem. A list of every unmet requirement
        # belongs in the admin gap report, not in a student-facing line.
        first = next(
            r for r in report.results if r.status is not matching.req.RequirementStatus.satisfied
        )
        return Resolved(deployment, shuttle, None, False, first.message)

    return Resolved(
        deployment,
        shuttle,
        f"http://{shuttle.address}:{deployment.port}",
        True,
        None,
    )


def backend_url_for(db: Session, lab: Lab) -> str | None:
    """Where to START a session - health-gated.

    A lab with a deployment that is currently unavailable returns None:
    the caller must refuse rather than quietly fall back to the static
    URL, which would send a student at hardware the system just decided
    was not fit to serve.
    """
    resolved = resolve(db, lab)
    if resolved is None:
        return lab.backend_url
    return resolved.backend_url


def address_for(db: Session, lab: Lab) -> str | None:
    """Where to reach this lab's hardware - NOT health-gated.

    Deliberately different from backend_url_for. Ending or inspecting an
    already-open session has to work precisely when the lab has gone
    unhealthy: a capture card failing mid-session is exactly when the
    sweep needs to close that session, and refusing on health grounds
    would leave it open on the board, blocking the next user.

    Falls back to the static URL for an undeployed lab, and to it again
    if the board cannot currently be located - a best-effort address
    beats no address when the goal is to release hardware.
    """
    deployment = db.scalar(select(LabDeployment).where(LabDeployment.lab_id == lab.id))
    if deployment is None:
        return lab.backend_url

    shuttle = _shuttle_holding(db, deployment.board)
    if shuttle is None or not shuttle.address:
        return lab.backend_url
    return f"http://{shuttle.address}:{deployment.port}"
