from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_admin
from app.models import Lab, Reservation, ReservationStatus, User
from app.schemas import LabCreate, LabOut

router = APIRouter(prefix="/labs", tags=["labs"])


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

    return [
        LabOut(
            id=lab.id,
            name=lab.name,
            description=lab.description,
            status=lab.status,
            queue_count=queue_count or 0,
        )
        for lab, queue_count in rows
    ]


@router.post("", response_model=LabOut, status_code=201)
def create_lab(payload: LabCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    # require_admin checks the role server-side - the old repo only hid the
    # "create lab" button in the UI and never verified this on the backend.
    lab = Lab(name=payload.name, description=payload.description)
    db.add(lab)
    db.commit()
    db.refresh(lab)
    return LabOut(id=lab.id, name=lab.name, description=lab.description, status=lab.status, queue_count=0)
