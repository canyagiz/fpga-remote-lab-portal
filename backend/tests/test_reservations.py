from datetime import datetime, timedelta

from tests.helpers import login, make_admin, register


def _create_lab(client):
    register(client, "admin", "admin@example.com")
    login(client, "admin")
    make_admin("admin")
    lab_id = client.post("/api/labs", json={"name": "Arty Z7", "description": "FPGA board"}).json()["id"]
    return lab_id


def test_access_now_grants_the_free_board_and_refuses_a_second_user(client):
    """The board has no waiting queue: the first user to Access a free
    board gets it immediately; a second user, while it's in use, is
    refused (409) rather than parked in a queue.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    login(client, "user1")
    resv1 = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert resv1.status_code == 201 and resv1.json()["status"] == "active"

    login(client, "user2")
    resv2 = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert resv2.status_code == 409

    # Once the first user finishes, the board frees up for the second.
    login(client, "user1")
    client.post(f"/api/reservations/{resv1.json()['id']}/complete")

    login(client, "user2")
    retry = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert retry.status_code == 201 and retry.json()["status"] == "active"


def test_access_now_is_idempotent_for_an_active_session(client):
    """Re-Accessing while already active returns the same session instead
    of erroring - lets a returning tab re-open the hardware."""
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    first = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    second = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert second.status_code in (200, 201)
    assert second.json()["id"] == first["id"]


def test_access_now_activates_a_scheduled_reservation_whose_time_has_come(client):
    """A booked slot is entered via Access once its window covers now -
    there is no separate Start step."""
    from app.database import SessionLocal
    from app.models import Reservation

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    slot = datetime.utcnow() + timedelta(hours=2)
    resv = client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": slot.date().isoformat(),
            "reservation_time": slot.time().replace(microsecond=0).isoformat(),
        },
    ).json()

    # Access before the slot's time: rejected (it's for later).
    early = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert early.status_code == 409

    # Move the slot onto now, then Access activates it.
    db = SessionLocal()
    try:
        row = db.get(Reservation, resv["id"])
        now = datetime.utcnow()
        row.reservation_date = now.date()
        row.reservation_time = now.time()
        db.commit()
    finally:
        db.close()

    entered = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert entered.status_code in (200, 201)
    assert entered.json()["status"] == "active"
    assert entered.json()["id"] == resv["id"]


def test_cancel_frees_the_slot_for_a_new_booking(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    slot = datetime.utcnow() + timedelta(hours=2)
    date_str, time_str = slot.date().isoformat(), slot.time().replace(microsecond=0).isoformat()

    login(client, "user1")
    resv = client.post(
        "/api/reservations", json={"lab_id": lab_id, "reservation_date": date_str, "reservation_time": time_str}
    ).json()

    login(client, "user2")
    conflict = client.post(
        "/api/reservations", json={"lab_id": lab_id, "reservation_date": date_str, "reservation_time": time_str}
    )
    assert conflict.status_code == 409

    login(client, "user1")
    cancelled = client.post(f"/api/reservations/{resv['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"

    login(client, "user2")
    retry = client.post(
        "/api/reservations", json={"lab_id": lab_id, "reservation_date": date_str, "reservation_time": time_str}
    )
    assert retry.status_code == 201


def test_overlapping_slots_are_rejected_even_with_different_start_times(client):
    """Regression test: a 10:28-10:32 booking followed by a 10:30-10:34
    one for the same board used to both succeed, because the old check
    only rejected an *exact* (date, time) match - not any overlap between
    the two sessions' actual [start, start + session_duration) windows.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    base = datetime.utcnow() + timedelta(hours=2)
    first_start = base.replace(minute=0, second=0, microsecond=0)
    # session_duration_seconds defaults to 240s (4 min) - two minutes later
    # still falls inside the first booking's occupied window.
    second_start = first_start + timedelta(minutes=2)

    login(client, "user1")
    first = client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": first_start.date().isoformat(),
            "reservation_time": first_start.time().isoformat(),
        },
    )
    assert first.status_code == 201

    login(client, "user2")
    second = client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": second_start.date().isoformat(),
            "reservation_time": second_start.time().isoformat(),
        },
    )
    assert second.status_code == 409

    # A booking that starts only after the first one's window fully ends
    # must still be allowed.
    third_start = first_start + timedelta(minutes=4)
    third = client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": third_start.date().isoformat(),
            "reservation_time": third_start.time().isoformat(),
        },
    )
    assert third.status_code == 201


def test_access_is_immediate_when_board_is_free_despite_a_future_reservation(client):
    """Regression test: a future scheduled reservation used to make the
    'is the board free' check treat the board as occupied *right now*, so
    clicking Access queued the user (queue position 1) even though the
    board was actually free and the scheduled slot was hours away.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    login(client, "user1")
    slot = datetime.utcnow() + timedelta(hours=2)
    client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": slot.date().isoformat(),
            "reservation_time": slot.time().replace(microsecond=0).isoformat(),
        },
    )

    login(client, "user2")
    access = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert access.status_code == 201
    # Immediately active - not stuck behind the far-future scheduled slot.
    assert access.json()["status"] == "active"


def test_access_rejected_when_a_scheduled_reservation_covers_now(client):
    """The flip side: if a scheduled reservation's window actually covers
    the current moment, you can't barge into it via immediate Access."""
    from app.database import SessionLocal
    from app.models import Reservation, ReservationStatus

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    login(client, "user1")
    slot = datetime.utcnow() + timedelta(hours=2)
    resv = client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": slot.date().isoformat(),
            "reservation_time": slot.time().replace(microsecond=0).isoformat(),
        },
    ).json()

    # make_reservation enforces a min-advance window, so a slot can't be
    # booked to start *right now* through the API - move it onto now directly.
    db = SessionLocal()
    try:
        row = db.get(Reservation, resv["id"])
        now = datetime.utcnow()
        row.reservation_date = now.date()
        row.reservation_time = now.time()
        db.commit()
    finally:
        db.close()

    login(client, "user2")
    access = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert access.status_code == 409


def test_reservation_out_includes_session_ends_at_only_when_active(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    slot = datetime.utcnow() + timedelta(hours=2)
    scheduled = client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": slot.date().isoformat(),
            "reservation_time": slot.time().replace(microsecond=0).isoformat(),
        },
    ).json()
    assert scheduled["usage_start_time"] is None
    assert scheduled["session_ends_at"] is None

    register(client, "user2", "user2@example.com")
    login(client, "user2")
    active = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    assert active["usage_start_time"] is not None
    assert active["session_ends_at"] is not None
    assert active["session_ends_at"] > active["usage_start_time"]


def test_cannot_finish_a_session_that_already_ran_out_of_time(client):
    """A manual Finish must not be able to "close" a session past its
    allotted time - that's the expiry sweep's job (services/queue.py), and
    letting Finish succeed here would record it as completed instead of
    expired and race the sweep.
    """
    from app.database import SessionLocal
    from app.models import Reservation

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()

    db = SessionLocal()
    try:
        row = db.get(Reservation, resv["id"])
        row.usage_start_time = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    response = client.post(f"/api/reservations/{resv['id']}/complete")
    assert response.status_code == 409


def _mark_session_opened(reservation_id, url="http://10.30.70.23:5003/foo/callback/fake-session-id"):
    """Simulate having already called GET /labs/{id}/access once, which is
    what sets weblab_session_url in real use."""
    from app.database import SessionLocal
    from app.models import Reservation

    db = SessionLocal()
    try:
        reservation = db.get(Reservation, reservation_id)
        reservation.weblab_session_url = url
        db.commit()
    finally:
        db.close()


def test_finish_closes_the_hardware_session_when_one_was_opened(client):
    """Regression test: Finish only updated our own database - the real
    WebLab session on CT300 stayed open, so the browser tab that already
    had the hardware page loaded kept working, and a second user could be
    handed a session on what we now considered a free board while the
    first one was still physically live.
    """
    from unittest.mock import patch

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    _mark_session_opened(resv["id"])

    with patch("app.routers.reservations.close_weblab_session") as mock_close:
        response = client.post(f"/api/reservations/{resv['id']}/complete")

    assert response.status_code == 200
    mock_close.assert_called_once()


def test_cancel_closes_the_hardware_session_when_one_was_opened(client):
    from unittest.mock import patch

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    _mark_session_opened(resv["id"])

    with patch("app.routers.reservations.close_weblab_session") as mock_close:
        response = client.post(f"/api/reservations/{resv['id']}/cancel")

    assert response.status_code == 200
    mock_close.assert_called_once()


def test_finish_succeeds_even_if_the_hardware_is_unreachable(client):
    """Ending a reservation on our side must not get stuck just because
    CT300 can't be reached - best effort, not a hard dependency."""
    import httpx
    from unittest.mock import patch

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    _mark_session_opened(resv["id"])

    with patch("app.routers.reservations.close_weblab_session", side_effect=httpx.ConnectError("unreachable")):
        response = client.post(f"/api/reservations/{resv['id']}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_finish_does_not_call_hardware_when_no_session_was_ever_opened(client):
    """A reservation nobody clicked Access on has nothing on CT300 to
    close - closing must not even try (and must not error)."""
    from unittest.mock import patch

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()

    with patch("app.routers.reservations.close_weblab_session") as mock_close:
        response = client.post(f"/api/reservations/{resv['id']}/complete")

    assert response.status_code == 200
    mock_close.assert_not_called()


def test_reservation_requires_minimum_advance_notice(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    too_soon = datetime.utcnow() + timedelta(minutes=1)
    response = client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": too_soon.date().isoformat(),
            "reservation_time": too_soon.time().replace(microsecond=0).isoformat(),
        },
    )
    assert response.status_code == 400


def test_expiry_sweep_frees_an_overrun_active_session(client):
    from app.database import SessionLocal
    from app.models import Reservation
    from app.services.queue import sweep_expired_reservations

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    login(client, "user1")
    resv1 = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()

    # While user1 is active, user2 can't grab the board (no queue).
    login(client, "user2")
    blocked = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert blocked.status_code == 409

    # Simulate user1 having overrun their session time without finishing.
    db = SessionLocal()
    try:
        reservation = db.get(Reservation, resv1["id"])
        reservation.usage_start_time = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        expired_count = sweep_expired_reservations(db)
    finally:
        db.close()
    assert expired_count == 1

    # With the overrun session swept, the board is free for user2 now.
    login(client, "user2")
    entered = client.post("/api/reservations/access-now", json={"lab_id": lab_id})
    assert entered.status_code == 201 and entered.json()["status"] == "active"


def test_expiry_sweep_closes_the_hardware_session_for_an_overrun_reservation(client):
    """Same overrun scenario, but this time a real WebLab session was
    opened (weblab_session_url set) - the sweep must tell CT300 too, not
    just mark the reservation expired on our side."""
    from unittest.mock import patch

    from app.database import SessionLocal
    from app.models import Reservation
    from app.services.queue import sweep_expired_reservations

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    resv1 = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()

    db = SessionLocal()
    try:
        reservation = db.get(Reservation, resv1["id"])
        reservation.usage_start_time = datetime.utcnow() - timedelta(hours=1)
        reservation.weblab_session_url = "http://10.30.70.23:5003/foo/callback/fake-session-id"
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        with patch("app.services.queue.close_weblab_session") as mock_close:
            expired_count = sweep_expired_reservations(db)
    finally:
        db.close()

    assert expired_count == 1
    mock_close.assert_called_once()
