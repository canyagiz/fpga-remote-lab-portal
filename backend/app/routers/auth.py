import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import LoginEvent, RegistrationAttempt, TwoFactorCode, User
from app.schemas import (
    CaptchaOut,
    LoginRequest,
    LoginResult,
    MessageOut,
    RegisterRequest,
    UserOut,
    Verify2FARequest,
    validate_registration_email,
    validate_registration_password,
    validate_registration_username,
)
from app.security import generate_two_factor_code, hash_password, mask_email, verify_password
from app.services.admin import sync_user_role
from app.services.captcha import CAPTCHA_TOLERANCE_PX, generate_puzzle
from app.services.email import send_two_factor_code

router = APIRouter(prefix="/auth", tags=["auth"])


def _format_wait_text(wait_seconds: int) -> str:
    # m:ss, not a rounded "2 minutes" - flooring to whole minutes used to
    # report e.g. 179 remaining seconds as "2 minutes" while the frontend's
    # live countdown (which starts from this same number, see
    # ApiError.retryAfterSeconds) correctly ticks all the way down from
    # 2:59, so the button stayed disabled for a minute longer than the
    # toast had just promised.
    minutes, seconds = divmod(wait_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _two_factor_cooldown_remaining(db: Session, user_id: int) -> int:
    """Seconds until another 2FA code may be sent to this user, or 0 if
    none is currently pending. Single source of truth for the cooldown -
    used both by resend-2fa (to reject early) and by login (to avoid
    firing a second email instead of just re-showing the code prompt) -
    so closing the verification dialog and signing in again can't be used
    to route around the resend button's own rate limit.
    """
    last_code = db.scalar(
        select(TwoFactorCode).where(TwoFactorCode.user_id == user_id).order_by(TwoFactorCode.created_at.desc())
    )
    if last_code is None:
        return 0
    elapsed_seconds = (datetime.utcnow() - last_code.created_at).total_seconds()
    return max(int(settings.two_factor_resend_cooldown_seconds - elapsed_seconds), 0)


@router.get("/captcha", response_model=CaptchaOut)
def get_captcha(request: Request):
    puzzle = generate_puzzle()

    request.session["captcha_result"] = puzzle.target_x
    return CaptchaOut(
        background_image=puzzle.background_image,
        piece_image=puzzle.piece_image,
        canvas_width=puzzle.canvas_width,
        canvas_height=puzzle.canvas_height,
        piece_width=puzzle.piece_width,
        piece_height=puzzle.piece_height,
        piece_top=puzzle.piece_top,
    )


@router.get("/csrf-token")
def get_csrf_token(request: Request):
    token = secrets.token_hex(32)
    request.session["csrf_token"] = token
    return {"success": True, "token": token}


@router.post("/register", response_model=LoginResult)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # Honeypot: bots fill every field, including this hidden one. Report
    # fake success so the bot doesn't learn its submission was rejected.
    # Not rate-limited - it's a guaranteed instant fake success, nothing
    # here for an attacker to probe or brute-force.
    if payload.website:
        return LoginResult(success=True, require_2fa=True, message="Registration successful")

    # Rate-limited from here on, BEFORE csrf/captcha/content validation -
    # all of those used to run first, so a submission that merely had a
    # bad email, a weak password, or a wrong captcha answer never
    # consumed a slot at all. RegisterRequest itself is deliberately
    # unvalidated (plain str fields, see schemas.py) specifically so that
    # any pydantic-level rejection can't happen before this point either -
    # otherwise FastAPI would 422 the request before this function body
    # (and this check) ever ran.
    ip_address = request.client.host if request.client else "unknown"
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=settings.registration_rate_limit_window_minutes)
    recent_attempt_times = db.scalars(
        select(RegistrationAttempt.attempt_time)
        .where(RegistrationAttempt.ip_address == ip_address)
        .where(RegistrationAttempt.attempt_time > window_start)
        .order_by(RegistrationAttempt.attempt_time)
    ).all()
    if len(recent_attempt_times) >= settings.registration_rate_limit_max_attempts:
        # The window clears from its oldest end, not all at once - once the
        # earliest of these attempts ages past the window, the count drops
        # below the limit again and a retry succeeds.
        retry_at = recent_attempt_times[0] + timedelta(minutes=settings.registration_rate_limit_window_minutes)
        wait_seconds = max(int((retry_at - now).total_seconds()), 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Please try again in {_format_wait_text(wait_seconds)}.",
            headers={"Retry-After": str(wait_seconds)},
        )
    # Committed immediately, decoupled from whatever happens next - a bad
    # csrf token, wrong captcha, or failed content validation below must
    # still burn this slot, not roll back with the rest of the request.
    db.add(RegistrationAttempt(ip_address=ip_address))
    db.commit()

    if not payload.csrf_token or payload.csrf_token != request.session.get("csrf_token"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid security token")
    request.session.pop("csrf_token", None)

    stored_captcha = request.session.pop("captcha_result", None)
    if stored_captcha is None or abs(payload.captcha_answer - stored_captcha) > CAPTCHA_TOLERANCE_PX:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect security check")

    try:
        validate_registration_username(payload.username)
        validate_registration_email(payload.email)
        validate_registration_password(payload.password)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(err))

    # Case-insensitive on both sides: "Canyagiz" and "canyagiz" (or two
    # differently-cased emails) must collide as the same account, not
    # register as two - a plain == comparison let that duplicate through.
    existing = db.scalar(
        select(User).where(
            (func.lower(User.username) == payload.username.lower())
            | (func.lower(User.email) == payload.email.lower())
        )
    )
    if existing:
        # Nothing to commit here - the RegistrationAttempt above was
        # already committed on its own, and this was only a read.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already exists")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    # Promote immediately if this address is on the admin allowlist (root
    # config email, or one an admin pre-authorized before this person
    # registered) - see services/admin.py.
    sync_user_role(db, user)
    try:
        db.commit()
    except IntegrityError:
        # Two requests for the same (or same-but-differently-cased)
        # username/email racing past the check above - the check above is
        # best-effort, this is the actual guarantee (DB-level unique index
        # on lower(username)/lower(email), see the matching migration).
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username or email already exists")

    # Verify the email address right away, the way most sites do it -
    # not deferred until whatever this person's first login happens to
    # be. two_factor_enabled defaults to True for every new account (see
    # models.py), so this always fires. verify-2fa/resend-2fa below don't
    # need to change for this - both already key off pending_2fa_user_id
    # in the session, whether login() set it or this did.
    code = generate_two_factor_code()
    expires_at = datetime.utcnow() + timedelta(seconds=settings.two_factor_code_ttl_seconds)
    db.add(TwoFactorCode(user_id=user.id, code=code, expires_at=expires_at))
    db.commit()
    send_two_factor_code(user.email, user.username, code)

    request.session["pending_2fa_user_id"] = user.id
    return LoginResult(
        success=True,
        require_2fa=True,
        message=f"A verification code has been sent to {mask_email(user.email)}",
    )


@router.post("/login", response_model=LoginResult)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # Case-insensitive, and matches either username or email - both are
    # unique per user (see the matching lower() indexes on User), so
    # matching on either can never resolve to more than one account.
    identifier = payload.username.lower()
    user = db.scalar(
        select(User).where(
            (func.lower(User.username) == identifier) | (func.lower(User.email) == identifier)
        )
    )

    # Deliberately no plaintext fallback here: the old repo accepted
    # `password === stored_value` as a bypass, which was a real backdoor.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    if user.two_factor_enabled:
        # The pending user id lives server-side in the session, never in the
        # response body - the client can't verify 2FA for an arbitrary user.
        request.session["pending_2fa_user_id"] = user.id

        # Signing in again (e.g. after closing the code dialog) must not
        # be a free way to re-trigger a send that resend-2fa would have
        # rate-limited - the earlier, still-valid/unexpired code just
        # gets re-shown instead of firing another email.
        if _two_factor_cooldown_remaining(db, user.id) > 0:
            return LoginResult(
                success=True,
                require_2fa=True,
                message=f"A code was already sent to {mask_email(user.email)} - check your email.",
            )

        code = generate_two_factor_code()
        expires_at = datetime.utcnow() + timedelta(seconds=settings.two_factor_code_ttl_seconds)
        db.query(TwoFactorCode).filter(
            TwoFactorCode.user_id == user.id, TwoFactorCode.used == False  # noqa: E712
        ).update({"used": True})
        db.add(TwoFactorCode(user_id=user.id, code=code, expires_at=expires_at))
        db.commit()

        send_two_factor_code(user.email, user.username, code)

        return LoginResult(
            success=True,
            require_2fa=True,
            message=f"A verification code has been sent to {mask_email(user.email)}",
        )

    # Overwriting this column invalidates any other browser/device already
    # signed into this account - see the comparison in deps.get_current_user.
    user.active_session_token = secrets.token_hex(32)
    request.session["user_id"] = user.id
    request.session["session_token"] = user.active_session_token
    sync_user_role(db, user)
    db.add(LoginEvent(user_id=user.id))
    db.commit()
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
    # 2FA is only meant to confirm the email address once, right after
    # registration - not on every subsequent login. The first successful
    # verification turns it off for this account; future logins skip
    # straight through.
    user.two_factor_enabled = False
    sync_user_role(db, user)
    # This is the moment a 2FA login actually succeeds - the sign-in is
    # recorded here, not in /login (which only sent the code).
    db.add(LoginEvent(user_id=user.id))
    # Overwriting this column invalidates any other browser/device already
    # signed into this account - see the comparison in deps.get_current_user.
    user.active_session_token = secrets.token_hex(32)
    db.commit()

    request.session.pop("pending_2fa_user_id", None)
    request.session["user_id"] = user.id
    request.session["session_token"] = user.active_session_token
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

    # Cooldown against hammering this button - without it, nothing stops
    # hundreds of resend clicks from each firing a fresh email/SMS.
    wait_seconds = _two_factor_cooldown_remaining(db, user.id)
    if wait_seconds > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait {_format_wait_text(wait_seconds)} before requesting another code.",
            headers={"Retry-After": str(wait_seconds)},
        )

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
