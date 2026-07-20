def captcha_target_x(client):
    """Test-only: recovers the puzzle's solution the same way
    SessionMiddleware itself decodes the session cookie. The real client
    never gets target_x - see app/services/captcha.py - it's baked into
    where the hole and piece sit in the two images the endpoint returns,
    which a test has no way to "look at".
    """
    import json
    from base64 import b64decode

    import itsdangerous

    from app.config import settings

    signer = itsdangerous.TimestampSigner(str(settings.secret_key))
    session = json.loads(b64decode(signer.unsign(client.cookies["session"])))
    return session["captcha_result"]


def register(client, username, email, password="Password123"):
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    client.get("/api/auth/captcha")
    answer = captcha_target_x(client)

    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
            "captcha_answer": answer,
            "csrf_token": csrf,
            "website": "",
        },
    )
    assert response.status_code == 200, response.text


def login(client, username, password="Password123"):
    """Log in, completing the 2FA step only if the account still requires
    it. 2FA turns itself off after its first successful verification (see
    routers/auth.py::verify_two_factor), so a second login for the same
    username - common across tests - won't require it again.
    """
    from app.database import SessionLocal
    from app.models import TwoFactorCode, User

    client.cookies.clear()
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text

    if not response.json()["require_2fa"]:
        db = SessionLocal()
        try:
            return db.query(User).filter(User.username == username).first().id
        finally:
            db.close()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        code_row = (
            db.query(TwoFactorCode)
            .filter(TwoFactorCode.user_id == user.id)
            .order_by(TwoFactorCode.id.desc())
            .first()
        )
        user_id, code = user.id, code_row.code
    finally:
        db.close()

    verify = client.post("/api/auth/verify-2fa", json={"code": code})
    assert verify.status_code == 200, verify.text
    return user_id


def make_admin(username):
    """Grant admin the same way the app does - a row in admin_emails, not
    just a raw role flip. The role is now a projection of the allowlist
    (config + admin_emails), re-synced on every login, so a bare role=admin
    would be undone the next time this account logs in.
    """
    from app.database import SessionLocal
    from app.models import AdminEmail, User, UserRole

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        user.role = UserRole.admin
        if db.query(AdminEmail).filter(AdminEmail.email == user.email).first() is None:
            db.add(AdminEmail(email=user.email, added_by_user_id=user.id))
        db.commit()
    finally:
        db.close()
