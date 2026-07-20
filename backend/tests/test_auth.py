from tests.helpers import captcha_target_x, login, make_admin, register


def test_register_rejects_wrong_captcha(client):
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")  # sets the real answer in session, we ignore it below

    response = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "Password123",
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
            "password": "Password123",
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

    response = client.post("/api/auth/login", json={"username": "alice", "password": "Password123"})
    assert response.status_code == 200
    assert response.json()["require_2fa"] is True

    # Not authenticated yet - the 2FA step hasn't completed.
    assert client.get("/api/auth/me").status_code == 401

    login(client, "alice")
    assert client.get("/api/auth/me").status_code == 200


def test_2fa_only_required_on_first_login(client):
    """2FA should confirm the email address once, right after registration -
    not gate every single login. The first verification must flip
    two_factor_enabled off so later logins skip straight through.
    """
    register(client, "alice", "alice@example.com")

    first = client.post("/api/auth/login", json={"username": "alice", "password": "Password123"})
    assert first.json()["require_2fa"] is True
    login(client, "alice")  # completes the one required verification

    client.cookies.clear()
    second = client.post("/api/auth/login", json={"username": "alice", "password": "Password123"})
    assert second.status_code == 200
    assert second.json()["require_2fa"] is False
    # No verify-2fa call needed this time - the session is already live.
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


def test_resend_2fa_is_rate_limited(client):
    """register() already sent one code; hammering resend right after
    must be rejected instead of firing an email per click."""
    register(client, "alice", "alice@example.com")

    response = client.post("/api/auth/resend-2fa")
    assert response.status_code == 429
    assert "minute" in response.json()["detail"] or "second" in response.json()["detail"]
    assert int(response.headers["Retry-After"]) > 0


def test_resend_2fa_succeeds_once_the_cooldown_has_elapsed(client):
    from datetime import datetime, timedelta

    from app.database import SessionLocal
    from app.models import TwoFactorCode, User

    register(client, "alice", "alice@example.com")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "alice").first()
        db.query(TwoFactorCode).filter(TwoFactorCode.user_id == user.id).update(
            {"created_at": datetime.utcnow() - timedelta(minutes=10)}
        )
        db.commit()
    finally:
        db.close()

    response = client.post("/api/auth/resend-2fa")
    assert response.status_code == 200


def test_registration_rate_limit_reports_how_long_to_wait(client):
    from app.config import settings

    for i in range(settings.registration_rate_limit_max_attempts):
        register(client, f"ratelimit{i}", f"ratelimit{i}@example.com")

    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    answer = captcha_target_x(client)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "onemore",
            "email": "onemore@example.com",
            "password": "Password123",
            "captcha_answer": answer,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 429
    assert "minute" in response.json()["detail"] or "second" in response.json()["detail"]
    assert int(response.headers["Retry-After"]) > 0


def _attempt_register_with_weak_password(client, username):
    """A submission that fails content validation (weak password) - used
    to confirm this still consumes a rate-limit slot, unlike before."""
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    answer = captcha_target_x(client)
    return client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "allweaklowercase",  # no uppercase, no digit
            "captcha_answer": answer,
            "csrf_token": csrf,
            "website": "",
        },
    )


def test_rate_limit_counts_content_validation_failures_too(client):
    """Regression test: a bad email/weak password/wrong captcha used to
    skip the rate limit entirely, because RegisterRequest's own pydantic
    validators ran before this function's body (where the limit lived)
    ever started - a flood of garbage submissions was never counted."""
    from app.config import settings

    for i in range(settings.registration_rate_limit_max_attempts):
        response = _attempt_register_with_weak_password(client, f"weakpw{i}")
        assert response.status_code == 422

    response = _attempt_register_with_weak_password(client, "onemoreweak")
    assert response.status_code == 429


def test_rate_limit_counts_wrong_captcha_attempts_too(client):
    from app.config import settings

    for i in range(settings.registration_rate_limit_max_attempts):
        csrf = client.get("/api/auth/csrf-token").json()["token"]
        client.get("/api/auth/captcha")  # sets the real answer in session, ignored below
        response = client.post(
            "/api/auth/register",
            json={
                "username": f"badcaptcha{i}",
                "email": f"badcaptcha{i}@example.com",
                "password": "GoodPass123",
                "captcha_answer": -999999,
                "csrf_token": csrf,
                "website": "",
            },
        )
        assert response.status_code == 400

    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    response = client.post(
        "/api/auth/register",
        json={
            "username": "onemorebad",
            "email": "onemorebad@example.com",
            "password": "GoodPass123",
            "captcha_answer": -999999,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 429


def test_registration_username_is_case_insensitively_unique(client):
    register(client, "alice", "alice@example.com")

    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    answer = captcha_target_x(client)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "Alice",
            "email": "someone-else@example.com",
            "password": "Password123",
            "captcha_answer": answer,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 409


def test_registration_email_is_case_insensitively_unique(client):
    register(client, "alice", "alice@example.com")

    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    answer = captcha_target_x(client)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "someone_else",
            "email": "Alice@Example.com",
            "password": "Password123",
            "captcha_answer": answer,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 409


def test_login_username_is_case_insensitive(client):
    register(client, "alice", "alice@example.com")

    response = client.post("/api/auth/login", json={"username": "ALICE", "password": "Password123"})
    assert response.status_code == 200


def test_login_with_email_instead_of_username(client):
    register(client, "alice", "alice@example.com")

    response = client.post("/api/auth/login", json={"username": "alice@example.com", "password": "Password123"})
    assert response.status_code == 200


def test_login_with_email_is_case_insensitive(client):
    register(client, "alice", "alice@example.com")

    response = client.post("/api/auth/login", json={"username": "ALICE@EXAMPLE.COM", "password": "Password123"})
    assert response.status_code == 200


def test_registration_rejects_a_password_without_uppercase(client):
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    answer = captcha_target_x(client)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "password123",
            "captcha_answer": answer,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 422


def test_registration_rejects_a_password_without_a_digit(client):
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    answer = captcha_target_x(client)

    response = client.post(
        "/api/auth/register",
        json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "PasswordOnly",
            "captcha_answer": answer,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 422


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
