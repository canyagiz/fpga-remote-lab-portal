from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Reservation, ReservationStatus, User
from app.schemas import JoinQueueRequest, ReservationCreate, ReservationOut
from app.services.queue import renumber_queue

router = APIRouter(prefix="/reservations", tags=["reservations"])


def _to_out(reservation: Reservation) -> ReservationOut:
    return ReservationOut(
        id=reservation.id,
        lab_id=reservation.lab_id,
        lab_name=reservation.lab.name,
        reservation_date=reservation.reservation_date,
        reservation_time=reservation.reservation_time,
        status=reservation.status,
        queue_position=reservation.queue_position,
        created_at=reservation.created_at,
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

    # Prevent two different users from booking the same lab at the same
    # exact slot - the old repo only checked "same user, same lab".
    slot_taken = db.scalar(
        select(Reservation).where(
            Reservation.lab_id == payload.lab_id,
            Reservation.reservation_date == payload.reservation_date,
            Reservation.reservation_time == payload.reservation_time,
            Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
        )
    )
    if slot_taken is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That time slot is already booked")

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


@router.post("/queue", response_model=ReservationOut, status_code=201)
def join_queue(payload: JoinQueueRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if _has_open_reservation(db, user.id, payload.lab_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already in the queue or have an active reservation for this lab",
        )

    # The lab is free only if nobody else is currently active *or* pending
    # for it - checking `pending` alone was a bug: once the person ahead
    # moves to `active` they leave the pending set, so the next joiner
    # would wrongly see an "empty" queue and also become active immediately.
    lab_occupied = db.scalar(
        select(Reservation).where(
            Reservation.lab_id == payload.lab_id,
            Reservation.status.in_([ReservationStatus.pending, ReservationStatus.active]),
        )
    )
    is_first_in_line = lab_occupied is None

    reservation = Reservation(
        user_id=user.id,
        lab_id=payload.lab_id,
        status=ReservationStatus.active if is_first_in_line else ReservationStatus.pending,
        queue_position=0,
        usage_start_time=datetime.utcnow() if is_first_in_line else None,
    )
    db.add(reservation)
    db.commit()
    renumber_queue(db, payload.lab_id)
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

    reservation.status = ReservationStatus.cancelled
    reservation.usage_end_time = datetime.utcnow()
    db.commit()
    renumber_queue(db, reservation.lab_id)
    db.commit()
    db.refresh(reservation)
    return _to_out(reservation)


@router.post("/{reservation_id}/start", response_model=ReservationOut)
def start_lab_usage(reservation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    reservation = db.get(Reservation, reservation_id)
    if reservation is None or reservation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found")

    if reservation.status == ReservationStatus.active:
        return _to_out(reservation)

    if reservation.status != ReservationStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Reservation is {reservation.status.value}"
        )

    if reservation.queue_position != 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Not your turn yet - queue position {reservation.queue_position}",
        )

    # Being first among the *pending* entries doesn't mean the lab is free -
    # someone else's reservation for the same lab can still be `active`.
    lab_busy = db.scalar(
        select(Reservation).where(
            Reservation.lab_id == reservation.lab_id,
            Reservation.status == ReservationStatus.active,
            Reservation.id != reservation.id,
        )
    )
    if lab_busy is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lab is currently occupied")

    reservation.status = ReservationStatus.active
    reservation.usage_start_time = datetime.utcnow()
    db.commit()
    # This reservation just left the `pending` set, so whoever was behind it
    # needs to move up - same class of bug as the old repo's frozen queue,
    # just at the pending->active transition instead of cancel/complete.
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

    reservation.status = ReservationStatus.completed
    reservation.usage_end_time = datetime.utcnow()
    db.commit()
    renumber_queue(db, reservation.lab_id)
    db.commit()
    db.refresh(reservation)
    return _to_out(reservation)
