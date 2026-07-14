"""Self-service account deletion from the profile page."""

from tests.helpers import login, register


def _user_row(username):
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == username).first()
    finally:
        db.close()


def test_delete_own_account_with_correct_password(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")

    resp = client.request("DELETE", "/api/profile", json={"password": "Password123"})
    assert resp.status_code == 200, resp.text
    assert _user_row("alice") is None

    # session is cleared - a follow-up authed call is now unauthorized
    assert client.get("/api/auth/me").status_code == 401


def test_delete_requires_correct_password(client):
    register(client, "bob", "bob@example.com")
    login(client, "bob")

    resp = client.request("DELETE", "/api/profile", json={"password": "wrongpass"})
    assert resp.status_code == 401
    assert _user_row("bob") is not None  # still there


def test_delete_requires_authentication(client):
    client.cookies.clear()
    resp = client.request("DELETE", "/api/profile", json={"password": "whatever"})
    assert resp.status_code == 401


def test_delete_removes_reservation_history(client):
    # make a lab as admin, then use it as bob, then bob deletes himself
    register(client, "root", "root@example.com")
    login(client, "root")
    lab_id = client.post("/api/labs", json={"name": "Arty Z7", "description": "board"}).json()["id"]

    register(client, "bob", "bob@example.com")
    bob_id = login(client, "bob")
    client.post("/api/reservations/access-now", json={"lab_id": lab_id})

    from app.database import SessionLocal
    from app.models import Reservation

    db = SessionLocal()
    try:
        assert db.query(Reservation).filter(Reservation.user_id == bob_id).count() == 1
    finally:
        db.close()

    resp = client.request("DELETE", "/api/profile", json={"password": "Password123"})
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    try:
        # user gone AND their reservations gone (no FK violation, hard delete)
        assert db.query(Reservation).filter(Reservation.user_id == bob_id).count() == 0
    finally:
        db.close()
    assert _user_row("bob") is None
