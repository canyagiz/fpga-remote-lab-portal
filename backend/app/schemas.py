from datetime import date, datetime, time

from pydantic import BaseModel, EmailStr, Field

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

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=100)
    school: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    age: int | None = Field(default=None, ge=0, le=150)
    bio: str | None = Field(default=None, max_length=1000)
    social_links: dict[str, str] | None = None


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

    model_config = {"from_attributes": True}


class LabCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    image_url: str | None = None
    backend_url: str | None = None
    keywords: list[str] | None = None
    features: list[str] | None = None
    is_public: bool = False


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
