import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lab, Reservation, ReservationStatus

router = APIRouter(tags=["hardware-proxy"])
logger = logging.getLogger("fpga_remote_lab")

# Headers that must not be copied verbatim between the browser <-> our
# proxy <-> the CT300 container hop (either meaningless out of context, or
# managed automatically by the ASGI server / httpx for the new hop).
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
    "host",
}


@router.api_route("/hw/{lab_id}/logout", methods=["POST"])
async def proxy_logout_and_close_reservation(lab_id: int, request: Request, db: Session = Depends(get_db)):
    """
    The *only* hardware-container traffic still routed to this app - see
    [[project_ct210_migration_plan]] for why the rest moved to nginx
    (nginx's own reverse-proxy config now forwards /hw/{lab_id}/* and
    /labfiles/* straight to CT300, with an explicit exception carving
    this one path out to us first).

    The in-lab "Log out" button (arty_lab_overlay's /logout route,
    calling labdiscoverylib's logout()/force_exit()) ends the session on
    CT300 immediately, but our own Reservation row - and therefore the
    "occupied" state everyone else sees - has no way to learn that on its
    own. Buffering this one (small, one-line JSON) response instead of
    streaming it lets us inspect it and, on success, close the lab's
    active reservation in the very same request - no waiting for the
    background sweep (services/queue.py::sweep_logged_out_sessions, still
    in place as a fallback for a closed tab or dropped connection that
    never sends this request at all).
    """
    lab = db.get(Lab, lab_id)
    if lab is None or lab.backend_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lab not found")

    target_url = f"{lab.backend_url}/logout"
    upstream_headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
    upstream_headers.update(
        {
            "X-Forwarded-Prefix": f"/hw/{lab_id}",
            "X-Forwarded-Host": request.headers.get("host", ""),
            "X-Forwarded-Proto": request.url.scheme,
        }
    )
    body = await request.body()

    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        upstream_response = await client.request(
            request.method, target_url, headers=upstream_headers, params=request.query_params, content=body
        )

    if upstream_response.status_code == 200:
        try:
            payload = upstream_response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("error") is False:
            reservation = db.scalar(
                select(Reservation).where(
                    Reservation.lab_id == lab_id,
                    Reservation.status == ReservationStatus.active,
                )
            )
            if reservation is not None:
                reservation.status = ReservationStatus.completed
                reservation.usage_end_time = datetime.utcnow()
                db.commit()
                logger.info("Closed reservation %d immediately after in-lab logout", reservation.id)

    response_headers = {
        k: v for k, v in upstream_response.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=upstream_response.content, status_code=upstream_response.status_code, headers=response_headers
    )
