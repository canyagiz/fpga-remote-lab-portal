import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Reservation, ReservationStatus, User, UserProfile
from app.schemas import DeleteAccountRequest, MessageOut, ProfileOut, ProfileUpdate, PublicProfileOut
from app.security import verify_password
from app.services import deployments
from app.services.weblab import close_weblab_session

router = APIRouter(prefix="/profile", tags=["profile"])
logger = logging.getLogger("fpga_remote_lab")

_PROFILE_FIELDS = ("full_name", "school", "department", "age", "bio", "social_links")


@router.get("", response_model=ProfileOut)
def get_my_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.profile is None:
        # No row yet for a user who never edited their profile - return an
        # all-empty one rather than 404, since "no profile" isn't an error.
        return ProfileOut(
            full_name=None, school=None, department=None, age=None, bio=None, social_links=None,
            is_public=True, hidden_fields=None,
        )
    return ProfileOut.model_validate(user.profile)


@router.get("/{username}", response_model=PublicProfileOut)
def get_public_profile(
    username: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """Any other signed-in user's profile - reachable by tapping a name on
    the Calendar. Any authenticated user can view any other's (this is an
    internal university lab tool, not a public site) - a deliberate
    change from the Calendar's own username-only design, made at the
    user's explicit request.

    Respects the profile owner's own privacy settings: is_public is a
    master switch (False hides everything, full stop), and hidden_fields
    is a finer-grained per-field opt-out that only applies while
    is_public is True - see models.py::UserProfile.
    """
    target = db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target.profile is None or not target.profile.is_public:
        return PublicProfileOut(username=target.username, is_public=False)

    profile = target.profile
    hidden = set(profile.hidden_fields or [])
    fields = {k: (None if k in hidden else getattr(profile, k)) for k in _PROFILE_FIELDS}
    if fields["social_links"]:
        # Per-platform opt-out, e.g. "social:github" - independent of
        # hiding the whole social_links block via the "social_links" key.
        fields["social_links"] = {
            platform: url
            for platform, url in fields["social_links"].items()
            if f"social:{platform}" not in hidden
        } or None
    return PublicProfileOut(username=target.username, is_public=True, **fields)


@router.put("", response_model=ProfileOut)
def update_my_profile(
    payload: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if user.profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    else:
        profile = user.profile

    profile.full_name = payload.full_name
    profile.school = payload.school
    profile.department = payload.department
    profile.age = payload.age
    profile.bio = payload.bio
    profile.social_links = payload.social_links
    profile.is_public = payload.is_public
    profile.hidden_fields = payload.hidden_fields

    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.delete("", response_model=MessageOut)
def delete_my_account(
    payload: DeleteAccountRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Irreversibly delete the signed-in user's own account and all of
    their data. Requires the account password to confirm identity (the
    session cookie is a long-lived sliding window - see config.py).

    Reservations deliberately have no ON DELETE CASCADE (they're a lab
    usage/audit trail for admins), so they're removed explicitly here.
    The profile, 2FA codes, and login events do cascade. A live hardware
    session (an active reservation that opened the board) is closed on
    CT300 first so the board isn't left locked - best-effort, an
    unreachable container shouldn't block the user from deleting.
    """
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    reservations = db.scalars(select(Reservation).where(Reservation.user_id == user.id)).all()
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
                    "Could not close hardware session for reservation %d while deleting user %d",
                    reservation.id,
                    user.id,
                )
        db.delete(reservation)

    username = user.username
    db.delete(user)
    db.commit()

    # Drop the now-orphaned session so the browser is signed out.
    request.session.clear()
    return MessageOut(success=True, message=f"Account {username} deleted")
