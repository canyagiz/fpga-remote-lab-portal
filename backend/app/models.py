import enum
from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"


class LabStatus(str, enum.Enum):
    available = "available"
    occupied = "occupied"


class ReservationStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"


class TwoFactorType(str, enum.Enum):
    email = "email"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Not unique=True/index=True here - uniqueness is enforced case-
    # insensitively instead (see __table_args__ below), so "Alice" and
    # "alice" can't register as two different accounts. A plain unique
    # column constraint would only catch an exact-case duplicate.
    username: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user)
    two_factor_enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="user")
    profile: Mapped["UserProfile | None"] = relationship(back_populates="user", uselist=False)

    __table_args__ = (
        Index("ix_users_username_lower", func.lower(username), unique=True),
        Index("ix_users_email_lower", func.lower(email), unique=True),
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    school: Mapped[str | None] = mapped_column(String(150), nullable=True)
    department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"linkedin": "https://...", "github": "https://...", ...} - a fixed
    # small set of platforms rendered as named fields on the frontend, not
    # an open-ended list, to keep the profile form simple.
    social_links: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    # Master switch: when False, GET /api/profile/{username} (the public
    # view reachable from the Calendar) shows nothing at all, regardless
    # of hidden_fields below - a private profile isn't "everything hidden
    # field-by-field", it's a separate, higher-level gate. Defaults True
    # so existing filled-in profiles don't silently vanish from view the
    # moment this ships.
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    # Field-level opt-outs that only take effect while is_public is True -
    # e.g. ["age", "bio", "social:github"]. Turning is_public off and back
    # on must NOT reset this list - it's the person's own standing
    # preference, not something the master switch is allowed to touch.
    hidden_fields: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship(back_populates="profile")


class Lab(Base):
    __tablename__ = "labs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[LabStatus] = mapped_column(Enum(LabStatus), default=LabStatus.available)
    image_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Direct CT300 hardware endpoint (host:port). Only ever handed to a
    # client that holds an active reservation for this lab - see
    # routers/labs.py::access_lab.
    backend_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    features: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    # Self-hosted prerequisite/orientation reading (frontend/public/guides/) -
    # not a link to an external site. None means this lab has no guide yet.
    guide_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="lab")


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    # No ondelete=CASCADE here on purpose: reservation history is an audit
    # trail of lab usage, so deleting a user with past reservations should
    # fail loudly (see routers/users.py::delete_user) rather than silently
    # erasing that history.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id"))
    reservation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reservation_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus), default=ReservationStatus.pending
    )
    queue_position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    usage_start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    usage_end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Cached WebLab session URL from the hardware container (see
    # routers/labs.py::access_lab). Set once, on the first successful
    # access for this reservation, and reused after that - without this,
    # every call to /access (every tab, every click, every page refresh)
    # would start a brand-new independent session on the same physical
    # board, letting several tabs control the same hardware at once.
    weblab_session_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship(back_populates="reservations")
    lab: Mapped["Lab"] = relationship(back_populates="reservations")


class TwoFactorCode(Base):
    __tablename__ = "two_factor_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(6))
    type: Mapped[TwoFactorType] = mapped_column(Enum(TwoFactorType), default=TwoFactorType.email)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RegistrationAttempt(Base):
    __tablename__ = "registration_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip_address: Mapped[str] = mapped_column(String(45))
    attempt_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LoginEvent(Base):
    """One row per successful sign-in (plain login or the 2FA verify step).

    Powers the Dashboard's daily-login-frequency chart - nothing else
    reads it. CASCADE (unlike reservations) because login history is
    activity telemetry, not an audit trail worth blocking user deletion.
    """

    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
