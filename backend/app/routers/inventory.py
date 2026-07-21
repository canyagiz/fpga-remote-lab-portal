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
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import (
    Board,
    Device,
    FpgaFamily,
    Lab,
    LabDeployment,
    LabTemplate,
    Shuttle,
    ShuttleRole,
    User,
)
from app.schemas import (
    AgentReport,
    AgentReportAccepted,
    BoardCreate,
    BoardOut,
    CreateShuttleRequest,
    DeploymentCreate,
    DeploymentOut,
    DeviceOut,
    GapReportOut,
    LabTemplateCreate,
    LabTemplateOut,
    MessageOut,
    RequirementResultOut,
    ShuttleAddressUpdate,
    ShuttleEnrolled,
    ShuttleOut,
    UnclaimedDeviceOut,
)
from app.security import (
    generate_shuttle_token,
    parse_shuttle_token,
    verify_shuttle_secret,
)
from app.services import deployments, inventory, matching
from app.services import requirements as requirements_module

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


# ---- Boards ----------------------------------------------------------
#
# A board is the human half of the model: discovery finds a cable, a
# person says what is on the end of it. That step cannot be automated
# away - an IDCODE identifies silicon, not a board, and the USB-Blaster
# in this lab reports one code shared by three chip families.


def _board_out(db: Session, board: Board) -> BoardOut:
    # Resolved live rather than stored: the board is wherever its
    # programmer is currently being reported from.
    row = db.execute(
        select(Shuttle.id, Shuttle.name)
        .join(Device, Device.shuttle_id == Shuttle.id)
        .where(
            Device.usb_serial == board.programmer_serial,
            Device.is_present.is_(True),
        )
        .limit(1)
    ).first()
    return BoardOut(
        id=board.id,
        label=board.label,
        family=board.family.value,
        expected_idcode=board.expected_idcode,
        programmer_serial=board.programmer_serial,
        video_capture_serial=board.video_capture_serial,
        gpio_endpoint=board.gpio_endpoint,
        notes=board.notes,
        created_at=board.created_at,
        shuttle_id=row[0] if row else None,
        shuttle_name=row[1] if row else None,
    )


@admin_router.get("/boards", response_model=list[BoardOut])
def list_boards(db: Session = Depends(get_db)):
    boards = db.scalars(select(Board).order_by(Board.id)).all()
    return [_board_out(db, b) for b in boards]


@admin_router.get("/boards/unclaimed", response_model=list[UnclaimedDeviceOut])
def list_unclaimed(db: Session = Depends(get_db)):
    """Programmers that are attached but that no board has claimed.

    This is the queue an admin works through after someone plugs
    something in.
    """
    shuttles = {s.id: s.name for s in db.scalars(select(Shuttle))}
    return [
        UnclaimedDeviceOut(
            device_id=d.id,
            shuttle_id=d.shuttle_id,
            shuttle_name=shuttles.get(d.shuttle_id, "?"),
            usb_serial=d.usb_serial,
            product=d.product,
            manufacturer=d.manufacturer,
            signature=d.signature,
            sysfs_path=d.sysfs_path,
            jtag_chain=d.jtag_chain,
            first_seen_at=d.first_seen_at,
        )
        for d in matching.unclaimed_devices(db)
    ]


@admin_router.post("/boards", response_model=BoardOut, status_code=201)
def register_board(
    payload: BoardCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        family = FpgaFamily(payload.family)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Family must be one of: {', '.join(f.value for f in FpgaFamily)}",
        )

    # Refuse a serial nothing has ever reported. Almost always a typo,
    # and a board bound to a serial that does not exist would silently
    # never satisfy any requirement - failing now, with the reason, beats
    # failing later without one.
    seen = db.scalar(
        select(Device.id).where(Device.usb_serial == payload.programmer_serial).limit(1)
    )
    if seen is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No shuttle has reported a device with serial "
                f"{payload.programmer_serial!r}. Check the serial, or wait for the "
                "agent on that shuttle to report."
            ),
        )

    board = Board(
        label=payload.label.strip(),
        family=family,
        expected_idcode=payload.expected_idcode,
        programmer_serial=payload.programmer_serial,
        video_capture_serial=payload.video_capture_serial,
        gpio_endpoint=payload.gpio_endpoint,
        notes=payload.notes,
        registered_by_user_id=admin.id,
    )
    db.add(board)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That label, or that programmer serial, is already registered to a board",
        )
    db.refresh(board)
    return _board_out(db, board)


@admin_router.delete("/boards/{board_id}", response_model=MessageOut)
def delete_board(board_id: int, db: Session = Depends(get_db)):
    board = db.get(Board, board_id)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")
    label = board.label
    db.delete(board)
    db.commit()
    return MessageOut(success=True, message=f"Board {label} deregistered")


# ---- Lab templates ---------------------------------------------------


@admin_router.get("/templates", response_model=list[LabTemplateOut])
def list_templates(db: Session = Depends(get_db)):
    return list(db.scalars(select(LabTemplate).order_by(LabTemplate.id)))


@admin_router.post("/templates", response_model=LabTemplateOut, status_code=201)
def create_template(
    payload: LabTemplateCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # Parse before storing, so a template can never hold a shape the
    # matching engine will later choke on. The error text names the
    # accepted types rather than leaking a pydantic traceback.
    try:
        requirements_module.parse(payload.requirements)
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid requirements: {err.errors()[0].get('msg', 'unrecognised shape')}",
        )

    template = LabTemplate(
        name=payload.name.strip(),
        description=payload.description,
        requirements=payload.requirements,
        created_by_user_id=admin.id,
    )
    db.add(template)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A template with that name already exists"
        )
    db.refresh(template)
    return template


@admin_router.delete("/templates/{template_id}", response_model=MessageOut)
def delete_template(template_id: int, db: Session = Depends(get_db)):
    template = db.get(LabTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    name = template.name
    db.delete(template)
    db.commit()
    return MessageOut(success=True, message=f"Template {name} deleted")


# ---- The gap report --------------------------------------------------


def _gap_out(report: matching.GapReport) -> GapReportOut:
    return GapReportOut(
        shuttle_id=report.shuttle_id,
        shuttle_name=report.shuttle_name,
        template_id=report.template_id,
        template_name=report.template_name,
        deployable=report.deployable,
        missing_count=report.missing_count,
        results=[
            RequirementResultOut(type=r.type, status=r.status.value, message=r.message)
            for r in report.results
        ],
    )


@admin_router.get("/templates/{template_id}/gaps", response_model=list[GapReportOut])
def template_gaps(template_id: int, db: Session = Depends(get_db)):
    """Where can this lab run, and what is stopping it everywhere else?"""
    template = db.get(LabTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return [_gap_out(r) for r in matching.evaluate_across_fleet(db, template)]


@admin_router.get("/gaps", response_model=list[GapReportOut])
def all_gaps(db: Session = Depends(get_db)):
    """Every template against every shuttle - the fleet overview."""
    reports = []
    for template in db.scalars(select(LabTemplate).order_by(LabTemplate.id)):
        reports.extend(matching.evaluate_across_fleet(db, template))
    return [_gap_out(r) for r in reports]


@admin_router.get("/unused", response_model=list[DeviceOut])
def unused(db: Session = Depends(get_db)):
    """Hardware no template has any use for - the spare side of the report."""
    return matching.unused_devices(db)


# ---- Deployments -----------------------------------------------------
#
# Binding a catalogue entry to a physical board. Until one of these
# exists for a lab, that lab behaves exactly as it always has.


def _deployment_out(db: Session, deployment: LabDeployment) -> DeploymentOut:
    resolved = deployments.resolve(db, deployment.lab)
    return DeploymentOut(
        id=deployment.id,
        lab_id=deployment.lab_id,
        lab_name=deployment.lab.name,
        template_id=deployment.template_id,
        template_name=deployment.template.name,
        board_id=deployment.board_id,
        board_label=deployment.board.label,
        port=deployment.port,
        is_enabled=deployment.is_enabled,
        created_at=deployment.created_at,
        shuttle_id=resolved.shuttle.id if resolved and resolved.shuttle else None,
        shuttle_name=resolved.shuttle.name if resolved and resolved.shuttle else None,
        backend_url=resolved.backend_url if resolved else None,
        available=bool(resolved and resolved.available),
        reason=resolved.reason if resolved else None,
    )


@admin_router.get("/deployments", response_model=list[DeploymentOut])
def list_deployments(db: Session = Depends(get_db)):
    rows = db.scalars(select(LabDeployment).order_by(LabDeployment.id)).all()
    return [_deployment_out(db, d) for d in rows]


@admin_router.post("/deployments", response_model=DeploymentOut, status_code=201)
def create_deployment(payload: DeploymentCreate, db: Session = Depends(get_db)):
    """Bind a lab to a board. This is the moment a lab starts being
    governed by the inventory instead of by its static backend_url."""
    lab = db.get(Lab, payload.lab_id)
    if lab is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lab not found")
    template = db.get(LabTemplate, payload.template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    board = db.get(Board, payload.board_id)
    if board is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")

    deployment = LabDeployment(
        lab_id=lab.id,
        template_id=template.id,
        board_id=board.id,
        port=payload.port,
    )
    db.add(deployment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That lab already has a deployment - delete it first to rebind",
        )
    db.refresh(deployment)
    return _deployment_out(db, deployment)


@admin_router.post("/deployments/{deployment_id}/enable", response_model=DeploymentOut)
def set_deployment_enabled(
    deployment_id: int, enabled: bool = True, db: Session = Depends(get_db)
):
    """Take a lab in or out of service without unbinding it."""
    deployment = db.get(LabDeployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    deployment.is_enabled = enabled
    db.commit()
    db.refresh(deployment)
    return _deployment_out(db, deployment)


@admin_router.delete("/deployments/{deployment_id}", response_model=MessageOut)
def delete_deployment(deployment_id: int, db: Session = Depends(get_db)):
    """Unbind. The lab reverts to its static backend_url, exactly as
    before it was ever deployed - which is what makes this reversible."""
    deployment = db.get(LabDeployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    name = deployment.lab.name
    db.delete(deployment)
    db.commit()
    return MessageOut(
        success=True, message=f"{name} is no longer bound to a board; its static URL applies again"
    )


@admin_router.put("/shuttles/{shuttle_id}/address", response_model=ShuttleOut)
def set_shuttle_address(
    shuttle_id: int, payload: ShuttleAddressUpdate, db: Session = Depends(get_db)
):
    """Set where this shuttle's lab containers are reached.

    Kept as an explicit admin action rather than something an agent can
    report, because this is the value student browsers are ultimately
    sent to.
    """
    shuttle = db.get(Shuttle, shuttle_id)
    if shuttle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shuttle not found")
    shuttle.address = payload.address.strip()
    db.commit()
    db.refresh(shuttle)
    return _shuttle_out(db, shuttle)
