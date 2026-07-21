import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import (
    AdminEmail,
    Lab,
    Reservation,
    ReservationStatus,
    User,
    UserProfile,
    UserRole,
)
from app.schemas import (
    AdminEntry,
    AdminReservationOut,
    AdminUserDetail,
    AdminUserSummary,
    GrantAdminRequest,
    MessageOut,
    ProfileOut,
)
from app.services.admin import is_admin_email, is_root_admin_email, sync_user_role
from app.services import deployments
from app.services.weblab import close_weblab_session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
logger = logging.getLogger("fpga_remote_lab")


# ---- Members ----------------------------------------------------------

@router.get("/users", response_model=list[AdminUserSummary])
def list_members(db: Session = Depends(get_db)):
    """Every member with a usage summary. Aggregates are computed in two
    grouped queries (not per-user loops) so this stays one round trip
    each regardless of how many members exist."""
    users = db.scalars(select(User).order_by(User.id)).all()

    # completed sessions + distinct completed labs, per user
    completed_rows = db.execute(
        select(
            Reservation.user_id,
            func.count(Reservation.id),
            func.count(func.distinct(Reservation.lab_id)),
        )
        .where(Reservation.status == ReservationStatus.completed)
        .group_by(Reservation.user_id)
    ).all()
    completed = {uid: (sessions, labs) for uid, sessions, labs in completed_rows}

    total_rows = db.execute(
        select(Reservation.user_id, func.count(Reservation.id)).group_by(Reservation.user_id)
    ).all()
    totals = {uid: n for uid, n in total_rows}

    profile_ids = set(db.scalars(select(UserProfile.user_id)).all())

    result = []
    for u in users:
        sessions, labs = completed.get(u.id, (0, 0))
        result.append(
            AdminUserSummary(
                id=u.id,
                username=u.username,
                email=u.email,
                role=u.role,
                created_at=u.created_at,
                is_root_admin=is_root_admin_email(u.email),
                completed_labs=labs,
                completed_sessions=sessions,
                total_reservations=totals.get(u.id, 0),
                has_profile=u.id in profile_ids,
            )
        )
    return result


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def member_detail(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    # Admins see the whole profile regardless of is_public/hidden_fields -
    # those only gate peer-to-peer viewing (GET /api/profile/{username}),
    # not administration.
    profile_out = ProfileOut.model_validate(profile) if profile is not None else None

    rows = db.execute(
        select(Reservation, Lab.name)
        .join(Lab, Lab.id == Reservation.lab_id)
        .where(Reservation.user_id == user_id)
        .order_by(Reservation.created_at.desc())
    ).all()
    reservations = [
        AdminReservationOut(
            id=r.id,
            lab_id=r.lab_id,
            lab_name=lab_name,
            status=r.status,
            reservation_date=r.reservation_date,
            reservation_time=r.reservation_time,
            created_at=r.created_at,
            usage_start_time=r.usage_start_time,
            usage_end_time=r.usage_end_time,
        )
        for r, lab_name in rows
    ]

    return AdminUserDetail(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        created_at=user.created_at,
        is_root_admin=is_root_admin_email(user.email),
        profile=profile_out,
        reservations=reservations,
    )


@router.delete("/users/{user_id}", response_model=MessageOut)
def delete_member(
    user_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Delete a member. Reservations deliberately don't cascade (they're
    an audit trail) - by default this fails loudly (409) rather than
    silently erasing a user's usage history. Pass force=true (the admin
    panel does this after an explicit confirmation showing the session
    count) to delete the history along with the account, same as a user
    deleting their own account - see routers/profile.py::delete_my_account,
    which this mirrors."""
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if is_root_admin_email(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete a root administrator",
        )

    if force:
        reservations = db.scalars(select(Reservation).where(Reservation.user_id == user_id)).all()
        for reservation in reservations:
            if reservation.status == ReservationStatus.active and reservation.weblab_session_url:
                try:
                    close_weblab_session(
                        reservation.lab,
                        reservation.weblab_session_url,
                        backend_url=deployments.address_for(db, reservation.lab),
                    )
                except httpx.HTTPError:
                    logger.warning(
                        "Could not close hardware session for reservation %d while force-deleting user %d",
                        reservation.id,
                        user_id,
                    )
            db.delete(reservation)

    db.delete(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a user with existing reservation history",
        )

    return MessageOut(success=True, message=f"User {user.username} deleted")


# ---- Admin management -------------------------------------------------

@router.get("/admins", response_model=list[AdminEntry])
def list_admins(db: Session = Depends(get_db)):
    """Root config admins plus runtime-granted ones, each annotated with
    whether an account exists for the address yet."""
    entries: dict[str, AdminEntry] = {}

    def user_for(email: str) -> User | None:
        return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))

    from app.config import settings

    for email in settings.admin_emails:
        if not email.strip():
            continue
        u = user_for(email)
        entries[email.strip().lower()] = AdminEntry(
            email=email.strip(),
            is_root_admin=True,
            is_registered=u is not None,
            user_id=u.id if u else None,
            username=u.username if u else None,
            granted_at=None,
        )

    for row in db.scalars(select(AdminEmail).order_by(AdminEmail.created_at)).all():
        key = row.email.strip().lower()
        if key in entries:  # also a root admin - root annotation wins
            continue
        u = user_for(row.email)
        entries[key] = AdminEntry(
            email=row.email,
            is_root_admin=False,
            is_registered=u is not None,
            user_id=u.id if u else None,
            username=u.username if u else None,
            granted_at=row.created_at,
        )

    return list(entries.values())


@router.post("/admins", response_model=MessageOut)
def grant_admin(payload: GrantAdminRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    email = payload.email.strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a valid email address")

    if is_admin_email(db, email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That address is already an admin")

    db.add(AdminEmail(email=email, added_by_user_id=admin.id))

    # If the person is already registered, promote their account now;
    # otherwise the grant sits in the table until they register/log in and
    # sync_user_role picks it up.
    existing = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if existing is not None:
        existing.role = UserRole.admin

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That address is already an admin")

    if existing is not None:
        return MessageOut(success=True, message=f"{existing.username} is now an admin")
    return MessageOut(success=True, message=f"{email} will become an admin when they register")


@router.delete("/admins/{email}", response_model=MessageOut)
def revoke_admin(email: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    email = email.strip()
    if is_root_admin_email(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke a root administrator",
        )

    row = db.scalar(select(AdminEmail).where(func.lower(AdminEmail.email) == email.lower()))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That address is not a granted admin")

    db.delete(row)
    # Demote the matching account if there is one. Flush the delete first
    # so is_admin_email (used by sync_user_role) no longer sees the grant.
    db.flush()
    existing = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if existing is not None:
        sync_user_role(db, existing)
    db.commit()

    return MessageOut(success=True, message=f"Admin access revoked for {email}")
