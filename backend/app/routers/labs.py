from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import Lab, Reservation, ReservationStatus, User, UserRole
from app.schemas import LabAccessOut, LabCreate, LabOut
from app.services.availability import next_available_at
from app.services import deployments
from app.services.weblab import WeblabSessionError, start_weblab_session

router = APIRouter(prefix="/labs", tags=["labs"])


def _to_out(db: Session, lab: Lab, queue_count: int) -> LabOut:
    available_at = next_available_at(db, lab.id)
    # None for a lab with no deployment, which is every lab until an
    # admin binds one - see services/deployments.py.
    resolved = deployments.resolve(db, lab)
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
        guide_url=lab.guide_url,
        deployment_status=resolved.status if resolved else None,
        unavailable_reason=resolved.reason if resolved else None,
    )


@router.get("", response_model=list[LabOut])
def list_labs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
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

    entries = [_to_out(db, lab, queue_count or 0) for lab, queue_count in rows]

    # A deployed lab whose hardware is not currently fit to serve is
    # withdrawn from the catalogue rather than left bookable - today that
    # failure is discovered by a student, mid-session, as a black video
    # feed. Admins keep seeing it, annotated with why, since hiding a
    # fault from the people who fix it helps nobody.
    if user.role is UserRole.admin:
        return entries
    return [e for e in entries if e.deployment_status != "unavailable"]


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

    # Enforced here as well as in the listing: hiding a lab from the
    # catalogue is not access control, and a user holding a reservation
    # from before the hardware broke still has a working link to it.
    resolved = deployments.resolve(db, lab)
    if resolved is not None and not resolved.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"This lab is temporarily unavailable: {resolved.reason}",
        )

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
        # Based on hardware_started_at, not usage_start_time: usage_start_time
        # marks when the reservation was claimed (and keeps the board's
        # calendar window and expiry sweep anchored to that instant - see
        # models.py), but the hardware clock itself must only start once a
        # session actually opens. Otherwise a failed attempt below (a
        # deployment-health rejection above, CT300 mid-restart, ...) would
        # already have "spent" time against a session the user was never
        # let into, and every retry would be handed a shorter duration.
        if reservation.hardware_started_at is not None:
            elapsed = (datetime.utcnow() - reservation.hardware_started_at).total_seconds()
        else:
            elapsed = 0
        remaining = max(int(settings.session_duration_seconds - elapsed), 30)
        back_url = f"{str(request.base_url).rstrip('/')}/labs"

        try:
            session_url = start_weblab_session(
                lab,
                user,
                duration_seconds=remaining,
                back_url=back_url,
                # Health already checked above, so this is the address of
                # the shuttle currently holding the board.
                backend_url=resolved.backend_url if resolved else None,
            )
        except (httpx.HTTPError, WeblabSessionError) as err:
            # This reservation never opened a session (weblab_session_url
            # is still None, or this branch would not have run) - it is
            # exactly the "dead end" access-now already refuses to create
            # when the health check fails up front. The health check
            # cannot predict every failure, though - reachable-and-present
            # hardware can still fail to actually initialize - so the same
            # rule is enforced here too: a reservation that never got in
            # is cancelled rather than left "active" for the user to
            # notice and clear themselves.
            reservation.status = ReservationStatus.cancelled
            # Recorded on the deployment, not just this reservation, so
            # it survives past this one cancelled row and shows up on the
            # fleet page - the periodic health check that gates access
            # only knows the hardware is present and signalling; it has
            # no way to see a real session fail to initialize, so without
            # this an admin only learns about it if a student says so.
            if resolved is not None and resolved.deployment is not None:
                resolved.deployment.last_access_error = str(err)
                resolved.deployment.last_access_error_at = datetime.utcnow()
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not start a session on the lab hardware: {err}",
            )
        reservation.weblab_session_url = session_url
        reservation.hardware_started_at = datetime.utcnow()
        # A session just opened successfully - whatever the last failure
        # was, it no longer describes this deployment's current state.
        if resolved is not None and resolved.deployment is not None:
            resolved.deployment.last_access_error = None
            resolved.deployment.last_access_error_at = None
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
