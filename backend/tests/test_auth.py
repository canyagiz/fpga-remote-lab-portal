from tests.helpers import login, make_admin, register


def test_register_rejects_wrong_captcha(client):
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")  # sets the real answer in session, we ignore it below

    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password123",
            "captcha_answer": -999999,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 400


def test_register_honeypot_reports_fake_success_without_creating_user(client):
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    response = client.post(
        "/api/auth/register",
        json={
            "username": "bot",
            "email": "bot@example.com",
            "password": "password123",
            "captcha_answer": 0,
            "csrf_token": csrf,
            "website": "https://spam.example",
        },
    )
    assert response.status_code == 200

    # The account must not actually exist despite the "success" response.
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.username == "bot").first() is None
    finally:
        db.close()


def test_login_requires_2fa_and_session_gates_me(client):
    register(client, "alice", "alice@example.com")

    response = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert response.status_code == 200
    assert response.json()["require_2fa"] is True

    # Not authenticated yet - the 2FA step hasn't completed.
    assert client.get("/api/auth/me").status_code == 401

    login(client, "alice")
    assert client.get("/api/auth/me").status_code == 200


def test_login_rejects_wrong_password_with_no_plaintext_fallback(client):
    register(client, "alice", "alice@example.com")
    response = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"})
    assert response.status_code == 401


def test_2fa_verification_uses_session_not_client_supplied_user_id(client):
    """Regression test for the old repo's design, where verify2FA trusted a
    client-supplied userId. Here the pending user id must come from the
    session set during /auth/login, so passing an unrelated code verifies
    nothing without a matching pending session.
    """
    register(client, "alice", "alice@example.com")
    client.cookies.clear()

    response = client.post("/api/auth/verify-2fa", json={"code": "123456"})
    assert response.status_code == 400


def test_create_lab_requires_admin_role_enforced_server_side(client):
    register(client, "alice", "alice@example.com")
    login(client, "alice")

    response = client.post("/api/labs", json={"name": "Arty Z7", "description": "FPGA board"})
    assert response.status_code == 403

    # Role is re-read from the database on every request (see
    # deps.get_current_user), so this takes effect immediately - no
    # re-login and no stale role cached in the session cookie.
    make_admin("alice")
    response = client.post("/api/labs", json={"name": "Arty Z7", "description": "FPGA board"})
    assert response.status_code == 201
