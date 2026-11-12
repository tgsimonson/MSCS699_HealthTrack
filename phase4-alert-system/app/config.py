"""application settings read from environment variables (prefix HT_)"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # sqlite works with zero setup; set HT_DATABASE_URL=postgresql+psycopg://... for postgres
    database_url: str = field(default_factory=lambda: os.getenv("HT_DATABASE_URL", "sqlite:///./healthtrack.db"))
    environment: str = field(default_factory=lambda: os.getenv("HT_ENV", "development"))
    # a random secret per process is safe for local work; production must set HT_JWT_SECRET
    jwt_secret: str = field(default_factory=lambda: os.getenv("HT_JWT_SECRET", secrets.token_urlsafe(48)))
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "healthtrack-api"
    jwt_audience: str = "healthtrack-clients"
    access_token_minutes: int = field(default_factory=lambda: int(os.getenv("HT_ACCESS_TOKEN_MINUTES", "15")))
    refresh_token_hours_staff: int = 12
    refresh_token_hours_patient: int = 168
    bcrypt_rounds: int = field(default_factory=lambda: int(os.getenv("HT_BCRYPT_ROUNDS", "12")))
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    login_rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("HT_LOGIN_RATE_LIMIT", "10")))
    max_page_size: int = 200
    max_batch_size: int = 500
    max_query_days: int = 92
    log_level: str = field(default_factory=lambda: os.getenv("HT_LOG_LEVEL", "INFO"))
    sql_echo: bool = field(default_factory=lambda: _bool("HT_SQL_ECHO", False))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(o for o in os.getenv("HT_CORS_ORIGINS", "http://localhost:8050,http://127.0.0.1:8050").split(",") if o))

    # ---------------------------------------------------------------- alerting (phase 4)
    # background jobs: notification dispatch, escalation checks, and pattern detection (off in the test suite)
    alert_workers: bool = field(default_factory=lambda: _bool("HT_ALERT_WORKERS", True))
    dispatch_poll_seconds: float = field(default_factory=lambda: float(os.getenv("HT_DISPATCH_POLL_SECONDS", "2")))
    escalation_check_seconds: int = field(default_factory=lambda: int(os.getenv("HT_ESCALATION_CHECK_SECONDS", "30")))
    pattern_check_minutes: int = field(default_factory=lambda: int(os.getenv("HT_PATTERN_CHECK_MINUTES", "15")))
    # low-severity email is grouped into one digest per recipient, sent daily at this local time
    digest_hour: int = field(default_factory=lambda: int(os.getenv("HT_DIGEST_HOUR", "7")))
    program_timezone: str = field(default_factory=lambda: os.getenv("HT_PROGRAM_TIMEZONE", "America/Denver"))
    # alert-storm cap: past this many non-critical alerts per patient per hour, email and sms go to the digest
    max_noncritical_alerts_per_hour: int = field(default_factory=lambda: int(os.getenv("HT_ALERT_STORM_CAP", "4")))
    notification_max_attempts: int = 3
    # delivery: smtp and an sms gateway webhook when configured, otherwise json-lines files in the outbox folder
    outbox_dir: str = field(default_factory=lambda: os.getenv("HT_OUTBOX_DIR", "./outbox"))
    smtp_host: str | None = field(default_factory=lambda: os.getenv("HT_SMTP_HOST") or None)
    smtp_port: int = field(default_factory=lambda: int(os.getenv("HT_SMTP_PORT", "587")))
    smtp_from: str = field(default_factory=lambda: os.getenv("HT_SMTP_FROM", "alerts@healthtrack.example"))
    sms_webhook_url: str | None = field(default_factory=lambda: os.getenv("HT_SMS_WEBHOOK_URL") or None)
    dashboard_url: str = field(default_factory=lambda: os.getenv("HT_DASHBOARD_URL", "http://localhost:8050"))
    stream_ticket_seconds: int = 60

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and "HT_JWT_SECRET" not in os.environ:
        raise RuntimeError("HT_JWT_SECRET must be set in production")
    return s
