"""
Application Settings and Configuration
Loads environment variables and provides typed settings
"""
import logging
import secrets
from pydantic_settings import BaseSettings
from typing import List

logger = logging.getLogger(__name__)

# Sentinels we explicitly refuse to run with in production.
_WEAK_SECRET_PATTERNS = (
    "dev-secret-key-change-in-production",
    "change-me",
    "changeme",
    "secret",
    "test",
    "default",
)


class Settings(BaseSettings):
    """Application settings loaded from environment"""

    # Application
    APP_NAME: str = "CrossFit Health OS"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    # Generated per-process when missing — dev convenience only. Production
    # must supply its own via env; the post-init guard below refuses to boot
    # in prod with a missing/weak key.
    SECRET_KEY: str = ""

    # Supabase (optional — legacy, app now uses DATABASE_URL)
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # Database (fallback for local Postgres)
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/crossfit"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Public domain — single source of truth for FRONTEND_URL, CORS,
    # and the support/DPO email defaults. Override per-environment via
    # APP_DOMAIN env var (e.g. crossfit.leicbit.com in prod).
    APP_DOMAIN: str = "localhost:8001"
    APP_SCHEME: str = "http"  # "https" in prod

    # CORS — additional origins beyond the APP_DOMAIN-derived one.
    # The derived origin is appended at startup; this list captures dev
    # extras (e.g. localhost:3000 when running a separate Next.js dev).
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8001",
    ]

    # Frontend URL (used by Stripe success_url, referral share links, etc).
    # Auto-derived from APP_DOMAIN+APP_SCHEME if left empty.
    FRONTEND_URL: str = ""

    # Public contact addresses surfaced in legal docs + help. Default to
    # APP_DOMAIN-derived addresses; override directly to use a different
    # mailbox provider (e.g. Google Workspace forwarding).
    SUPPORT_EMAIL: str = ""
    DPO_EMAIL: str = ""

    # Integrations
    GOOGLE_CALENDAR_CLIENT_ID: str = ""
    GOOGLE_CALENDAR_CLIENT_SECRET: str = ""
    APPLE_TEAM_ID: str = ""
    TODOIST_API_TOKEN: str = ""

    # AI & OCR
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Stripe — leave empty in CI/tests. Real keys go in backend/.env (gitignored).
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLIC_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""  # set after creating the webhook in Stripe Dashboard
    STRIPE_PRICE_ID: str = ""  # set after creating the $29/mo Price (or auto-provisioned)

    # Internal cron auth — shared secret required to hit /internal/cron/*.
    # Operator (Coolify cron job) sends it in the X-Internal-Cron-Secret header.
    INTERNAL_CRON_SECRET: str = ""

    # JWT — short-lived access token + DB-tracked refresh token with rotation.
    # JWT_EXPIRATION_HOURS is kept for back-compat but should be unused;
    # all new code reads JWT_ACCESS_TTL_MINUTES + JWT_REFRESH_TTL_DAYS.
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24
    JWT_ACCESS_TTL_MINUTES: int = 60
    JWT_REFRESH_TTL_DAYS: int = 30

    # Default timezone for calendar events
    DEFAULT_TIMEZONE: str = "America/Sao_Paulo"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


def _validate_secret_key(s: "Settings") -> None:
    """Refuse to boot in production with a weak/missing SECRET_KEY.

    In dev, generate an ephemeral key per-process so first-run isn't blocked.
    Production deploys must supply a strong key via the host environment.
    """
    is_prod = (s.ENVIRONMENT or "").lower() in ("production", "prod", "live")
    key = (s.SECRET_KEY or "").strip()
    weak = (
        not key
        or len(key) < 32
        or any(p in key.lower() for p in _WEAK_SECRET_PATTERNS)
    )

    if is_prod and weak:
        raise RuntimeError(
            "SECRET_KEY is missing or weak in production. "
            "Set a strong random value (>=32 chars) in the host environment."
        )

    if is_prod and s.DEBUG:
        raise RuntimeError("DEBUG must be False when ENVIRONMENT=production.")

    if not key:
        # Dev fallback: ephemeral key. Tokens won't survive a restart, which
        # is intentional — forces the operator to set one for any real use.
        s.SECRET_KEY = secrets.token_urlsafe(48)
        logger.warning(
            "SECRET_KEY missing — generated ephemeral key for this process. "
            "Set SECRET_KEY in your .env for stable sessions."
        )


def _resolve_domain_defaults(s: "Settings") -> None:
    """Fill domain-derived settings when the operator only set APP_DOMAIN.

    Derives ``FRONTEND_URL``, appends the public origin to ``CORS_ORIGINS``,
    and sets ``SUPPORT_EMAIL`` / ``DPO_EMAIL`` to ``<role>@<bare-domain>``.
    """
    domain = (s.APP_DOMAIN or "").strip()
    scheme = (s.APP_SCHEME or "http").strip().lower()
    if not domain:
        return

    public_origin = f"{scheme}://{domain}"
    if not s.FRONTEND_URL:
        s.FRONTEND_URL = public_origin

    if public_origin not in s.CORS_ORIGINS:
        s.CORS_ORIGINS = list(s.CORS_ORIGINS) + [public_origin]

    # Bare domain (strip port) for email addresses.
    bare = domain.split(":", 1)[0]
    if not s.SUPPORT_EMAIL:
        s.SUPPORT_EMAIL = f"support@{bare}"
    if not s.DPO_EMAIL:
        s.DPO_EMAIL = f"dpo@{bare}"


# Global settings instance
settings = Settings()
_validate_secret_key(settings)
_resolve_domain_defaults(settings)
