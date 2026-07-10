from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User, UserProfile
from app.schemas import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
def get_my_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.profile is None:
        # No row yet for a user who never edited their profile - return an
        # all-empty one rather than 404, since "no profile" isn't an error.
        return ProfileOut(full_name=None, school=None, department=None, age=None, bio=None, social_links=None)
    return ProfileOut.model_validate(user.profile)


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

    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)
