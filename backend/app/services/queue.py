from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Reservation, ReservationStatus


def renumber_queue(db: Session, lab_id: int) -> None:
    """Recompute queue_position for a lab's pending reservations, in the
    order they were created, closing any gaps.

    The old repo set queue_position once when a reservation was created and
    never touched it again, so the person in position 1 waited forever once
    position 0 finished. This function is the fix: call it after any
    reservation leaves the `pending` queue (cancelled, completed, expired,
    or promoted to active).
    """
    pending = db.scalars(
        select(Reservation)
        .where(Reservation.lab_id == lab_id, Reservation.status == ReservationStatus.pending)
        .order_by(Reservation.created_at)
    ).all()

    for index, reservation in enumerate(pending):
        reservation.queue_position = index


def sweep_expired_reservations(db: Session) -> int:
    """Server-side replacement for the old client-triggered expiry check.

    Runs periodically from a background task (see app.main), so a slot is
    freed even if the user just closes their browser tab.
    """
    now = datetime.utcnow()
    expired_count = 0
    affected_lab_ids: set[int] = set()

    candidates = db.scalars(
        select(Reservation).where(
            Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active])
        )
    ).all()

    for reservation in candidates:
        if reservation.status == ReservationStatus.active:
            if reservation.usage_start_time is None:
                continue
            # An active session that has outlived its allotted lab time.
            elapsed = (now - reservation.usage_start_time).total_seconds()
            if elapsed <= settings.session_duration_seconds:
                continue
        elif reservation.reservation_date and reservation.reservation_time:
            scheduled_at = datetime.combine(reservation.reservation_date, reservation.reservation_time)
            if now <= scheduled_at:
                continue
        else:
            # A queue entry with no fixed time never expires on its own.
            continue

        reservation.status = ReservationStatus.expired
        reservation.usage_end_time = now
        affected_lab_ids.add(reservation.lab_id)
        expired_count += 1

    for lab_id in affected_lab_ids:
        renumber_queue(db, lab_id)

    if expired_count:
        db.commit()

    return expired_count
