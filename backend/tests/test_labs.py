from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.weblab import WeblabSessionError
from tests.helpers import login, make_admin, register


def _create_lab(client, **overrides):
    register(client, "admin", "admin@example.com")
    login(client, "admin")
    make_admin("admin")
    payload = {
        "name": "Arty Z7",
        "description": "FPGA board",
        "backend_url": "http://10.30.70.23:5003",
        "is_public": True,
    }
    payload.update(overrides)
    return client.post("/api/labs", json=payload).json()["id"]


def test_seeded_lab_catalog_comes_from_labs_yaml(client):
    """The 4 real labs are seeded from backend/labs.yaml on startup (see
    app/main.py::_load_lab_catalog) - a regression test for that loader,
    not for any particular lab's content."""
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    labs = client.get("/api/labs").json()
    assert len(labs) == 4
    arty = next(lab for lab in labs if lab["name"] == "Arty Z7 Lab")
    assert arty["is_public"] is True
    assert arty["guide_url"] == "/guides/arty-prerequest.html"
    # Named rather than counted: a bare count said only "one of them
    # changed" when Cyclone IV was published, which is the least useful
    # version of that message. This says which labs are meant to be
    # public, so making another one public fails with the answer in the
    # diff.
    assert {lab["name"] for lab in labs if lab["is_public"]} == {
        "Cyclone IV Lab",
        "Arty Z7 Lab",
    }


def test_list_labs_includes_new_metadata_fields(client):
    lab_id = _create_lab(client, keywords=["fpga", "xilinx"], features=["feature1"])

    labs = client.get("/api/labs").json()
    created = next(lab for lab in labs if lab["id"] == lab_id)
    assert "backend_url" not in created  # never exposed via the list endpoint
    assert created["is_public"] is True
    assert created["keywords"] == ["fpga", "xilinx"]
    assert created["features"] == ["feature1"]


def test_next_available_at_is_null_for_a_free_board(client):
    lab_id = _create_lab(client)
    labs = client.get("/api/labs").json()
    created = next(lab for lab in labs if lab["id"] == lab_id)
    assert created["next_available_at"] is None


def test_next_available_at_reflects_the_active_session_end(client):
    """next_available_at reflects when the reservation's occupied window
    ends (usage_start_time + session length, set the moment the board is
    claimed - see services/availability.py), not session_ends_at, which
    only appears once the hardware session actually opens (see
    test_failed_hardware_start_does_not_start_the_session_clock) and isn't
    set here since this test never calls /access."""
    from app.config import settings

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    assert resv["session_ends_at"] is None
    usage_start = datetime.fromisoformat(resv["usage_start_time"])
    expected_end = usage_start + timedelta(seconds=settings.session_duration_seconds)

    labs = client.get("/api/labs").json()
    created = next(lab for lab in labs if lab["id"] == lab_id)
    assert datetime.fromisoformat(created["next_available_at"]) == expected_end


def test_next_available_at_skips_past_back_to_back_scheduled_reservations(client):
    """If someone has already booked the slot right after the active
    session ends, the next real opening is after *that* slot too - not
    the moment the current session finishes.

    The follow-up slot is inserted directly in the DB (not through
    POST /reservations) because it sits well under the API's own
    min-advance-notice window in this test's compressed timeline - that
    creation-time rule is already covered by
    test_reservation_requires_minimum_advance_notice; this test is only
    about next_available_at's own chaining logic.
    """
    from app.config import settings
    from app.database import SessionLocal
    from app.models import Reservation, ReservationStatus, User

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    # session_ends_at isn't set yet (no /access call was made - see
    # test_next_available_at_reflects_the_active_session_end), so derive
    # the reservation's occupied-window end the same way availability.py
    # does: usage_start_time + session length.
    usage_start = datetime.fromisoformat(resv["usage_start_time"]).replace(tzinfo=None)
    session_end = usage_start + timedelta(seconds=settings.session_duration_seconds)

    register(client, "user2", "user2@example.com")

    db = SessionLocal()
    try:
        user2_id = db.query(User).filter_by(username="user2").first().id
        db.add(
            Reservation(
                user_id=user2_id,
                lab_id=lab_id,
                reservation_date=session_end.date(),
                reservation_time=session_end.time(),
                status=ReservationStatus.pending,
            )
        )
        db.commit()
    finally:
        db.close()

    labs = client.get("/api/labs").json()
    created = next(lab for lab in labs if lab["id"] == lab_id)
    assert created["next_available_at"] != resv["session_ends_at"]
    assert datetime.fromisoformat(created["next_available_at"]).replace(tzinfo=None) > session_end


def test_access_denied_without_active_reservation(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    response = client.get(f"/api/labs/{lab_id}/access")
    assert response.status_code == 403


def test_access_granted_after_taking_a_free_board(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    # The hardware container's own session-start API isn't reachable from
    # tests (and shouldn't be hit for real here) - only the reservation
    # gate (the part this endpoint is actually responsible for) is under
    # test; the HTTP handshake itself is exercised by start_weblab_session
    # in isolation, not through the real network.
    with patch(
        "app.routers.labs.start_weblab_session",
        return_value="http://10.30.70.23:5003/foo/callback/fake-session-id",
    ) as mock_start:
        response = client.get(f"/api/labs/{lab_id}/access")
    assert response.status_code == 200
    # The raw CT300 URL is rewritten to go through our own /hw/{lab_id}
    # reverse proxy (see routers/hardware_proxy.py) - the browser should
    # never be pointed straight at the bare hardware host:port.
    assert response.json()["backend_url"] == f"http://testserver/hw/{lab_id}/foo/callback/fake-session-id"
    mock_start.assert_called_once()


def test_access_reuses_cached_session_on_repeated_calls(client):
    """Regression test: every call to /access used to start a brand-new
    WebLab session on the same physical board, so opening several tabs (or
    just clicking Access more than once) gave each of them independent,
    simultaneous control over the same hardware. The session must now be
    started once per reservation and reused after that.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    with patch(
        "app.routers.labs.start_weblab_session",
        return_value="http://10.30.70.23:5003/foo/callback/fake-session-id",
    ) as mock_start:
        first = client.get(f"/api/labs/{lab_id}/access")
        second = client.get(f"/api/labs/{lab_id}/access")
        third = client.get(f"/api/labs/{lab_id}/access")

    assert first.status_code == second.status_code == third.status_code == 200
    assert first.json()["backend_url"] == second.json()["backend_url"] == third.json()["backend_url"]
    mock_start.assert_called_once()


def test_access_returns_502_when_hardware_session_start_fails(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    with patch(
        "app.routers.labs.start_weblab_session",
        side_effect=WeblabSessionError("Hardware container refused to start a session"),
    ):
        response = client.get(f"/api/labs/{lab_id}/access")
    assert response.status_code == 502


def test_failed_hardware_start_does_not_start_the_session_clock(client):
    """Regression test: session_ends_at (the countdown the frontend shows
    and counts down against) used to be derived from usage_start_time,
    which access-now sets the instant a reservation is promoted to active -
    before the hardware session is ever attempted. A hardware failure on
    the first /access call then left the reservation "active" with a
    countdown already ticking, even though the user was never let in. This
    test covers the plain start_weblab_session failure (502) path - a
    board access-now itself has no way to know is unhealthy up front. See
    test_fleet_deployments.py::test_access_now_refuses_to_create_a_reservation_for_an_unhealthy_board
    for the (more common) case where the board's health is already known
    at access-now time: there, no reservation is created at all.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    with patch(
        "app.routers.labs.start_weblab_session",
        side_effect=WeblabSessionError("Hardware container refused to start a session"),
    ):
        failed = client.get(f"/api/labs/{lab_id}/access")
    assert failed.status_code == 502

    mine = client.get("/api/reservations/mine").json()
    reservation = next(r for r in mine if r["lab_id"] == lab_id)
    assert reservation["status"] == "active"
    assert reservation["usage_start_time"] is not None
    assert reservation["session_ends_at"] is None

    with patch(
        "app.routers.labs.start_weblab_session",
        return_value="http://10.30.70.23:5003/foo/callback/fake-session-id",
    ):
        recovered = client.get(f"/api/labs/{lab_id}/access")
    assert recovered.status_code == 200

    mine = client.get("/api/reservations/mine").json()
    reservation = next(r for r in mine if r["lab_id"] == lab_id)
    assert reservation["session_ends_at"] is not None


def test_access_denied_for_a_second_user_while_board_is_in_use(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    register(client, "user2", "user2@example.com")
    login(client, "user2")
    # user2 is refused a session while user1 holds the board (no queue),
    # so has no active reservation and can't reach the hardware.
    blocked = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert blocked.status_code == 409

    response = client.get(f"/api/labs/{lab_id}/access")
    assert response.status_code == 403
