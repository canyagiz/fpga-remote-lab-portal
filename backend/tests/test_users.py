from tests.helpers import login, make_admin, register


def _make_admin_session(client, username="admin", email="admin@example.com"):
    register(client, username, email)
    login(client, username)
    make_admin(username)
    return username


def test_list_users_requires_admin(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")

    response = client.get("/api/admin/users")
    assert response.status_code == 403


def test_admin_can_list_users(client):
    _make_admin_session(client)
    register(client, "alice", "alice@example.com")

    response = client.get("/api/admin/users")
    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()}
    assert {"admin", "alice"} <= usernames


def test_delete_user_requires_admin(client):
    register(client, "alice", "alice@example.com")
    register(client, "bob", "bob@example.com")
    login(client, "alice")

    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        bob_id = db.query(User).filter(User.username == "bob").first().id
    finally:
        db.close()

    response = client.delete(f"/api/admin/users/{bob_id}")
    assert response.status_code == 403


def test_admin_can_delete_a_user_even_with_2fa_codes(client):
    """Regression test for the cascade fix: a user always has at least one
    two_factor_codes row after their first login (2FA is on by default), so
    without ON DELETE CASCADE this delete would fail with a FK violation.
    """
    _make_admin_session(client)
    register(client, "bob", "bob@example.com")
    login(client, "bob")  # creates a two_factor_codes row

    from app.database import SessionLocal
    from app.models import TwoFactorCode, User

    db = SessionLocal()
    try:
        bob = db.query(User).filter(User.username == "bob").first()
        bob_id = bob.id
        assert db.query(TwoFactorCode).filter(TwoFactorCode.user_id == bob_id).count() > 0
    finally:
        db.close()

    client.cookies.clear()
    login(client, "admin")
    response = client.delete(f"/api/admin/users/{bob_id}")
    assert response.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(User, bob_id) is None
        assert db.query(TwoFactorCode).filter(TwoFactorCode.user_id == bob_id).count() == 0
    finally:
        db.close()


def test_admin_cannot_delete_own_account(client):
    _make_admin_session(client)

    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        admin_id = db.query(User).filter(User.username == "admin").first().id
    finally:
        db.close()

    response = client.delete(f"/api/admin/users/{admin_id}")
    assert response.status_code == 400


def test_cannot_delete_user_with_reservation_history(client):
    lab_id = None
    _make_admin_session(client)

    lab_id = client.post("/api/labs", json={"name": "Arty Z7", "description": "FPGA board"}).json()["id"]

    register(client, "bob", "bob@example.com")
    login(client, "bob")
    reservation = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    assert reservation["status"] == "active"

    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        bob_id = db.query(User).filter(User.username == "bob").first().id
    finally:
        db.close()

    client.cookies.clear()
    login(client, "admin")
    response = client.delete(f"/api/admin/users/{bob_id}")
    assert response.status_code == 409


def test_admin_can_force_delete_a_user_with_reservation_history(client):
    lab_id = None
    _make_admin_session(client)

    lab_id = client.post("/api/labs", json={"name": "Arty Z7", "description": "FPGA board"}).json()["id"]

    register(client, "bob", "bob@example.com")
    login(client, "bob")
    reservation = client.post("/api/reservations/access-now", json={"lab_id": lab_id}).json()
    assert reservation["status"] == "active"

    from app.database import SessionLocal
    from app.models import Reservation, User

    db = SessionLocal()
    try:
        bob_id = db.query(User).filter(User.username == "bob").first().id
    finally:
        db.close()

    client.cookies.clear()
    login(client, "admin")

    # without force, still blocked (unchanged behavior)
    assert client.delete(f"/api/admin/users/{bob_id}").status_code == 409

    # with force, the account and its history are both removed
    response = client.delete(f"/api/admin/users/{bob_id}?force=true")
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        assert db.get(User, bob_id) is None
        assert db.query(Reservation).filter(Reservation.user_id == bob_id).count() == 0
    finally:
        db.close()
