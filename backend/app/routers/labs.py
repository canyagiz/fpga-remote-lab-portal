from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import Lab, Reservation, ReservationStatus, User
from app.schemas import LabAccessOut, LabCreate, LabOut
from app.services.availability import next_available_at
from app.services.weblab import WeblabSessionError, start_weblab_session

router = APIRouter(prefix="/labs", tags=["labs"])


def _to_out(db: Session, lab: Lab, queue_count: int) -> LabOut:
    available_at = next_available_at(db, lab.id)
    return LabOut(
        id=lab.id,
        name=lab.name,
        description=lab.description,
        status=lab.status,
        queue_count=queue_count,
        image_url=lab.image_url,
        keywords=lab.keywords,
        features=lab.features,
        is_public=lab.is_public,
        next_available_at=available_at.replace(tzinfo=timezone.utc) if available_at is not None else None,
    )


@router.get("", response_model=list[LabOut])
def list_labs(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(
        select(
            Lab,
            func.count(Reservation.id).filter(Reservation.status == ReservationStatus.pending).label(
                "queue_count"
            ),
        )
        .outerjoin(Reservation, Reservation.lab_id == Lab.id)
        .group_by(Lab.id)
        .order_by(Lab.id)
    ).all()

    return [_to_out(db, lab, queue_count or 0) for lab, queue_count in rows]


@router.post("", response_model=LabOut, status_code=201)
def create_lab(payload: LabCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    # require_admin checks the role server-side - the old repo only hid the
    # "create lab" button in the UI and never verified this on the backend.
    lab = Lab(
        name=payload.name,
        description=payload.description,
        image_url=payload.image_url,
        backend_url=payload.backend_url,
        keywords=payload.keywords,
        features=payload.features,
        is_public=payload.is_public,
    )
    db.add(lab)
    db.commit()
    db.refresh(lab)
    return _to_out(db, lab, 0)


@router.get("/{lab_id}/access", response_model=LabAccessOut)
def access_lab(
    lab_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    lab = db.get(Lab, lab_id)
    if lab is None or lab.backend_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lab not found")

    reservation = db.scalar(
        select(Reservation).where(
            Reservation.lab_id == lab_id,
            Reservation.user_id == user.id,
            Reservation.status == ReservationStatus.active,
        )
    )
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You need an active reservation to access this lab",
        )

    # Reuse the session started for this reservation if one already
    # exists - each fresh call otherwise opens a brand-new WebLab session
    # on the same physical board, so opening several tabs (or clicking
    # Access more than once) would give each of them independent,
    # simultaneous control over the same hardware.
    if reservation.weblab_session_url is None:
        if reservation.usage_start_time is not None:
            elapsed = (datetime.utcnow() - reservation.usage_start_time).total_seconds()
        else:
            elapsed = 0
        remaining = max(int(settings.session_duration_seconds - elapsed), 30)
        back_url = f"{str(request.base_url).rstrip('/')}/labs"

        try:
            session_url = start_weblab_session(lab, user, duration_seconds=remaining, back_url=back_url)
        except (httpx.HTTPError, WeblabSessionError) as err:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not start a session on the lab hardware: {err}",
            )
        reservation.weblab_session_url = session_url
        db.commit()
    else:
        session_url = reservation.weblab_session_url

    # Send the browser through our own reverse proxy (see
    # routers/hardware_proxy.py) instead of straight at the bare CT300
    # host:port - the container's own root-relative asset/AJAX URLs only
    # resolve correctly against whatever origin the browser is currently
    # on, and CT300 alone doesn't serve them under this origin.
    parsed_session_url = httpx.URL(session_url)
    proxied_path = f"/hw/{lab.id}{parsed_session_url.path}"
    if parsed_session_url.query:
        proxied_path = f"{proxied_path}?{parsed_session_url.query.decode()}"
    proxied_url = f"{str(request.base_url).rstrip('/')}{proxied_path}"

    return LabAccessOut(backend_url=proxied_url)
