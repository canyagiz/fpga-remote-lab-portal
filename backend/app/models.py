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
    # Regenerated on every successful login (see routers/auth.py) and
    # copied into that browser's session cookie. get_current_user compares
    # the two on every request - a second login from another device
    # overwrites this column, which silently invalidates the first
    # device's cookie on its very next request. Single-active-session-
    # per-account, enforced without a separate sessions table.
    active_session_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="user")
    # passive_deletes=True: user_profiles.user_id already has ON DELETE
    # CASCADE at the DB level - without this, SQLAlchemy's ORM doesn't
    # trust that and instead tries to UPDATE the child's FK to NULL
    # before deleting the user, which fails outright since that column
    # is NOT NULL (this actually happened deleting a real account with a
    # filled-in profile). This tells the ORM to just issue the DELETE and
    # let Postgres cascade it, matching what the FK already promises.
    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, passive_deletes=True
    )

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
    # fail loudly (see routers/admin.py::delete_member) rather than silently
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


class LoginAttempt(Base):
    """One row per FAILED login attempt (unknown identifier or wrong
    password), keyed by source IP - see routers/auth.py::login. A
    successful login never writes a row here, so normal use (including a
    single mistyped password) never counts against the window - only a
    string of wrong guesses from the same IP does.
    """

    __tablename__ = "login_attempts"

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


class ShuttleRole(str, enum.Enum):
    master = "master"
    worker = "worker"


class Shuttle(Base):
    """One physical machine running an inventory agent.

    Created by an admin (enrolment), never by an agent announcing
    itself - a machine that merely sends a request must not become part
    of the fleet. The agent authenticates with a token issued at that
    moment; only its hash is kept here.
    """

    __tablename__ = "shuttles"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Admin-chosen label, stable regardless of what the machine calls
    # itself. Reporting is keyed off the token, never off this.
    name: Mapped[str] = mapped_column(String(100))
    # Self-reported by the agent, kept for diagnostics only. Deliberately
    # not trusted for identity: an agent could claim any hostname.
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Where this machine's lab containers are actually reached, e.g.
    # "10.30.70.23". Set by an admin at enrolment and NEVER taken from a
    # report: student browsers are redirected to a URL built from this,
    # so an agent able to set its own address could point users at a host
    # of its choosing. `hostname` above is for humans; this is the only
    # field allowed to influence where traffic goes.
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[ShuttleRole] = mapped_column(Enum(ShuttleRole), default=ShuttleRole.worker)
    # SHA-256 of the token secret. Not bcrypt: the secret is 256 bits of
    # CSPRNG output, so there is no dictionary to slow an attacker down,
    # and this is verified on every report from every shuttle - paying
    # bcrypt's deliberate cost here would buy nothing.
    token_hash: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Absence of this is what marks a node offline; see
    # services/inventory.py::shuttle_status.
    last_report_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enrolled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    devices: Mapped[list["Device"]] = relationship(
        back_populates="shuttle", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_shuttles_name_lower", func.lower(name), unique=True),)


class Device(Base):
    """A piece of hardware an agent reported seeing on its shuttle.

    Every column here is owned by the scanner and overwritten on each
    report - nothing a human types belongs in this table. The human's
    interpretation ("this is EduPow CV #3") is a separate concern and
    binds to `usb_serial`, which is why the serial matters more than the
    row id or the port path.
    """

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    shuttle_id: Mapped[int] = mapped_column(ForeignKey("shuttles.id", ondelete="CASCADE"))
    # Free-form rather than an Enum on purpose: the vocabulary belongs to
    # the agent, and agents are allowed to run ahead of the master (see
    # the versioning note in docs/agent-protocol.md). An unknown kind
    # must round-trip and be visible, not be rejected at the door.
    kind: Mapped[str] = mapped_column(String(32))
    usb_vendor_id: Mapped[str] = mapped_column(String(8))
    usb_product_id: Mapped[str] = mapped_column(String(8))
    # The stable identity when present. Devices without one can only be
    # tracked by port path, which breaks on replug - surfaced to admins
    # rather than silently tolerated.
    usb_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sysfs_path: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Full JTAG chain as last probed, e.g.
    # [{"idcode": "0x3727093", "name": "xc7z020", "kind": "zynq"}].
    # A list because a chain really can hold several parts - a Zynq puts
    # its ARM core alongside the fabric. Null means never probed, which
    # is the normal state: probing is active and takes the chain lock.
    jtag_chain: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # Only meaningful for capture devices. None = could not determine,
    # which is deliberately distinct from False (positively no signal) -
    # only one of those is a fault worth hiding a lab for.
    has_video_signal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # False once a report no longer mentions it. Rows are kept rather
    # than deleted so that "this board was here yesterday" stays
    # answerable after someone unplugs it.
    is_present: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    shuttle: Mapped["Shuttle"] = relationship(back_populates="devices")

    __table_args__ = (
        Index("ix_devices_shuttle_serial", "shuttle_id", "usb_serial"),
        Index("ix_devices_shuttle_path", "shuttle_id", "sysfs_path"),
    )


class FpgaFamily(str, enum.Enum):
    cyclone_iv = "cyclone_iv"
    cyclone_v = "cyclone_v"
    cyclone_10 = "cyclone_10"
    zynq_7020 = "zynq_7020"


class Board(Base):
    """A physical board as a human knows it.

    The bridge between an anonymous USB serial and "the EduPow board in
    room 3". Written once by an admin and rarely touched again - which is
    exactly why it is a separate table from Device, whose every column is
    overwritten on each scan.

    Deliberately NOT tied to a shuttle. A board is wherever its
    programmer currently is; binding it to a machine would mean moving a
    cable required editing the record, which is the manual bookkeeping
    this system exists to remove. The shuttle is derived at query time by
    finding which one currently reports `programmer_serial`.

    A human step here is unavoidable, not a shortcut: an IDCODE
    identifies silicon, not a board. The USB-Blaster in this lab reads
    0x020F30DD, which Quartus resolves to "10CL025(Y|Z)/EP3C25/EP4CE22" -
    one code, three families. Discovery genuinely cannot conclude which
    board this is.
    """

    __tablename__ = "boards"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    family: Mapped[FpgaFamily] = mapped_column(Enum(FpgaFamily))
    # What a JTAG probe should report. Optional, because probing is
    # disruptive and may never have run. When set, a mismatch means the
    # hardware behind this cable changed - which raises a question for a
    # human rather than triggering an automatic decision.
    expected_idcode: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # The identity link. Matches Device.usb_serial, not a device row id:
    # device rows are transient (a replug can create a new one) while a
    # serial is burned into the hardware.
    programmer_serial: Mapped[str] = mapped_column(String(128))
    video_capture_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Where the Raspberry Pi driving this board's switches listens, e.g.
    # "10.30.70.50:20000". Recorded, not yet probed - see
    # services/requirements.py::GpioRequirement.
    gpio_endpoint: Mapped[str | None] = mapped_column(String(128), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # One board per programmer. Claiming a serial that already backs
        # another board is a mistake worth refusing rather than silently
        # producing two boards that are really one.
        Index("ix_boards_programmer_serial", "programmer_serial", unique=True),
        Index("ix_boards_label_lower", func.lower(label), unique=True),
    )


class LabTemplate(Base):
    """What a lab NEEDS - never what it currently has.

    The requirements list is stored as JSON and parsed into typed
    objects by a pydantic discriminated union (see
    services/requirements.py). That choice keeps adding a new kind of
    hardware to a one-class change with no migration, and matches how
    the rest of this schema already stores structured values
    (Lab.keywords, UserProfile.social_links).
    """

    __tablename__ = "lab_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. [{"type": "fpga", "family": "cyclone_iv"},
    #       {"type": "video_capture", "require_signal": true}]
    requirements: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_lab_templates_name_lower", func.lower(name), unique=True),)


class LabDeployment(Base):
    """Binds a catalogue entry to the physical board that serves it.

    Deliberately additive. A Lab with no deployment behaves exactly as it
    always has - its static backend_url is used and it is listed on the
    same rules as before - so shipping this changes nothing until an
    admin creates a deployment for a lab. That is what makes it safe to
    put in front of a running teaching lab.

    Once a deployment exists it takes over two things:
      * the address students are sent to, resolved from wherever the
        board currently is rather than a line in labs.yaml
      * whether the lab is offered at all, from the template's own
        requirements being met right now
    """

    __tablename__ = "lab_deployments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The student-facing catalogue entry this serves.
    lab_id: Mapped[int] = mapped_column(ForeignKey("labs.id", ondelete="CASCADE"), unique=True)
    # What it needs, checked against the shuttle holding the board.
    template_id: Mapped[int] = mapped_column(ForeignKey("lab_templates.id", ondelete="RESTRICT"))
    # Which physical board. No shuttle column: the board is wherever its
    # programmer serial is currently reported, so the shuttle is derived
    # and moving hardware needs no edit here.
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="RESTRICT"))
    # Port of the lab container on whichever shuttle holds the board.
    # A property of how shuttles are provisioned, not of the board, so it
    # travels with the deployment: moving a board to another machine
    # keeps the port and changes only the host. That assumes shuttles are
    # provisioned alike, which is true here and is why the fleet setup is
    # a documented checklist rather than ad-hoc.
    port: Mapped[int] = mapped_column(Integer)
    # Lets an admin take a lab out of service without deleting the
    # binding or touching the catalogue entry.
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lab: Mapped["Lab"] = relationship()
    template: Mapped["LabTemplate"] = relationship()
    board: Mapped["Board"] = relationship()


class AdminEmail(Base):
    """An email granted admin rights at runtime by an existing admin.

    The full admin set is this table UNION settings.admin_emails (the
    immutable root admins in config, which are never stored here). An
    entry may point at a not-yet-registered address: when that person
    registers or logs in, services/admin.py::sync_user_role promotes
    them automatically. Removing a row here revokes the grant (and demotes
    the matching user, if any) - but the config root admins can't be
    revoked, so the panel can never lock itself out.
    """

    __tablename__ = "admin_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(100))
    # Who granted it (null for anything seeded/system-added). SET NULL so
    # deleting the granting admin doesn't erase the grant record.
    added_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # Case-insensitive uniqueness, same pattern as users.email - one
        # grant per address regardless of how it was typed.
        Index("ix_admin_emails_email_lower", func.lower(email), unique=True),
    )
