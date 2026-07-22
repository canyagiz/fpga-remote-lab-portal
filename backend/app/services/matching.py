"""Comparing what a lab needs against what a shuttle actually has.

The whole engine is one loop over polymorphic objects; the interesting
decisions live in services/requirements.py, and this module only assembles
the view they check against.

Two answers come out of it, and both were asked for:

    what is missing   evaluate a template against each shuttle
    what is spare     hardware no template has any use for
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Board, Device, FpgaFamily, LabTemplate, Shuttle
from app.services import requirements as req


@dataclass
class ShuttleInventory:
    """One shuttle's hardware, as a requirement needs to see it.

    `boards` are resolved rather than stored: a Board records the serial
    of its programmer, so the boards "on" this shuttle are whichever ones
    the shuttle is currently reporting that serial for. Moving a board to
    another machine therefore needs no edit anywhere - it simply starts
    appearing in a different inventory.
    """

    shuttle: Shuttle
    devices: list[Device] = field(default_factory=list)
    boards: list[Board] = field(default_factory=list)

    def find_board(self, family: FpgaFamily) -> Board | None:
        for board in self.boards:
            if board.family == family:
                return board
        return None

    def find_device(self, *, kind: str, signature: str | None = None) -> Device | None:
        for device in self.devices:
            if device.kind != kind:
                continue
            if signature is not None and device.signature != signature:
                continue
            return device
        return None

    def device_for_board(self, board: Board) -> Device | None:
        for device in self.devices:
            if device.usb_serial == board.programmer_serial:
                return device
        return None


@dataclass
class GapReport:
    shuttle_id: int
    shuttle_name: str
    template_id: int
    template_name: str
    results: list[req.RequirementResult]

    @property
    def deployable(self) -> bool:
        # Degraded counts as not deployable: hardware that is present but
        # not working produces a lab that looks fine in the catalogue and
        # fails once a student is inside it, which is worse than one that
        # is honestly unavailable.
        return all(r.status is req.RequirementStatus.satisfied for r in self.results)

    @property
    def missing_count(self) -> int:
        return sum(1 for r in self.results if r.status is not req.RequirementStatus.satisfied)


def shuttle_status_is_offline(db: Session, shuttle: Shuttle) -> bool:
    """Has this node gone quiet?

    Thin wrapper over services/inventory.shuttle_status so callers that
    only care about the yes/no do not have to know the vocabulary, and
    so "never reported" counts as offline rather than being a third case
    every caller has to remember to handle.
    """
    from app.services import inventory

    return inventory.shuttle_status(shuttle) != "online"


def build_inventory(db: Session, shuttle: Shuttle) -> ShuttleInventory:
    devices = list(
        db.scalars(
            select(Device).where(
                Device.shuttle_id == shuttle.id, Device.is_present.is_(True)
            )
        )
    )
    serials = {d.usb_serial for d in devices if d.usb_serial}
    boards = (
        list(db.scalars(select(Board).where(Board.programmer_serial.in_(serials))))
        if serials
        else []
    )
    return ShuttleInventory(shuttle=shuttle, devices=devices, boards=boards)


def evaluate(template: LabTemplate, inventory: ShuttleInventory) -> GapReport:
    """Check one template against one shuttle.

    Polymorphism does the work: this loop does not grow when a new
    requirement type is introduced.
    """
    parsed = req.parse(template.requirements or [])
    return GapReport(
        shuttle_id=inventory.shuttle.id,
        shuttle_name=inventory.shuttle.name,
        template_id=template.id,
        template_name=template.name,
        results=[requirement.check(inventory) for requirement in parsed],
    )


def evaluate_across_fleet(db: Session, template: LabTemplate) -> list[GapReport]:
    """Where can this lab run, and what is stopping it elsewhere?"""
    shuttles = db.scalars(select(Shuttle).order_by(Shuttle.id)).all()
    return [evaluate(template, build_inventory(db, s)) for s in shuttles]


def unused_devices(db: Session) -> list[Device]:
    """Hardware no template has a use for - the "spare" side of the report.

    A device counts as used if it backs a registered board that some
    template's requirements can be satisfied by, or if it is a capture
    card or programmer that a template asks for by signature. Anything
    left over is sitting idle, which is worth knowing before someone buys
    another one.
    """
    templates = db.scalars(select(LabTemplate)).all()
    if not templates:
        # With nothing declaring a need, "unused" has no meaning - every
        # device would trivially qualify, and a list of all the hardware
        # under the heading "no lab template asks for it" reads as a
        # fault when the real state is simply that no templates exist
        # yet. Answer nothing rather than answer misleadingly.
        return []

    wanted_families: set[FpgaFamily] = set()
    wanted_signatures: set[str] = set()
    wants_capture = False

    for template in templates:
        for requirement in req.parse(template.requirements or []):
            if isinstance(requirement, req.FpgaRequirement):
                wanted_families.add(requirement.family)
            elif isinstance(requirement, req.ProgrammerRequirement):
                wanted_signatures.add(requirement.signature)
            elif isinstance(requirement, req.VideoCaptureRequirement):
                wants_capture = True

    boards_by_serial = {b.programmer_serial: b for b in db.scalars(select(Board))}
    devices = db.scalars(select(Device).where(Device.is_present.is_(True))).all()

    spare = []
    for device in devices:
        if device.kind == "video_capture" and wants_capture:
            continue
        if device.signature and device.signature in wanted_signatures:
            continue
        board = boards_by_serial.get(device.usb_serial or "")
        if board is not None and board.family in wanted_families:
            continue
        spare.append(device)
    return spare


def unclaimed_devices(db: Session) -> list[Device]:
    """Programmers present on some shuttle that no Board has claimed.

    This is the "new hardware found" queue: a cable nobody has yet said
    what is on the end of. Only programmers, because those are what a
    board is identified by - a stray capture card is not an unregistered
    board.
    """
    claimed = {b.programmer_serial for b in db.scalars(select(Board))}
    devices = db.scalars(
        select(Device).where(Device.is_present.is_(True), Device.kind == "programmer")
    ).all()
    return [d for d in devices if d.usb_serial and d.usb_serial not in claimed]
