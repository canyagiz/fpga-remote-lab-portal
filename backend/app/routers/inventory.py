"""Fleet inventory: the agent's one endpoint, plus admin management.

Two audiences with deliberately different powers:

  * Agents authenticate with a per-node bearer token and may call
    exactly one route - POST /inventory/report. A stolen agent token
    buys the ability to lie about one shuttle's hardware and nothing
    else: it cannot read users, publish a lab, or see another shuttle.
  * Admins (the existing root-admin allowlist) enrol and remove
    shuttles and read the whole fleet.

Enrolment is an explicit administrative act. There is no route by which
a machine can register itself, because "anything that can reach the API
becomes part of the fleet" is not a trust model.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import Device, Shuttle, ShuttleRole, User
from app.schemas import (
    AgentReport,
    AgentReportAccepted,
    CreateShuttleRequest,
    DeviceOut,
    MessageOut,
    ShuttleEnrolled,
    ShuttleOut,
)
from app.security import (
    generate_shuttle_token,
    parse_shuttle_token,
    verify_shuttle_secret,
)
from app.services import inventory

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _shuttle_out(db: Session, shuttle: Shuttle) -> ShuttleOut:
    device_count = db.scalar(
        select(func.count(Device.id)).where(
            Device.shuttle_id == shuttle.id, Device.is_present.is_(True)
        )
    )
    return ShuttleOut(
        id=shuttle.id,
        name=shuttle.name,
        hostname=shuttle.hostname,
        role=shuttle.role.value,
        agent_version=shuttle.agent_version,
        last_report_at=shuttle.last_report_at,
        created_at=shuttle.created_at,
        status=inventory.shuttle_status(shuttle),
        device_count=device_count or 0,
    )


# ---- Agent-facing ----------------------------------------------------

def authenticate_agent(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Shuttle:
    """Resolve which shuttle is reporting, from its bearer token.

    Every failure returns the same 401 with the same message. Telling a
    caller whether the shuttle id existed, or whether only the secret
    was wrong, would turn this into an oracle for enumerating the fleet.
    """
    unauthorised = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid agent token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorised

    parsed = parse_shuttle_token(authorization.split(" ", 1)[1].strip())
    if parsed is None:
        raise unauthorised

    shuttle_id, secret = parsed
    shuttle = db.get(Shuttle, shuttle_id)
    if shuttle is None or not verify_shuttle_secret(secret, shuttle.token_hash):
        raise unauthorised

    return shuttle


@router.post("/report", response_model=AgentReportAccepted)
def report(
    payload: AgentReport,
    db: Session = Depends(get_db),
    shuttle: Shuttle = Depends(authenticate_agent),
):
    """The only route an agent may call.

    Note what is NOT taken from the body: which shuttle this is. That
    comes from the token alone - accepting a self-declared identity here
    would let any agent overwrite any other shuttle's inventory.
    """
    count, notices = inventory.ingest(db, shuttle, payload)
    return AgentReportAccepted(
        shuttle_id=shuttle.id, devices_recorded=count, notices=notices
    )


# ---- Admin-facing ----------------------------------------------------

admin_router = APIRouter(
    prefix="/admin/fleet", tags=["fleet"], dependencies=[Depends(require_admin)]
)


@admin_router.get("/shuttles", response_model=list[ShuttleOut])
def list_shuttles(db: Session = Depends(get_db)):
    shuttles = db.scalars(select(Shuttle).order_by(Shuttle.id)).all()
    return [_shuttle_out(db, s) for s in shuttles]


@admin_router.post("/shuttles", response_model=ShuttleEnrolled, status_code=201)
def enrol_shuttle(
    payload: CreateShuttleRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admit a machine to the fleet and mint its token.

    The token is returned here and nowhere else - only its hash is
    stored, so this response is the single opportunity to capture it.
    """
    try:
        role = ShuttleRole(payload.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role must be one of: {', '.join(r.value for r in ShuttleRole)}",
        )

    shuttle = Shuttle(
        name=payload.name.strip(),
        role=role,
        token_hash="",  # replaced below, once the row has an id
        enrolled_by_user_id=admin.id,
    )
    db.add(shuttle)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A shuttle with that name already exists",
        )

    # The id has to exist before the token can embed it, hence flush
    # first and fill the hash in second - both inside one transaction, so
    # a shuttle row with an empty token_hash can never be committed.
    token, token_hash = generate_shuttle_token(shuttle.id)
    shuttle.token_hash = token_hash
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A shuttle with that name already exists",
        )
    db.refresh(shuttle)

    return ShuttleEnrolled(shuttle=_shuttle_out(db, shuttle), token=token)


@admin_router.post("/shuttles/{shuttle_id}/rotate-token", response_model=ShuttleEnrolled)
def rotate_token(shuttle_id: int, db: Session = Depends(get_db)):
    """Issue a new token and invalidate the old one immediately.

    The agent stops being able to report until it is reconfigured - that
    is the point, and it is the only remedy available if a token leaks,
    since the stored hash cannot be turned back into the original.
    """
    shuttle = db.get(Shuttle, shuttle_id)
    if shuttle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shuttle not found")

    token, token_hash = generate_shuttle_token(shuttle.id)
    shuttle.token_hash = token_hash
    db.commit()
    db.refresh(shuttle)
    return ShuttleEnrolled(shuttle=_shuttle_out(db, shuttle), token=token)


@admin_router.delete("/shuttles/{shuttle_id}", response_model=MessageOut)
def remove_shuttle(shuttle_id: int, db: Session = Depends(get_db)):
    shuttle = db.get(Shuttle, shuttle_id)
    if shuttle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shuttle not found")
    name = shuttle.name
    # Devices cascade: they describe this shuttle's hardware and mean
    # nothing without it. Any human-authored Board record will reference
    # a serial rather than a device row, so nothing hand-entered is lost.
    db.delete(shuttle)
    db.commit()
    return MessageOut(success=True, message=f"Shuttle {name} removed from the fleet")


@admin_router.get("/devices", response_model=list[DeviceOut])
def list_devices(
    shuttle_id: int | None = None,
    include_absent: bool = False,
    db: Session = Depends(get_db),
):
    query = select(Device).order_by(Device.shuttle_id, Device.id)
    if shuttle_id is not None:
        query = query.where(Device.shuttle_id == shuttle_id)
    if not include_absent:
        query = query.where(Device.is_present.is_(True))
    return list(db.scalars(query))
