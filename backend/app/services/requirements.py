"""What a lab needs, expressed as objects that can check themselves.

Each requirement knows how to evaluate itself against one shuttle's
inventory. The matching engine (services/matching.py) never learns about
hardware types - it calls `check` and collects answers. Adding a new
class of hardware means writing one subclass here and registering it in
the union at the bottom; no migration, no change to the engine, the
router, or the UI.

Three statuses, not two, and the distinction matters:

    satisfied  the requirement is met
    missing    the hardware is not there at all
    degraded   it is there but not working (a capture card with no
               signal, a board whose IDCODE no longer matches)

Collapsing degraded into missing would lose the difference between "buy
one" and "check the cable", which is the whole point of the report.

The requirement classes are pydantic models rather than plain
dataclasses because they are also the on-disk format: a LabTemplate
stores its requirements as JSON and parses them back through the
discriminated union below, so the class list and the storage format
cannot drift apart.
"""

from __future__ import annotations

import enum
from abc import abstractmethod
from typing import TYPE_CHECKING, Annotated, Literal, Union

from pydantic import BaseModel, Field

from app.models import FpgaFamily

if TYPE_CHECKING:  # avoids a circular import at runtime
    from app.services.matching import ShuttleInventory


class RequirementStatus(str, enum.Enum):
    satisfied = "satisfied"
    missing = "missing"
    degraded = "degraded"


class RequirementResult(BaseModel):
    type: str
    status: RequirementStatus
    # Written for whoever has to act on it - what is wrong and, where
    # possible, which physical thing to go and look at.
    message: str


class Requirement(BaseModel):
    """Base class. Subclasses implement `check` and nothing else."""

    type: str

    @abstractmethod
    def check(self, inv: "ShuttleInventory") -> RequirementResult: ...

    def _result(self, status: RequirementStatus, message: str) -> RequirementResult:
        return RequirementResult(type=self.type, status=status, message=message)


class FpgaRequirement(Requirement):
    """A board of a given family must be present on this shuttle."""

    type: Literal["fpga"] = "fpga"
    family: FpgaFamily

    def check(self, inv: "ShuttleInventory") -> RequirementResult:
        board = inv.find_board(family=self.family)
        if board is None:
            return self._result(
                RequirementStatus.missing,
                f"No {self.family.value} board is attached to this shuttle",
            )
        # A registered board whose silicon no longer answers as expected
        # is present but untrustworthy - someone may have swapped the
        # hardware behind the cable. Worth a human's attention, not an
        # automatic reinterpretation of what the board is.
        device = inv.device_for_board(board)
        if board.expected_idcode and device is not None and device.jtag_chain:
            found = {entry.get("idcode") for entry in device.jtag_chain}
            if board.expected_idcode not in found:
                return self._result(
                    RequirementStatus.degraded,
                    f"{board.label} reports IDCODE {', '.join(sorted(c for c in found if c))} "
                    f"but was registered as {board.expected_idcode} - hardware may have changed",
                )
        return self._result(RequirementStatus.satisfied, f"{board.label} is attached")


class ProgrammerRequirement(Requirement):
    """A programmer of a given kind must be present.

    Usually implied by the fpga requirement - a registered board names
    its programmer's serial - but stated separately so a template can
    demand a specific toolchain (a Xilinx lab needs an FTDI programmer,
    not just any cable).
    """

    type: Literal["programmer"] = "programmer"
    # Matches Device.signature, e.g. "altera-usb-blaster", "ftdi-ft2232".
    signature: str

    def check(self, inv: "ShuttleInventory") -> RequirementResult:
        device = inv.find_device(kind="programmer", signature=self.signature)
        if device is None:
            return self._result(
                RequirementStatus.missing, f"No {self.signature} programmer on this shuttle"
            )
        return self._result(
            RequirementStatus.satisfied,
            f"{self.signature} present (serial {device.usb_serial or 'unknown'})",
        )


class VideoCaptureRequirement(Requirement):
    """A capture card wired to this board, and by default a live signal.

    Resolved through the board rather than the shuttle. A capture card
    watches ONE board's HDMI output - it is not a machine-wide resource -
    so "is there a capture card somewhere on this shuttle" is the wrong
    question the moment a shuttle holds two boards and one card. It
    would report both labs ready while only one of them has a picture.

    When the template names a family (so a specific board is in
    question) but that board has no capture card recorded, the honest
    answer is that this cannot be verified - not that it passes. Saying
    it passes is exactly the silent wrongness this resolution exists to
    remove.
    """

    type: Literal["video_capture"] = "video_capture"
    require_signal: bool = True

    def check(self, inv: "ShuttleInventory") -> RequirementResult:
        board = inv.subject_board

        if board is None and inv.subject_family is not None:
            # The template is about a board that is not here. Falling
            # back to the shuttle would report some other board's card
            # as this lab's, which is how a lab with no hardware at all
            # ends up looking half-ready.
            return self._result(
                RequirementStatus.missing,
                f"No {inv.subject_family.value} board here to resolve a capture card for",
            )

        if board is not None:
            if not board.video_capture_serial:
                return self._result(
                    RequirementStatus.degraded,
                    f"No capture card is recorded for {board.label} - set which one "
                    "watches this board so its video can be checked",
                )
            device = inv.find_device_by_serial(board.video_capture_serial)
            if device is None:
                return self._result(
                    RequirementStatus.missing,
                    f"{board.label}'s capture card ({board.video_capture_serial}) "
                    "is not attached to this shuttle",
                )
        else:
            # No family named, so the template is not about a particular
            # board and the shuttle-wide question is the right one.
            device = inv.find_device(kind="video_capture")
            if device is None:
                return self._result(
                    RequirementStatus.missing, "No HDMI capture card on this shuttle"
                )

        where = f"{board.label}'s capture card" if board else "Capture card"
        if not self.require_signal:
            return self._result(
                RequirementStatus.satisfied, f"{where} present ({device.usb_serial})"
            )
        if device.has_video_signal is False:
            # This is the failure a student would otherwise discover as a
            # black video feed, mid-session.
            return self._result(
                RequirementStatus.degraded,
                f"{where} ({device.usb_serial}) reports no HDMI signal - "
                "check the cable from the board",
            )
        if device.has_video_signal is None:
            # Unknown is not a fault. Reporting it as one would take a
            # working lab out of the catalogue because a driver did not
            # answer a query.
            return self._result(
                RequirementStatus.satisfied,
                f"{where} ({device.usb_serial}) present, signal state unknown",
            )
        return self._result(
            RequirementStatus.satisfied, f"{where} ({device.usb_serial}) has signal"
        )


class GpioRequirement(Requirement):
    """A controller for the board's physical switches must be assigned.

    Checked as configuration, not connectivity: whether the Pi actually
    answers has to be tested from the shuttle, since that is the machine
    that will talk to it, and the agent has no way to be told which
    endpoints to try yet. So this catches "no Pi assigned to this board"
    and says plainly that reachability is unverified.
    """

    type: Literal["gpio"] = "gpio"

    def check(self, inv: "ShuttleInventory") -> RequirementResult:
        board = inv.subject_board

        if board is None and inv.subject_family is not None:
            return self._result(
                RequirementStatus.missing,
                f"No {inv.subject_family.value} board here to resolve a GPIO controller for",
            )

        if board is not None:
            # This board's own controller, not every endpoint on the
            # shuttle. Listing them all made a Cyclone lab report the
            # Arty's UART bridge as if it drove its switches.
            if not board.gpio_endpoint:
                return self._result(
                    RequirementStatus.missing,
                    f"No GPIO controller is assigned to {board.label}",
                )
            return self._result(
                RequirementStatus.satisfied,
                f"{board.label} is driven by {board.gpio_endpoint} (not probed)",
            )

        boards = [b for b in inv.boards if b.gpio_endpoint]
        if not boards:
            return self._result(
                RequirementStatus.missing,
                "No board on this shuttle has a GPIO controller assigned",
            )
        endpoints = ", ".join(sorted({b.gpio_endpoint for b in boards if b.gpio_endpoint}))
        return self._result(
            RequirementStatus.satisfied, f"GPIO controller assigned ({endpoints}, not probed)"
        )


# The discriminated union is what makes a stored JSON blob come back as
# the right class. A new requirement type is added here and nowhere
# else - the engine, the API and the database are all indifferent to the
# length of this list.
AnyRequirement = Annotated[
    Union[
        FpgaRequirement,
        ProgrammerRequirement,
        VideoCaptureRequirement,
        GpioRequirement,
    ],
    Field(discriminator="type"),
]


class RequirementList(BaseModel):
    """Wrapper so a bare list can be validated through the union."""

    items: list[AnyRequirement]


def parse(raw: list[dict]) -> list[Requirement]:
    """Turn stored JSON back into typed requirement objects."""
    return list(RequirementList(items=raw).items)
