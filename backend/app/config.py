from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    secret_key: str = "change-me"
    database_url: str = "sqlite:///./fpga_remote_lab.db"
    # Flip to True once served over HTTPS (it will be, on CT210's real domain).
    session_cookie_secure: bool = False

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
    expiry_sweep_interval_seconds: int = 60

    two_factor_code_ttl_seconds: int = 60
    registration_rate_limit_window_minutes: int = 15
    registration_rate_limit_max_attempts: int = 5


settings = Settings()
