import re
from datetime import date, datetime, time
from urllib.parse import urlparse

import email_validator
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.config import settings
from app.models import LabStatus, ReservationStatus, UserRole


class MessageOut(BaseModel):
    success: bool
    message: str


class CaptchaOut(BaseModel):
    success: bool = True
    question: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8)
    captcha_answer: int
    csrf_token: str
    # Hidden honeypot field: real users never fill this in.
    website: str = ""

    @field_validator("email")
    @classmethod
    def email_domain_must_accept_mail(cls, email: str) -> str:
        # EmailStr above only checks syntax. This is a real DNS MX lookup -
        # confirmed live that it rejects a domain with no mail exchanger
        # (e.g. "gmail.co", a plausible typo of gmail.com) while accepting
        # real ones, closing the gap a syntax-only check leaves: a 2FA
        # code can never arrive at an address that can't receive mail, so
        # letting registration succeed anyway just produces an account
        # that can never be verified.
        if not settings.verify_email_deliverability:
            return email
        try:
            email_validator.validate_email(email, check_deliverability=True)
        except email_validator.EmailNotValidError as err:
            raise ValueError(f"This email address can't receive mail: {err}")
        return email

    @field_validator("password")
    @classmethod
    def password_must_be_reasonably_complex(cls, password: str) -> str:
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
        return password


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
