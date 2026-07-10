from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Lab, LoginEvent, Reservation, ReservationStatus, User
from app.schemas import LabUsageStat, MyStatsOut

router = APIRouter(prefix="/stats", tags=["stats"])

# How far back the login-frequency data reaches. The Dashboard chart shows
# a shorter window; sending a little extra costs nothing and lets the
# frontend widen its view without a backend change.
_LOGIN_HISTORY_DAYS = 30


def _lab_usage_stats(db: Session, user_id: int, *criteria) -> list[LabUsageStat]:
    rows = db.execute(
        select(Lab.id, Lab.name, Lab.image_url, func.count(Reservation.id))
        .join(Reservation, Reservation.lab_id == Lab.id)
        .where(Reservation.user_id == user_id, *criteria)
        .group_by(Lab.id, Lab.name, Lab.image_url)
        .order_by(func.count(Reservation.id).desc())
    ).all()
    return [
        LabUsageStat(lab_id=lab_id, lab_name=name, image_url=image_url, session_count=count)
        for lab_id, name, image_url, count in rows
    ]


@router.get("/me", response_model=MyStatsOut)
def my_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The current user's own activity, for the Dashboard stat cards.

    Strictly personal - nothing here exposes other users' activity, unlike
    the calendar (which shows usernames on purpose).
    """
    labs_demoed = _lab_usage_stats(db, user.id, Reservation.usage_start_time.is_not(None))
    labs_completed = _lab_usage_stats(
        db, user.id, Reservation.status == ReservationStatus.completed
    )

    status_counts: dict[ReservationStatus, int] = dict(
        db.execute(
            select(Reservation.status, func.count())
            .where(Reservation.user_id == user.id)
            .group_by(Reservation.status)
        ).all()
    )

    since = datetime.utcnow() - timedelta(days=_LOGIN_HISTORY_DAYS)
    login_times = db.scalars(
        select(LoginEvent.created_at)
        .where(LoginEvent.user_id == user.id, LoginEvent.created_at >= since)
        .order_by(LoginEvent.created_at)
    ).all()

    return MyStatsOut(
        labs_demoed=labs_demoed,
        labs_completed=labs_completed,
        total_reservations=sum(status_counts.values()),
        completed_count=status_counts.get(ReservationStatus.completed, 0),
        cancelled_count=status_counts.get(ReservationStatus.cancelled, 0),
        expired_count=status_counts.get(ReservationStatus.expired, 0),
        upcoming_count=status_counts.get(ReservationStatus.pending, 0),
        login_times=[t.replace(tzinfo=timezone.utc) for t in login_times],
    )
