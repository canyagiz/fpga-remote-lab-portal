import re
from datetime import date, datetime, time
from urllib.parse import urlparse

import email_validator
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.models import LabStatus, ReservationStatus, UserRole


class MessageOut(BaseModel):
    success: bool
    message: str


class CaptchaOut(BaseModel):
    success: bool = True
    question: str


class RegisterRequest(BaseModel):
    # Deliberately untyped/unconstrained here (plain str, no EmailStr, no
    # Field length limits, no complexity validators) - FastAPI validates
    # the request body against this model *before* the route function
    # body runs, so anything checked here (or via a pydantic
    # field_validator) never counts toward the registration rate limit,
    # which lives inside routers/auth.py::register(). A bad email or a
    # weak password used to skip the limit entirely; a wrong captcha
    # answer still does (see the comment in register() for why that one
    # is a separate, deliberate exception). Real validation - email
    # format/deliverability, password complexity, username length - now
    # happens in register() itself, after the rate-limit gate, via
    # validate_registration_email/validate_registration_password below.
    username: str
    email: str
    password: str
    captcha_answer: int
    csrf_token: str
    # Hidden honeypot field: real users never fill this in.
    website: str = ""


def validate_registration_username(username: str) -> None:
    if len(username) < 3 or len(username) > 50:
        raise ValueError("Username must be between 3 and 50 characters")


def validate_registration_email(email: str) -> None:
    # A real DNS MX lookup, not just syntax - confirmed live that it
    # rejects a domain with no mail exchanger (e.g. "gmail.co", a
    # plausible typo of gmail.com) while accepting real ones. A 2FA code
    # can never arrive at an address that can't receive mail, so letting
    # registration succeed anyway just produces an account that can
    # never be verified.
    try:
        email_validator.validate_email(email, check_deliverability=settings.verify_email_deliverability)
    except email_validator.EmailNotValidError as err:
        raise ValueError(f"This email address can't receive mail: {err}")


def validate_registration_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    # Length alone (the only rule until now) let straight-digit or
    # single-case passwords like "password" or "12345678" through.
    # Requiring upper+lower+digit is a middle ground: real complexity
    # without going as far as mandating a symbol, which tends to push
    # people toward predictable substitutions instead of actual
    # strength (see PasswordStrength.tsx, which still shows a symbol
    # as an optional "Excellent" bonus, not a requirement).
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one number")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResult(BaseModel):
    success: bool
    require_2fa: bool
    message: str | None = None


class Verify2FARequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: UserRole

    model_config = {"from_attributes": True}


class ProfileOut(BaseModel):
    full_name: str | None
    school: str | None
    department: str | None
    age: int | None
    bio: str | None
    social_links: dict[str, str] | None
    # Master share switch and the set of individually-hidden field names -
    # see models.py::UserProfile for what each means.
    is_public: bool
    hidden_fields: list[str] | None

    model_config = {"from_attributes": True}


class PublicProfileOut(BaseModel):
    # Shown to any other signed-in user (e.g. tapping a name on the
    # Calendar). is_public reflects the owner's master switch - when
    # False every other field stays at its default (None), regardless of
    # hidden_fields, which only matters while is_public is True.
    username: str
    is_public: bool
    full_name: str | None = None
    school: str | None = None
    department: str | None = None
    age: int | None = None
    bio: str | None = None
    social_links: dict[str, str] | None = None


#  hostname(s) a social link under this key must point to - anything not
# listed here (currently just "website") is unrestricted.
_SOCIAL_LINK_DOMAINS: dict[str, tuple[str, ...]] = {
    "linkedin": ("linkedin.com", "www.linkedin.com"),
    "github": ("github.com", "www.github.com"),
    "instagram": ("instagram.com", "www.instagram.com"),
    "x": ("x.com", "www.x.com", "twitter.com", "www.twitter.com"),
}


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=100)
    school: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    # ge=0 previously let through obviously-wrong values (e.g. 4). 14/120
    # is a generous real-world bound for a university lab's user base, not
    # a strict age-verification gate.
    age: int | None = Field(default=None, ge=14, le=120)
    bio: str | None = Field(default=None, max_length=1000)
    social_links: dict[str, str] | None = None
    is_public: bool = True
    hidden_fields: list[str] | None = None

    @field_validator("social_links")
    @classmethod
    def social_links_must_point_to_their_own_platform(
        cls, links: dict[str, str] | None
    ) -> dict[str, str] | None:
        # Checked by hostname only, not by fetching/scraping the URL - the
        # backend never makes an outbound request to a user-supplied URL
        # (that would be an SSRF hole: a malicious "linkedin" link could
        # point at an internal address instead). A hostname check can't
        # catch someone else's real profile URL entered by mistake, but it
        # does catch the actual reported problem: a GitHub URL parked in
        # the LinkedIn field, or any link that isn't even a URL.
        if not links:
            return links
        for key, url in links.items():
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f"{key}: '{url}' is not a valid link")
            allowed = _SOCIAL_LINK_DOMAINS.get(key)
            if allowed and parsed.netloc.lower() not in allowed:
                raise ValueError(f"{key} link must point to {allowed[0]}, not {parsed.netloc}")
        return links


class LabOut(BaseModel):
    id: int
    name: str
    description: str | None
    status: LabStatus
    queue_count: int
    image_url: str | None
    keywords: list[str] | None
    features: list[str] | None
    is_public: bool
    # None means available right now; otherwise the earliest moment a new
    # session could start without overlapping an existing reservation -
    # see services/availability.py::next_available_at.
    next_available_at: datetime | None
    guide_url: str | None

    model_config = {"from_attributes": True}


class LabCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    image_url: str | None = None
    backend_url: str | None = None
    keywords: list[str] | None = None
    features: list[str] | None = None
    is_public: bool = False
    guide_url: str | None = None


class LabAccessOut(BaseModel):
    backend_url: str


class ReservationCreate(BaseModel):
    lab_id: int
    reservation_date: date
    reservation_time: time


class JoinQueueRequest(BaseModel):
    lab_id: int


class ReservationOut(BaseModel):
    id: int
    lab_id: int
    lab_name: str
    reservation_date: date | None
    reservation_time: time | None
    status: ReservationStatus
    queue_position: int
    created_at: datetime
    # Only set once the session is actually running (status == active).
    # session_ends_at lets the frontend count down and disable Finish /
    # drop the card once the allotted time is up, without needing to know
    # session_duration_seconds itself.
    usage_start_time: datetime | None
    session_ends_at: datetime | None
    # Only set for a pending, scheduled reservation whose slot has a fixed
    # time - the moment Access stops working for it if nobody clicks it
    # (see services/availability.py::access_deadline). Lets the frontend
    # count down the same grace period access_now itself enforces, instead
    # of guessing at a duplicated magic number.
    access_deadline: datetime | None

    model_config = {"from_attributes": True}


class LabUsageStat(BaseModel):
    lab_id: int
    lab_name: str
    image_url: str | None
    session_count: int


class MyStatsOut(BaseModel):
    # Labs the user has actually run at least one session on (demoed),
    # regardless of how that session ended, vs. labs with at least one
    # cleanly completed session.
    labs_demoed: list[LabUsageStat]
    labs_completed: list[LabUsageStat]
    total_reservations: int
    completed_count: int
    cancelled_count: int
    expired_count: int
    upcoming_count: int
    # Raw sign-in timestamps (tz-aware UTC) rather than server-side daily
    # buckets: the browser groups them by the viewer's local day, same
    # UTC-storage/local-display convention as everywhere else.
    login_times: list[datetime]


class CalendarEntryOut(BaseModel):
    lab_id: int
    lab_name: str
    # Deliberately just the username, not a full profile - see
    # routers/reservations.py::calendar.
    username: str
    status: ReservationStatus
    start_time: datetime
    end_time: datetime


# ---- Admin panel ------------------------------------------------------

class AdminUserSummary(BaseModel):
    """One row in the admin members table."""

    id: int
    username: str
    email: str
    role: UserRole
    created_at: datetime
    # Whether this address is a config-level root admin (Andrea / Yagiz) -
    # the frontend uses it to hide the demote/delete controls, and the
    # backend refuses those operations regardless.
    is_root_admin: bool
    # Distinct labs the user has at least one completed session on, and the
    # total number of completed sessions across all labs.
    completed_labs: int
    completed_sessions: int
    total_reservations: int
    has_profile: bool


class AdminReservationOut(BaseModel):
    id: int
    lab_id: int
    lab_name: str
    status: ReservationStatus
    reservation_date: date | None
    reservation_time: time | None
    created_at: datetime
    usage_start_time: datetime | None
    usage_end_time: datetime | None

    model_config = {"from_attributes": True}


class AdminUserDetail(BaseModel):
    """Full drill-down for one member: identity, the profile fields they
    filled in (admins see everything, ignoring the public/hidden switches
    that only gate peer-to-peer viewing), and their whole reservation
    history."""

    id: int
    username: str
    email: str
    role: UserRole
    created_at: datetime
    is_root_admin: bool
    profile: ProfileOut | None
    reservations: list[AdminReservationOut]


class AdminEntry(BaseModel):
    """One entry in the admin-management list - a root config admin or a
    runtime-granted one, whether or not a matching account exists yet."""

    email: str
    is_root_admin: bool
    # True once someone has actually registered with this address; a
    # granted-but-unregistered admin shows as pending until then.
    is_registered: bool
    user_id: int | None
    username: str | None
    granted_at: datetime | None


class GrantAdminRequest(BaseModel):
    email: str = Field(min_length=3, max_length=100)
