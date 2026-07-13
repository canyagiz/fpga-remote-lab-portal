from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Reservation, ReservationStatus

# Every time value handled here is naive UTC: usage_start_time comes
# straight from datetime.utcnow(), and reservation_date/reservation_time
# are sent by the frontend already converted to UTC (see LabsPage's
# localToUtcParts). Callers re-attach tzinfo=utc only at the response
# boundary (schemas), never in here.

SESSION_LENGTH = timedelta(seconds=settings.session_duration_seconds)
ACCESS_GRACE_PERIOD = timedelta(seconds=settings.access_grace_period_seconds)


def access_deadline(reservation: Reservation) -> datetime | None:
    """The last instant a *pending, scheduled* reservation can still be
    turned into a real session via Access - `reservation_time` plus a
    short grace period, not the full session length. None for anything
    that isn't a not-yet-activated scheduled booking (active sessions
    have their own session_ends_at instead; immediate/queue entries have
    no scheduled slot to have a deadline against)."""
    if (
        reservation.status != ReservationStatus.pending
        or reservation.reservation_date is None
        or reservation.reservation_time is None
    ):
        return None
    scheduled_at = datetime.combine(reservation.reservation_date, reservation.reservation_time)
    return scheduled_at + ACCESS_GRACE_PERIOD


def reservation_window(reservation: Reservation) -> tuple[datetime, datetime] | None:
    """The [start, end) UTC window a reservation occupies on the board, or
    None for an immediate-queue entry that has no committed time yet (a FIFO
    waiter behind an active session)."""
    if reservation.status == ReservationStatus.active and reservation.usage_start_time is not None:
        start = reservation.usage_start_time
    elif reservation.reservation_date is not None and reservation.reservation_time is not None:
        start = datetime.combine(reservation.reservation_date, reservation.reservation_time)
    else:
        return None
    return start, start + SESSION_LENGTH


def open_windows(db: Session, lab_id: int, exclude_id: int | None = None) -> list[tuple[datetime, datetime]]:
    """Sorted [start, end) windows for every open (pending/active)
    reservation on this lab that has a determinable time."""
    reservations = db.scalars(
        select(Reservation).where(
            Reservation.lab_id == lab_id,
            Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
        )
    ).all()
    windows = []
    for r in reservations:
        if exclude_id is not None and r.id == exclude_id:
            continue
        window = reservation_window(r)
        if window is not None:
            windows.append(window)
    windows.sort(key=lambda w: w[0])
    return windows


def overlapping_reservation(
    db: Session, lab_id: int, start: datetime, end: datetime, exclude_id: int | None = None
) -> Reservation | None:
    """First open reservation for the lab whose occupied window overlaps
    [start, end). Half-open, so a booking that begins exactly when another
    ends does *not* count as an overlap."""
    reservations = db.scalars(
        select(Reservation).where(
            Reservation.lab_id == lab_id,
            Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
        )
    ).all()
    for other in reservations:
        if exclude_id is not None and other.id == exclude_id:
            continue
        window = reservation_window(other)
        if window is None:
            continue
        other_start, other_end = window
        if start < other_end and other_start < end:
            return other
    return None


def next_available_at(db: Session, lab_id: int, now: datetime | None = None) -> datetime | None:
    """Earliest moment at/after `now` when a fresh SESSION_LENGTH-long
    session could start on this board without overlapping any open
    reservation. None means the board is free right now.

    Open reservations for a single lab never overlap each other (enforced
    at booking time - see overlapping_reservation's callers), so a single
    chronological pass is sufficient: push the candidate start past any
    window it would collide with, in order.
    """
    if now is None:
        now = datetime.utcnow()
    candidate = now
    for start, end in open_windows(db, lab_id):
        if candidate < end and start < candidate + SESSION_LENGTH:
            candidate = end
    return None if candidate <= now else candidate
