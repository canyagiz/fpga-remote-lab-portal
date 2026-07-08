from datetime import datetime, timedelta

from tests.helpers import login, make_admin, register


def _create_lab(client):
    register(client, "admin", "admin@example.com")
    login(client, "admin")
    make_admin("admin")
    lab_id = client.post("/labs", json={"name": "Arty Z7", "description": "FPGA board"}).json()["id"]
    return lab_id


def test_queue_advances_through_three_users(client):
    """Regression test for the old repo's core bug: queue_position was set
    once and never recomputed, so whoever was behind position 0 waited
    forever. Here, three users queue for the same lab and each must get a
    turn as the ones ahead of them finish.
    """
    lab_id = _create_lab(client)

    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")
    register(client, "user3", "user3@example.com")

    login(client, "user1")
    resv1 = client.post("/reservations/queue", json={"lab_id": lab_id}).json()
    assert resv1["status"] == "active" and resv1["queue_position"] == 0

    login(client, "user2")
    resv2 = client.post("/reservations/queue", json={"lab_id": lab_id}).json()
    assert resv2["status"] == "pending" and resv2["queue_position"] == 0

    login(client, "user3")
    resv3 = client.post("/reservations/queue", json={"lab_id": lab_id}).json()
    assert resv3["status"] == "pending" and resv3["queue_position"] == 1

    login(client, "user1")
    client.post(f"/reservations/{resv1['id']}/complete")

    login(client, "user2")
    mine = client.get("/reservations/mine").json()
    assert mine[0]["queue_position"] == 0
    started = client.post(f"/reservations/{resv2['id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "active"

    login(client, "user3")
    mine = client.get("/reservations/mine").json()
    assert mine[0]["queue_position"] == 0


def test_being_first_in_queue_does_not_bypass_an_active_session(client):
    """Regression test: having queue_position 0 among pending reservations
    only means "next in line" - it does not mean the lab is free. Without
    this check, a second user could start a session while another user's
    session is still active.
    """
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    login(client, "user1")
    resv1 = client.post("/reservations/queue", json={"lab_id": lab_id}).json()
    assert resv1["status"] == "active"

    login(client, "user2")
    resv2 = client.post("/reservations/queue", json={"lab_id": lab_id}).json()
    assert resv2["status"] == "pending" and resv2["queue_position"] == 0

    response = client.post(f"/reservations/{resv2['id']}/start")
    assert response.status_code == 409

    login(client, "user1")
    client.post(f"/reservations/{resv1['id']}/complete")

    login(client, "user2")
    response = client.post(f"/reservations/{resv2['id']}/start")
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_cancel_frees_the_slot_for_a_new_booking(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    slot = datetime.utcnow() + timedelta(hours=2)
    date_str, time_str = slot.date().isoformat(), slot.time().replace(microsecond=0).isoformat()

    login(client, "user1")
    resv = client.post(
        "/reservations", json={"lab_id": lab_id, "reservation_date": date_str, "reservation_time": time_str}
    ).json()

    login(client, "user2")
    conflict = client.post(
        "/reservations", json={"lab_id": lab_id, "reservation_date": date_str, "reservation_time": time_str}
    )
    assert conflict.status_code == 409

    login(client, "user1")
    cancelled = client.post(f"/reservations/{resv['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"

    login(client, "user2")
    retry = client.post(
        "/reservations", json={"lab_id": lab_id, "reservation_date": date_str, "reservation_time": time_str}
    )
    assert retry.status_code == 201


def test_reservation_requires_minimum_advance_notice(client):
    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    login(client, "user1")

    too_soon = datetime.utcnow() + timedelta(minutes=1)
    response = client.post(
        "/reservations",
        json={
            "lab_id": lab_id,
            "reservation_date": too_soon.date().isoformat(),
            "reservation_time": too_soon.time().replace(microsecond=0).isoformat(),
        },
    )
    assert response.status_code == 400


def test_expiry_sweep_frees_an_overrun_active_session(client):
    from app.database import SessionLocal
    from app.models import Reservation, ReservationStatus
    from app.services.queue import sweep_expired_reservations

    lab_id = _create_lab(client)
    register(client, "user1", "user1@example.com")
    register(client, "user2", "user2@example.com")

    login(client, "user1")
    resv1 = client.post("/reservations/queue", json={"lab_id": lab_id}).json()

    login(client, "user2")
    resv2 = client.post("/reservations/queue", json={"lab_id": lab_id}).json()
    assert resv2["status"] == "pending"

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

    login(client, "user2")
    mine = client.get("/reservations/mine").json()
    assert mine[0]["queue_position"] == 0
    started = client.post(f"/reservations/{resv2['id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "active"
