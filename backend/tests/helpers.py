def register(client, username, email, password="password123"):
    csrf = client.get("/api/auth/csrf-token").json()["token"]
    question = client.get("/api/auth/captcha").json()["question"]
    n1, op, n2 = question.replace("What is ", "").replace("?", "").split(" ")
    answer = int(n1) + int(n2) if op == "+" else int(n1) - int(n2)

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


def login(client, username, password="password123"):
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
    from app.database import SessionLocal
    from app.models import User, UserRole

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        user.role = UserRole.admin
        db.commit()
    finally:
        db.close()
