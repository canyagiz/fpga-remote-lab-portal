import random
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import RegistrationAttempt, TwoFactorCode, User
from app.schemas import (
    CaptchaOut,
    LoginRequest,
    LoginResult,
    MessageOut,
    RegisterRequest,
    UserOut,
    Verify2FARequest,
)
from app.security import generate_two_factor_code, hash_password, mask_email, verify_password
from app.services.email import send_two_factor_code

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/captcha", response_model=CaptchaOut)
def get_captcha(request: Request):
    num1, num2 = random.randint(1, 10), random.randint(1, 10)
    operator = random.choice(["+", "-"])
    if operator == "-" and num1 < num2:
        num1, num2 = num2, num1
    result = num1 + num2 if operator == "+" else num1 - num2

    request.session["captcha_result"] = result
    return CaptchaOut(question=f"What is {num1} {operator} {num2}?")


@router.get("/csrf-token")
def get_csrf_token(request: Request):
    token = secrets.token_hex(32)
    request.session["csrf_token"] = token
    return {"success": True, "token": token}


@router.post("/register", response_model=MessageOut)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # Honeypot: bots fill every field, including this hidden one. Report
    # fake success so the bot doesn't learn its submission was rejected.
    if payload.website:
        return MessageOut(success=True, message="Registration successful")

    if not payload.csrf_token or payload.csrf_token != request.session.get("csrf_token"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid security token")
    request.session.pop("csrf_token", None)

    stored_captcha = request.session.pop("captcha_result", None)
    if stored_captcha is None or payload.captcha_answer != stored_captcha:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect security check")

    ip_address = request.client.host if request.client else "unknown"
    window_start = datetime.utcnow() - timedelta(
        minutes=settings.registration_rate_limit_window_minutes
    )
    recent_attempts = db.scalar(
        select(func.count())
        .select_from(RegistrationAttempt)
        .where(RegistrationAttempt.ip_address == ip_address)
        .where(RegistrationAttempt.attempt_time > window_start)
    )
    if recent_attempts and recent_attempts >= settings.registration_rate_limit_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait before trying again.",
        )
    db.add(RegistrationAttempt(ip_address=ip_address))

    existing = db.scalar(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    )
    if existing:
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already exists")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()

    return MessageOut(success=True, message="Registration successful")


@router.post("/login", response_model=LoginResult)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))

    # Deliberately no plaintext fallback here: the old repo accepted
    # `password === stored_value` as a bypass, which was a real backdoor.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if user.two_factor_enabled:
        code = generate_two_factor_code()
        expires_at = datetime.utcnow() + timedelta(seconds=settings.two_factor_code_ttl_seconds)
        db.query(TwoFactorCode).filter(
            TwoFactorCode.user_id == user.id, TwoFactorCode.used == False  # noqa: E712
        ).update({"used": True})
        db.add(TwoFactorCode(user_id=user.id, code=code, expires_at=expires_at))
        db.commit()

        send_two_factor_code(user.email, user.username, code)

        # The pending user id lives server-side in the session, never in the
        # response body - the client can't verify 2FA for an arbitrary user.
        request.session["pending_2fa_user_id"] = user.id
        return LoginResult(
            success=True,
            require_2fa=True,
            message=f"A verification code has been sent to {mask_email(user.email)}",
        )

    request.session["user_id"] = user.id
    return LoginResult(success=True, require_2fa=False)


@router.post("/verify-2fa", response_model=UserOut)
def verify_two_factor(payload: Verify2FARequest, request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("pending_2fa_user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending verification")

    code_row = db.scalar(
        select(TwoFactorCode)
        .where(TwoFactorCode.user_id == user_id)
        .where(TwoFactorCode.code == payload.code)
        .where(TwoFactorCode.used == False)  # noqa: E712
        .where(TwoFactorCode.expires_at > datetime.utcnow())
        .order_by(TwoFactorCode.created_at.desc())
    )
    if code_row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code")

    code_row.used = True
    user = db.get(User, user_id)
    db.commit()

    request.session.pop("pending_2fa_user_id", None)
    request.session["user_id"] = user.id
    return user


@router.post("/resend-2fa", response_model=MessageOut)
def resend_two_factor(request: Request, db: Session = Depends(get_db)):
    # Identity comes from the pending-2FA session key, not a client-supplied
    # userId - otherwise anyone could trigger codes for any account.
    user_id = request.session.get("pending_2fa_user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No pending verification")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    code = generate_two_factor_code()
    expires_at = datetime.utcnow() + timedelta(seconds=settings.two_factor_code_ttl_seconds)
    db.add(TwoFactorCode(user_id=user.id, code=code, expires_at=expires_at))
    db.commit()

    sent = send_two_factor_code(user.email, user.username, code)
    if not sent:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to send code")

    return MessageOut(success=True, message=f"New code sent to {mask_email(user.email)}")


@router.post("/logout", response_model=MessageOut)
def logout(request: Request):
    request.session.clear()
    return MessageOut(success=True, message="Logged out")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
