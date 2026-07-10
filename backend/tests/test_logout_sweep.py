from unittest.mock import patch

from app.database import SessionLocal
from app.models import Reservation
from app.services.queue import sweep_logged_out_sessions
from tests.helpers import login, make_admin, register


def _create_lab(client):
    register(client, "admin", "admin@example.com")
    login(client, "admin")
    make_admin("admin")
    lab_id = client.post(
        "/api/labs", json={"name": "Arty Z7", "description": "FPGA board", "backend_url": "http://10.30.70.23:5003"}
    ).json()["id"]
    return lab_id


def _mark_session_opened(reservation_id, url="http://10.30.70.23:5003/foo/callback/fake-session-id"):
    """Simulate having already called GET /labs/{id}/access once, which is
    what sets weblab_session_url in real use."""
    db = SessionLocal()
    try:
        reservation = db.get(Reservation, reservation_id)
        reservation.weblab_session_url = url
        db.commit()
    finally:
        db.close()


def test_sweep_closes_a_reservation_whose_hardware_session_already_ended(client):
    """Regression test: clicking "Log out" *inside* the lab UI ends the
    session on the CT300 side immediately (labdiscoverylib's logout() /
    force_exit()), but our own Reservation row had no way to learn that -
    it stayed "active" (and kept occupying the board as far as our own
    booking logic was concerned) until session_duration_seconds fully
    elapsed on its own.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    _mark_session_opened(resv["id"])

    with patch("app.services.queue.is_weblab_session_finished", return_value=True) as mock_check:
        db = SessionLocal()
        try:
            closed = sweep_logged_out_sessions(db)
        finally:
            db.close()

    assert closed == 1
    mock_check.assert_called_once()

    mine = client.get("/api/reservations/mine").json()
    assert mine == []  # completed reservations don't show up here anymore


def test_sweep_leaves_a_still_running_session_alone(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    _mark_session_opened(resv["id"])

    with patch("app.services.queue.is_weblab_session_finished", return_value=False):
        db = SessionLocal()
        try:
            closed = sweep_logged_out_sessions(db)
        finally:
            db.close()

    assert closed == 0
    mine = client.get("/api/reservations/mine").json()
    assert mine[0]["status"] == "active"


def test_sweep_skips_reservations_that_never_opened_a_session(client):
    """An active reservation nobody has actually clicked Access on yet has
    no weblab_session_url and therefore nothing on the hardware side to
    poll - the sweep must not try (and must not error out)."""
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    with patch("app.services.queue.is_weblab_session_finished") as mock_check:
        db = SessionLocal()
        try:
            closed = sweep_logged_out_sessions(db)
        finally:
            db.close()

    assert closed == 0
    mock_check.assert_not_called()


def test_sweep_tolerates_an_unreachable_hardware_container(client):
    import httpx

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    _mark_session_opened(resv["id"])

    with patch("app.services.queue.is_weblab_session_finished", side_effect=httpx.ConnectError("unreachable")):
        db = SessionLocal()
        try:
            closed = sweep_logged_out_sessions(db)
        finally:
            db.close()

    assert closed == 0
    mine = client.get("/api/reservations/mine").json()
    assert mine[0]["status"] == "active"
