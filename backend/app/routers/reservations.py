import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Lab, Reservation, ReservationStatus, User
from app.schemas import CalendarEntryOut, JoinQueueRequest, ReservationCreate, ReservationOut
from app.services.availability import (
    ACCESS_GRACE_PERIOD as _ACCESS_GRACE_PERIOD,
    SESSION_LENGTH as _SESSION_LENGTH,
    access_deadline as _access_deadline,
    overlapping_reservation as _overlapping_reservation,
    reservation_window as _reservation_window,
)
from app.services.queue import renumber_queue
from app.services import deployments
from app.services.weblab import close_weblab_session

router = APIRouter(prefix="/reservations", tags=["reservations"])
logger = logging.getLogger("fpga_remote_lab")


def _close_hardware_session_if_open(db: Session, reservation: Reservation) -> None:
    """Ending a reservation from our side (Finish, Cancel) must also end
    the real WebLab session on CT300 - otherwise the browser tab that
    already had the hardware page open keeps working, and a second user
    can be handed a fresh session on what our own database now considers
    a free board while the first one is still physically live. Only
    reservations that actually opened the hardware (weblab_session_url
    set) have anything on CT300 to close. Best-effort: an unreachable
    container shouldn't block the user from ending their own reservation.
    """
    if reservation.weblab_session_url is None:
        return
    try:
        close_weblab_session(
            reservation.lab,
            reservation.weblab_session_url,
            backend_url=deployments.address_for(db, reservation.lab),
        )
    except httpx.HTTPError:
        logger.warning(
            "Could not close hardware session for reservation %d (lab %d) - it may still be reachable elsewhere",
            reservation.id,
            reservation.lab_id,
        )


def _utc(dt: datetime) -> datetime:
    # Stored times are naive UTC; tag them so the JSON carries an explicit
    # +00:00 and the browser converts to the viewer's local timezone
    # instead of guessing (a naive string gets parsed as local time).
    return dt.replace(tzinfo=timezone.utc)


def _to_out(reservation: Reservation) -> ReservationOut:
    usage_start = reservation.usage_start_time
    # session_ends_at counts down from hardware_started_at, not
    # usage_start_time - the reservation can be "active" (board claimed,
    # occupying the calendar) well before the hardware session actually
    # opens, and a failed /access attempt in between must not make the
    # frontend show (or count down) time the user was never granted. See
    # models.py::Reservation.hardware_started_at.
    hardware_start = reservation.hardware_started_at
    deadline = _access_deadline(reservation)
    return ReservationOut(
        id=reservation.id,
        lab_id=reservation.lab_id,
        lab_name=reservation.lab.name,
        reservation_date=reservation.reservation_date,
        reservation_time=reservation.reservation_time,
        status=reservation.status,
        queue_position=reservation.queue_position,
        created_at=reservation.created_at,
        usage_start_time=_utc(usage_start) if usage_start is not None else None,
        session_ends_at=_utc(hardware_start + _SESSION_LENGTH) if hardware_start is not None else None,
        access_deadline=_utc(deadline) if deadline is not None else None,
    )


def _has_open_reservation(db: Session, user_id: int, lab_id: int) -> bool:
    existing = db.scalar(
        select(Reservation).where(
            Reservation.user_id == user_id,
            Reservation.lab_id == lab_id,
            Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
        )
    )
    return existing is not None


@router.get("/mine", response_model=list[ReservationOut])
def list_my_reservations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    reservations = db.scalars(
        select(Reservation)
        .where(
            Reservation.user_id == user.id,
            Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
        )
        .order_by(Reservation.created_at)
    ).all()
    return [_to_out(r) for r in reservations]


@router.get("/calendar", response_model=list[CalendarEntryOut])
def calendar(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Who has (or will have) each board, and when - symbolized by username
    only, never full profile details (see [[project_ct210_migration_plan]]
    for why: this is a shared schedule view, not a directory).

    Only entries with a determinable time slot are included: an active
    session (already running) and pending reservations that were booked
    for a specific date/time. Immediate queue joins with no fixed time
    (queue_position-based, "whenever it's your turn") have no slot to
    show here - they show up on the Dashboard/Labs queue view instead.
    """
    candidates = db.scalars(
        select(Reservation).where(
            Reservation.status.in_([ReservationStatus.active, ReservationStatus.pending]),
        )
    ).all()

    entries = []
    for r in candidates:
        window = _reservation_window(r)
        if window is None:
            # Immediate-queue waiter with no committed time - nothing to
            # place on a calendar; shows on the Dashboard queue view instead.
            continue
        start, end = window
        entries.append(
            CalendarEntryOut(
                lab_id=r.lab_id,
                lab_name=r.lab.name,
                username=r.user.username,
                status=r.status,
                start_time=_utc(start),
                end_time=_utc(end),
            )
        )

    entries.sort(key=lambda e: e.start_time)
    return entries


@router.post("", response_model=ReservationOut, status_code=201)
def make_reservation(
    payload: ReservationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    scheduled_at = datetime.combine(payload.reservation_date, payload.reservation_time)
    min_advance = timedelta(minutes=settings.min_reservation_advance_minutes)
    if scheduled_at < datetime.utcnow() + min_advance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Reservations must be made at least {settings.min_reservation_advance_minutes} minutes in advance",
        )

    if _has_open_reservation(db, user.id, payload.lab_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an open reservation for this lab",
        )

    # Reject a slot whose [start, start + session length) window overlaps
    # any other open reservation for this board - a plain (date, time)
    # equality check missed a 10:28-10:32 booking followed by a 10:30-10:34
    # one: different start times, but two real overlapping hardware sessions.
    scheduled_end = scheduled_at + _SESSION_LENGTH
    if _overlapping_reservation(db, payload.lab_id, scheduled_at, scheduled_end) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That time slot overlaps with an existing reservation for this lab",
        )

    reservation = Reservation(
        user_id=user.id,
        lab_id=payload.lab_id,
        reservation_date=payload.reservation_date,
        reservation_time=payload.reservation_time,
        status=ReservationStatus.pending,
        queue_position=0,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    renumber_queue(db, payload.lab_id)
    db.commit()
    db.refresh(reservation)
    return _to_out(reservation)


@router.post("/access-now", response_model=ReservationOut, status_code=201)
def access_now(payload: JoinQueueRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Use the board right now. There is no waiting queue: either the board
    is available to the caller this instant, or this fails with a 409 that
    explains why.

    Availability, in order:
    - Already have an active session here -> return it (idempotent, lets a
      returning browser tab re-open the hardware).
    - Have a scheduled reservation whose booked window covers now -> that's
      how a slot is entered when its time arrives (no separate Start step).
    - Otherwise start a fresh immediate session, but only if the board is
      free and the [now, now + session length) window collides with no
      reservation - the caller's own future booking, or anyone else's.
    """
    now = datetime.utcnow()
    window_end = now + _SESSION_LENGTH

    active_own = db.scalar(
        select(Reservation).where(
            Reservation.lab_id == payload.lab_id,
            Reservation.user_id == user.id,
            Reservation.status == ReservationStatus.active,
        )
    )
    if active_own is not None:
        return _to_out(active_own)

    # Refuse to hand out or promote a reservation to active when the
    # board itself is not currently fit to serve - a reservation that can
    # never be opened isn't "active", it's a dead end the user has to
    # notice and cancel themselves. Checked before *any* state change
    # below (both promoting a scheduled reservation and creating a fresh
    # one), using the same health check /labs/{id}/access enforces, so
    # the same "This lab is temporarily unavailable: ..." reason a
    # student would otherwise only see after already being marked active.
    lab = db.get(Lab, payload.lab_id)
    if lab is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lab not found")
    resolved = deployments.resolve(db, lab)
    if resolved is not None and not resolved.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"This lab is temporarily unavailable: {resolved.reason}",
        )

    own_scheduled = db.scalars(
        select(Reservation).where(
            Reservation.lab_id == payload.lab_id,
            Reservation.user_id == user.id,
            Reservation.status == ReservationStatus.pending,
            Reservation.reservation_date.is_not(None),
            Reservation.reservation_time.is_not(None),
        )
    ).all()
    covering = None
    for r in own_scheduled:
        start = datetime.combine(r.reservation_date, r.reservation_time)
        # Only a short grace period past the scheduled start, not the full
        # session length - see services/availability.py::access_deadline
        # (the value the frontend counts down against).
        if start <= now < start + _ACCESS_GRACE_PERIOD:
            covering = r
            break

    if covering is not None:
        if _overlapping_reservation(db, payload.lab_id, now, window_end, exclude_id=covering.id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The board is in use right now - try again in a moment.",
            )
        covering.status = ReservationStatus.active
        covering.usage_start_time = now
        db.commit()
        db.refresh(covering)
        return _to_out(covering)

    # No session to resume - the caller wants an immediate, unscheduled turn.
    if _has_open_reservation(db, user.id, payload.lab_id):
        # They hold a pending reservation, but (per the checks above) it's
        # for a later time, not now.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have a reservation for this board scheduled for a later time.",
        )

    if _overlapping_reservation(db, payload.lab_id, now, window_end) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The board is occupied or reserved for this time - check the calendar for a free slot.",
        )

    reservation = Reservation(
        user_id=user.id,
        lab_id=payload.lab_id,
        status=ReservationStatus.active,
        queue_position=0,
        usage_start_time=now,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return _to_out(reservation)


@router.post("/{reservation_id}/cancel", response_model=ReservationOut)
def cancel_reservation(
    reservation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    reservation = db.get(Reservation, reservation_id)
    if reservation is None or reservation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if reservation.status not in (ReservationStatus.pending, ReservationStatus.active):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reservation is not open")

    _close_hardware_session_if_open(db, reservation)
    reservation.status = ReservationStatus.cancelled
    reservation.usage_end_time = datetime.utcnow()
    db.commit()
    renumber_queue(db, reservation.lab_id)
    db.commit()
    db.refresh(reservation)
    return _to_out(reservation)


@router.post("/{reservation_id}/complete", response_model=ReservationOut)
def complete_lab_usage(
    reservation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    reservation = db.get(Reservation, reservation_id)
    if reservation is None or reservation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")
    if reservation.status != ReservationStatus.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reservation is not active")

    # Once the allotted time is up the session is already over - the
    # periodic sweep (see services/queue.py) will mark it expired shortly.
    # A manual Finish shouldn't be able to "close" a session that has
    # already run out, so the frontend can't race the sweep into reporting
    # completed instead of expired.
    if (
        reservation.usage_start_time is not None
        and datetime.utcnow() - reservation.usage_start_time > _SESSION_LENGTH
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session has already run out of time.",
        )

    _close_hardware_session_if_open(db, reservation)
    reservation.status = ReservationStatus.completed
    reservation.usage_end_time = datetime.utcnow()
    db.commit()
    renumber_queue(db, reservation.lab_id)
    db.commit()
    db.refresh(reservation)
    return _to_out(reservation)
