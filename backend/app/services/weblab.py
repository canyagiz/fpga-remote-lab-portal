from datetime import datetime, timezone

import httpx

from app.config import settings
from app.models import Lab, User

# Every CT300 hardware container bundles labdiscoverylib (LabsLand's
# WebLab-Deusto-compatible library) and exposes this session-creation REST
# endpoint under its fixed WEBLAB_BASE_URL ('/foo', same on all 4 labs).
# We call it with a plain HTTP request - this backend does not depend on
# or vendor labdiscoverylib/WebLab-Deusto itself, it just speaks the one
# REST call the container already answers.
#
# Without this handshake, redirecting a browser straight at the container's
# root hits its @requires_login guard, which - since no
# WEBLAB_UNAUTHORIZED_LINK is configured for our broker - falls back to the
# library's own generic docs page instead of the real experiment UI.
_SESSION_PATH = "/foo/ldl/sessions/"


class WeblabSessionError(RuntimeError):
    """The hardware container reachable but refused to start a session."""


def start_weblab_session(lab: Lab, user: User, duration_seconds: int, back_url: str) -> str:
    now = datetime.now(timezone.utc)
    response = httpx.post(
        f"{lab.backend_url}{_SESSION_PATH}",
        auth=(settings.weblab_username, settings.weblab_password),
        json={
            "request": {
                "locale": "en",
                "ldeReservationId": f"fpga-remote-lab-{user.id}-{lab.id}-{int(now.timestamp())}",
                "user": {},
                "server": {},
                "backUrl": back_url,
            },
            "laboratory": {"name": lab.name},
            "user": {
                "username": user.username,
                "unique": f"user-{user.id}",
                "fullName": user.username,
            },
            "schedule": {
                "start": now.isoformat(),
                "length": duration_seconds,
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if "url" not in data:
        raise WeblabSessionError(data.get("message", "Hardware container refused to start a session"))
    return data["url"]


def close_weblab_session(lab: Lab, session_id: str) -> None:
    """Force-end a session from the broker side - labdiscoverylib's own
    DELETE /sessions/{id} endpoint, whose docstring says exactly this is
    for: "kick one user out... when an administrator defines so, or when
    the assigned time is over."

    Used whenever *we* end a reservation (Finish, Cancel, or the expiry
    sweep noticing the allotted time ran out) instead of the user logging
    out from inside the lab UI itself - without this, the hardware
    session stays open: the browser tab that already had it loaded keeps
    working, and worse, a second user can be granted a fresh session on
    what our own database now considers a free board while the first
    session is still physically live on CT300.
    """
    session_id = session_id.rstrip("/").rsplit("/", 1)[-1]
    response = httpx.delete(
        f"{lab.backend_url}{_SESSION_PATH}{session_id}",
        auth=(settings.weblab_username, settings.weblab_password),
        timeout=10,
    )
    response.raise_for_status()


def is_weblab_session_finished(lab: Lab, session_id: str) -> bool:
    """Whether the hardware container itself already considers this
    session over - explicit in-lab logout (arty_lab_overlay/views.py's
    `/logout` route calls labdiscoverylib's logout(), which force-exits
    the session), idle timeout, or running out of allotted time.

    Polling this status endpoint is the protocol's own intended mechanism
    for a broker to learn this - there is no push notification back to us,
    so services/queue.py::sweep_logged_out_sessions calls this
    periodically for every reservation with an open session.
    """
    session_id = session_id.rstrip("/").rsplit("/", 1)[-1]
    response = httpx.get(
        f"{lab.backend_url}/foo/ldl/sessions/{session_id}/status",
        auth=(settings.weblab_username, settings.weblab_password),
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("should_finish") == -1
