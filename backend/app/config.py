from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "change-me"
    database_url: str = "sqlite:///./fpga_remote_lab.db"
    # Flip to True once served over HTTPS (it will be, on CT210's real domain).
    session_cookie_secure: bool = False
    # Starlette re-signs the session cookie (with a fresh timestamp) on
    # every response, so this is a sliding window: 30 days of inactivity
    # logs you out, but regular use keeps renewing it - the "stay signed
    # in for about a month" behavior most sites have, rather than a hard
    # expiry from the moment you first logged in.
    session_max_age_days: int = 30

    smtp_host: str = ""
    smtp_port: int = 465
    # "ssl" (implicit TLS, e.g. port 465), "starttls" (e.g. port 587), or
    # "plain" (no TLS, no auth - only for a local mock server like Mailpit).
    smtp_mode: str = "ssl"
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from_email: str = "noreply@h-brs.de"
    mail_from_name: str = "FPGA Remote Lab"

    session_duration_seconds: int = 240
    min_reservation_advance_minutes: int = 5
    # Once a scheduled reservation's time arrives, the user has this long to
    # actually click Access before it's given up - see
    # services/availability.py::access_deadline. Sweep interval is kept
    # short relative to this so a missed slot is reflected as `expired`
    # (and drops off the Dashboard) soon after the grace window closes -
    # though the real enforcement is synchronous in access_now itself, not
    # dependent on the sweep ever running.
    access_grace_period_seconds: int = 10
    expiry_sweep_interval_seconds: int = 5

    # Basic Auth credentials the CT300 hardware containers' own
    # labdiscoverylib session API expects from whichever broker calls it.
    # Real values come from .env (gitignored), same as smtp_password above -
    # not hardcoded here.
    weblab_username: str = ""
    weblab_password: str = ""

    # Root administrators, by email. Anyone who registers/logs in with one
    # of these addresses is always an admin and can never be demoted or
    # deleted through the panel - the email itself is the credential (you
    # can't complete first-login for an address without receiving its 2FA
    # code). Additional admins are granted at runtime by an existing admin
    # and live in the admin_emails table; these two are the immutable
    # bootstrap set so the panel can never be locked out. Override via a
    # JSON list in .env (ADMIN_EMAILS='["a@x.com","b@y.com"]') if needed.
    admin_emails: list[str] = [
        "Andrea.Schwandt@h-brs.de",
        "aliyagiz.caniguroglu@gmail.com",
    ]

    # 1 minute (the old repo's value) is too tight in practice - it barely
    # survives the time it takes to switch to a mail client and back, let
    # alone the current Mailpit lookup workflow before real SMTP is wired
    # up. 5 minutes is a more realistic window.
    two_factor_code_ttl_seconds: int = 300
    # Minimum gap between two "resend code" clicks for the same pending
    # verification - without it, nothing stops the button being hammered
    # into sending hundreds of emails.
    two_factor_resend_cooldown_seconds: int = 180
    registration_rate_limit_window_minutes: int = 15
    registration_rate_limit_max_attempts: int = 5
    # Same window/lockout pattern as registration, but counting only
    # FAILED attempts (see models.LoginAttempt) - a burst of wrong
    # passwords from one IP gets locked out; normal login traffic, even
    # a single mistyped password, never gets close to the limit.
    login_rate_limit_window_minutes: int = 15
    login_rate_limit_max_attempts: int = 8
    # A real DNS MX-record lookup at registration time (see schemas.py -
    # RegisterRequest), not just email syntax - catches domains that are
    # syntactically valid but can't actually receive mail (confirmed live:
    # "gmail.co" has no MX record and is rejected; "gmail.com"/"h-brs.de"
    # pass). Off by default in tests (see tests/conftest.py) since it's a
    # real network call and test addresses use the reserved, deliberately
    # mail-less example.com domain.
    verify_email_deliverability: bool = True

    # A board's GPIO controller must be reachable on the network when it
    # is set - a typo or an unplugged Pi is refused rather than saved to
    # fail later. Off in tests, which have no such network.
    verify_endpoint_reachability: bool = True


settings = Settings()
