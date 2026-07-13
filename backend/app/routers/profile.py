from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User, UserProfile
from app.schemas import ProfileOut, ProfileUpdate, PublicProfileOut

router = APIRouter(prefix="/profile", tags=["profile"])

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
