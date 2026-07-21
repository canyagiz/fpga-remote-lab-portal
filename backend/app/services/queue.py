import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Reservation, ReservationStatus
from app.services.availability import ACCESS_GRACE_PERIOD
from app.services import deployments
from app.services.weblab import close_weblab_session, is_weblab_session_finished

logger = logging.getLogger("fpga_remote_lab")


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
            # The clock ran out on our side - tell CT300 too, the same
            # way Finish/Cancel do, instead of leaving the hardware
            # session open until sweep_logged_out_sessions eventually
            # notices CT300 agrees (it has its own, independently
            # ticking timeout) or the browser tab just keeps working.
            if reservation.weblab_session_url is not None:
                try:
                    close_weblab_session(
                        reservation.lab,
                        reservation.weblab_session_url,
                        backend_url=deployments.address_for(db, reservation.lab),
                    )
                except httpx.HTTPError:
                    logger.warning(
                        "Could not close hardware session for overrun reservation %d (lab %d)",
                        reservation.id,
                        reservation.lab_id,
                    )
        elif reservation.reservation_date and reservation.reservation_time:
            # A scheduled slot nobody accessed - give the grace period
            # access_now itself enforces (see
            # services/availability.py::access_deadline) before giving up
            # on it, not the instant the clock passes the scheduled time.
            scheduled_at = datetime.combine(reservation.reservation_date, reservation.reservation_time)
            if now <= scheduled_at + ACCESS_GRACE_PERIOD:
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


def sweep_logged_out_sessions(db: Session) -> int:
    """Close out reservations whose hardware session already ended on the
    CT300 side - most notably an explicit "Log out" clicked *inside* the
    lab UI, which the hardware container knows about immediately but we
    otherwise wouldn't until session_duration_seconds naturally elapses
    (see routers/hardware_proxy.py for how that click reaches the
    container at all, and services/weblab.py::is_weblab_session_finished
    for the actual detection).

    Only reservations that actually opened a session (weblab_session_url
    set) are checked - an active reservation nobody has opened yet has
    nothing on the hardware side to poll.
    """
    active_with_session = db.scalars(
        select(Reservation).where(
            Reservation.status == ReservationStatus.active,
            Reservation.weblab_session_url.is_not(None),
        )
    ).all()

    if not active_with_session:
        return 0

    # Resolved here, on this thread, and passed in below. A SQLAlchemy
    # Session is not thread-safe, so anything touching `db` has to happen
    # before the pool starts - inside _check it would be several threads
    # sharing one session.
    addresses = {
        reservation.id: deployments.address_for(db, reservation.lab)
        for reservation in active_with_session
    }

    def _check(reservation: Reservation) -> tuple[Reservation, bool]:
        try:
            return reservation, is_weblab_session_finished(
                reservation.lab,
                reservation.weblab_session_url,
                backend_url=addresses[reservation.id],
            )
        except httpx.HTTPError:
            # Hardware unreachable or mid-restart right now - leave the
            # reservation as is and try again on the next sweep.
            return reservation, False

    # Checked concurrently, not one after another: each is an up-to-10s
    # HTTP call (see is_weblab_session_finished), and this whole function
    # already runs off the event loop via asyncio.to_thread (see
    # main.py::_expiry_sweep_loop) - but a sequential loop here would still
    # let one slow/unreachable board delay every other board's check by up
    # to 10s each, compounding with every open session.
    with ThreadPoolExecutor(max_workers=len(active_with_session)) as pool:
        results = list(pool.map(_check, active_with_session))

    closed_count = 0
    now = datetime.utcnow()
    for reservation, finished in results:
        if finished:
            reservation.status = ReservationStatus.completed
            reservation.usage_end_time = now
            closed_count += 1

    if closed_count:
        db.commit()
        logger.info("Logout sweep: %d reservation(s) closed after in-lab logout", closed_count)

    return closed_count
