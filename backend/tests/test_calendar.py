from datetime import datetime, timedelta

from tests.helpers import login, make_admin, register


def _create_lab(client):
    register(client, "admin", "admin@example.com")
    login(client, "admin")
    make_admin("admin")
    lab_id = client.post("/api/labs", json={"name": "Arty Z7", "description": "FPGA board"}).json()["id"]
    return lab_id


def test_calendar_shows_active_session_with_username_only(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})  # lab is free -> becomes active

    response = client.get("/api/reservations/calendar")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["username"] == "user1"
    assert entries[0]["lab_id"] == lab_id
    assert entries[0]["status"] == "active"
    assert entries[0]["start_time"] < entries[0]["end_time"]
    # Never leak anything beyond the username - no email, no profile fields.
    assert set(entries[0].keys()) == {"lab_id", "lab_name", "username", "status", "start_time", "end_time"}


def test_calendar_shows_future_scheduled_reservation(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    slot = datetime.utcnow() + timedelta(hours=2)
    client.post(
        "/api/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": slot.date().isoformat(),
            "reservation_time": slot.time().isoformat(),
        },
    )

    response = client.get("/api/reservations/calendar")
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["username"] == "user1"
    assert entries[0]["status"] == "pending"


def test_calendar_requires_authentication(client):
    response = client.get("/api/reservations/calendar")
    assert response.status_code == 401
