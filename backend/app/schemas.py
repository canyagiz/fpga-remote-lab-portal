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
    # Photo-based slide-to-fit puzzle (see app/services/captcha.py and
    # components/PuzzleCaptcha.tsx). background_image already has the
    # "hole" baked into its pixels and piece_image is the real photo
    # content that belongs there - the x position that solves it is
    # deliberately NOT included here, only kept server-side in the
    # session, so solving this requires actually looking at the images.
    background_image: str
    piece_image: str
    canvas_width: int
    canvas_height: int
    piece_width: int
    piece_height: int
    piece_top: int


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
    # Despite the name, this is matched against either username or email
    # (see routers/auth.py::login) - kept as "username" rather than
    # renamed to avoid unrelated churn across the frontend/schema/API.
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
    # None for a lab with no deployment - which is every lab until an
    # admin binds one, so adding these changes nothing about the
    # catalogue as it stands today.
    deployment_status: str | None = None
    unavailable_reason: str | None = None

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


class DeleteAccountRequest(BaseModel):
    # Re-entered to confirm identity before an irreversible delete - the
    # session cookie alone is a ~30-day sliding window, so an abandoned
    # open session shouldn't be enough to wipe the account.
    password: str


# ---- Fleet inventory -------------------------------------------------
#
# The agent-contract version this master was written against. A mismatch
# is reported back to the agent as a notice, not rejected: agents are
# deployed per shuttle and will legitimately run ahead of, or behind,
# the portal. See docs/agent-protocol.md.
SCHEMA_VERSION_SUPPORTED = "0.1"
#
# The AgentReport* models below are the master's half of the agent
# contract (docs/agent-protocol.md). Everything an agent sends is
# attacker-controlled input as far as this app is concerned: a shuttle
# holds a token, not trust. Hence the explicit length and list-size
# caps - without them a compromised or buggy agent could push unbounded
# data straight into the database.


class AgentJtagDevice(BaseModel):
    idcode: str = Field(max_length=32)
    name: str | None = Field(default=None, max_length=128)
    kind: str | None = Field(default=None, max_length=64)


class AgentJtagScan(BaseModel):
    tool: str = Field(max_length=32)
    ok: bool
    # A chain can hold several parts (a Zynq reports its ARM core next to
    # the fabric); 16 is far above anything real and well below abuse.
    devices: list[AgentJtagDevice] = Field(default_factory=list, max_length=16)
    error: str | None = Field(default=None, max_length=512)


class AgentDevice(BaseModel):
    kind: str = Field(max_length=32)
    usb_vendor_id: str = Field(max_length=8)
    usb_product_id: str = Field(max_length=8)
    usb_serial: str | None = Field(default=None, max_length=128)
    product: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    sysfs_path: str = Field(max_length=64)
    signature: str | None = Field(default=None, max_length=64)
    jtag: AgentJtagScan | None = None


class AgentVideoDevice(BaseModel):
    dev_node: str = Field(max_length=255)
    card: str | None = Field(default=None, max_length=255)
    driver: str | None = Field(default=None, max_length=64)
    usb_serial: str | None = Field(default=None, max_length=128)
    has_signal: bool | None = None


class AgentReport(BaseModel):
    # Agents and the master are deliberately allowed to run different
    # versions, so unknown extra fields are ignored rather than rejected
    # (pydantic's default) - a newer agent must not break an older
    # master. A schema_version mismatch is surfaced as a warning by the
    # ingest service instead of a hard failure.
    schema_version: str = Field(max_length=16)
    agent_version: str = Field(max_length=32)
    hostname: str = Field(max_length=255)
    scanned_at: str = Field(max_length=64)
    machine_id: str | None = Field(default=None, max_length=64)
    devices: list[AgentDevice] = Field(default_factory=list, max_length=64)
    video: list[AgentVideoDevice] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class AgentReportAccepted(BaseModel):
    success: bool = True
    shuttle_id: int
    devices_recorded: int
    # Anything the master noticed about the report itself - a schema
    # skew, a device it had to drop. Returned so the agent can log it
    # rather than the finding dying in a server log nobody reads.
    notices: list[str] = Field(default_factory=list)


class DeviceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    shuttle_id: int
    kind: str
    usb_vendor_id: str
    usb_product_id: str
    usb_serial: str | None
    product: str | None
    manufacturer: str | None
    sysfs_path: str
    signature: str | None
    jtag_chain: list[dict] | None
    has_video_signal: bool | None
    is_present: bool
    first_seen_at: datetime
    last_seen_at: datetime


class ShuttleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    # Self-reported by the agent - diagnostic only, never trusted.
    hostname: str | None
    # Admin-set, and the only field allowed to influence where student
    # traffic is sent. Surfaced so an admin can actually verify it.
    address: str | None
    role: str
    agent_version: str | None
    last_report_at: datetime | None
    created_at: datetime
    # Derived, not stored: a node is online if it reported recently
    # enough. See services/inventory.py::shuttle_status.
    status: str
    device_count: int


class CreateShuttleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="worker", max_length=16)


class ShuttleEnrolled(BaseModel):
    success: bool = True
    shuttle: ShuttleOut
    # Shown exactly once. Only its hash is stored, so it cannot be
    # recovered later - a lost token means issuing a new one.
    token: str
    message: str = (
        "Store this token now - it is shown only once and cannot be retrieved later."
    )


# ---- Boards and lab templates ----------------------------------------


class BoardCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    family: str = Field(max_length=32)
    # The device this board is identified by. Must currently be reported
    # by some shuttle - claiming a serial nothing has ever seen is almost
    # always a typo, and is refused with that explanation.
    programmer_serial: str = Field(min_length=1, max_length=128)
    expected_idcode: str | None = Field(default=None, max_length=32)
    video_capture_serial: str | None = Field(default=None, max_length=128)
    gpio_endpoint: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class BoardOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    label: str
    family: str
    expected_idcode: str | None
    programmer_serial: str
    video_capture_serial: str | None
    gpio_endpoint: str | None
    notes: str | None
    created_at: datetime
    # Derived, not stored: a board lives wherever its programmer is
    # currently reported, so this changes by itself when hardware moves.
    shuttle_id: int | None = None
    shuttle_name: str | None = None


class UnclaimedDeviceOut(BaseModel):
    """A programmer no board has claimed yet - the "new hardware" queue."""

    device_id: int
    shuttle_id: int
    shuttle_name: str
    usb_serial: str
    product: str | None
    manufacturer: str | None
    signature: str | None
    sysfs_path: str
    jtag_chain: list[dict] | None
    first_seen_at: datetime


class LabTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    # Validated against the requirement union in
    # services/requirements.py before being stored, so a template can
    # never hold a shape the engine cannot later parse.
    requirements: list[dict] = Field(default_factory=list, max_length=32)


class LabTemplateOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    description: str | None
    requirements: list[dict]
    created_at: datetime


class RequirementResultOut(BaseModel):
    type: str
    status: str
    message: str


class GapReportOut(BaseModel):
    shuttle_id: int
    shuttle_name: str
    template_id: int
    template_name: str
    deployable: bool
    missing_count: int
    results: list[RequirementResultOut]


class DeploymentCreate(BaseModel):
    lab_id: int
    template_id: int
    board_id: int
    port: int = Field(ge=1, le=65535)


class DeploymentOut(BaseModel):
    id: int
    lab_id: int
    lab_name: str
    template_id: int
    template_name: str
    board_id: int
    board_label: str
    port: int
    is_enabled: bool
    created_at: datetime
    # All recomputed per request rather than stored: a cached
    # "available" that has gone stale sends a student into a lab that is
    # not there.
    shuttle_id: int | None
    shuttle_name: str | None
    backend_url: str | None
    available: bool
    reason: str | None
    # The last time a real access attempt failed to initialize a session
    # here, distinct from `available` - health-check-passing hardware can
    # still fail a real session open. None once a session opens
    # successfully again.
    last_access_error: str | None
    last_access_error_at: datetime | None


class ShuttleAddressUpdate(BaseModel):
    # Admin-set, never taken from an agent report: this is what student
    # browsers are ultimately pointed at.
    address: str = Field(min_length=1, max_length=255)


class BoardUpdate(BaseModel):
    """Fields a human can revise after registration.

    Deliberately excludes programmer_serial: that is the board's
    identity, and letting it be edited would silently reassign every
    deployment and gap report that resolved through it. Re-register
    instead, which forces the decision to be explicit.
    """

    label: str | None = Field(default=None, min_length=1, max_length=100)
    family: str | None = Field(default=None, max_length=32)
    expected_idcode: str | None = Field(default=None, max_length=32)
    video_capture_serial: str | None = Field(default=None, max_length=128)
    gpio_endpoint: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class DiscoveredHostOut(BaseModel):
    ip: str
    mac: str | None
    vendor: str
    # "raspberry_pi" | "proxmox" | "host"
    kind: str
    open_ports: list[int]
    # Ties the host back to what we already know, so the list is not a
    # wall of anonymous addresses.
    note: str | None = None


class ScanResultOut(BaseModel):
    subnet: str
    duration_ms: int
    hosts: list[DiscoveredHostOut]


# ---- Provisioning (setup wizard) -------------------------------------


class ProvisionRequest(BaseModel):
    # SSH credentials for first contact with the shuttle's Proxmox host.
    # Used only to run the playbook, then discarded - never stored.
    ssh_user: str = Field(min_length=1, max_length=64)
    ssh_password: str = Field(min_length=1, max_length=256)
    # Where to reach it over SSH; defaults to the shuttle's address.
    ssh_host: str | None = Field(default=None, max_length=255)
    # The wizard's "detected devices" step: which boards are attached and
    # how this shuttle's hardware is wired.
    boards: list[str] = Field(default_factory=list)
    device_map: dict[str, str] = Field(default_factory=dict)
    board_uart: dict[str, dict] = Field(default_factory=dict)
    # Intel boards only: path on the shuttle to the licensed installer.
    quartus_installer_path: str = Field(default="", max_length=512)


class ProvisionJobStarted(BaseModel):
    success: bool = True
    job_id: str
    shuttle_id: int
    status: str


class ProvisionJobStatus(BaseModel):
    job_id: str
    shuttle_id: int
    # pending | running | succeeded | failed
    status: str
    returncode: int | None
    started_at: datetime | None
    finished_at: datetime | None
    # The whole log so far; the client remembers how many lines it has
    # already rendered and appends only the rest.
    log: list[str]


# ---- Installer upload (setup wizard) ---------------------------------


class InstallerUploaded(BaseModel):
    # Where the uploaded installer now lives on the shuttle.
    path: str


# ---- SSH check + device detection (setup wizard) ---------------------


class SshCredentials(BaseModel):
    ssh_user: str = Field(min_length=1, max_length=64)
    ssh_password: str = Field(min_length=1, max_length=256)
    ssh_host: str | None = Field(default=None, max_length=255)


class SshCheckResult(BaseModel):
    ok: bool
    message: str


class DetectedDevice(BaseModel):
    present: bool
    path: str
    info: str = ""


class DetectedDevices(BaseModel):
    pve: str = ""
    usb_blaster: DetectedDevice
    capture: DetectedDevice
    videos: list[str] = []
    serial: list[str] = []
