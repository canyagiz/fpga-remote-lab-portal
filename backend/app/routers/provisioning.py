"""The setup wizard's provisioning endpoints.

Sits alongside the fleet admin routes (same require_admin dependency) but
kept in its own module because it does something none of the others do:
run an external process against a remote machine. Enrolment
(routers/inventory.py) records a shuttle and mints its token; this turns
that shuttle into a working node.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_admin
from app.models import Shuttle
from app.schemas import ProvisionJobStarted, ProvisionJobStatus, ProvisionRequest
from app.services import provisioning

router = APIRouter(
    prefix="/admin/fleet",
    tags=["provisioning"],
    dependencies=[Depends(require_admin)],
)


def _status(job) -> ProvisionJobStatus:
    return ProvisionJobStatus(
        job_id=job.job_id,
        shuttle_id=job.shuttle_id,
        status=job.status,
        returncode=job.returncode,
        started_at=job.started_at,
        finished_at=job.finished_at,
        log=job.snapshot(),
    )


@router.post(
    "/shuttles/{shuttle_id}/provision",
    response_model=ProvisionJobStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
def provision_shuttle(
    shuttle_id: int,
    payload: ProvisionRequest,
    db: Session = Depends(get_db),
):
    """Start provisioning an already-enrolled shuttle.

    Returns immediately with a job id; the wizard polls the status route
    below for the live log. The shuttle's token is rotated and injected by
    the playbook, so the admin never has to copy it.
    """
    shuttle = db.get(Shuttle, shuttle_id)
    if shuttle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shuttle not found")
    try:
        job = provisioning.start_provision(db, shuttle, payload)
    except provisioning.ProvisionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return ProvisionJobStarted(
        job_id=job.job_id, shuttle_id=shuttle_id, status=job.status
    )


@router.get(
    "/shuttles/{shuttle_id}/provision/{job_id}",
    response_model=ProvisionJobStatus,
)
def provision_status(
    shuttle_id: int,
    job_id: str,
    db: Session = Depends(get_db),
):
    """The wizard polls this for status and the accumulated log."""
    job = provisioning.get_job(job_id)
    if job is None or job.shuttle_id != shuttle_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such provisioning job")
    return _status(job)
