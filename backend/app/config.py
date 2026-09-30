"""Runtime configuration.

Set via environment variables (or `.env` file). Defaults are tuned for **local
dev** — production deployments should set every variable explicitly.
"""
from __future__ import annotations

import logging
import secrets

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -------------------------------------------------------------
    env: str = "dev"  # "dev" | "staging" | "production"

    # --- Database ------------------------------------------------------------
    database_url: str = "sqlite:///./payroll_dev.db"

    # --- Auth ----------------------------------------------------------------
    jwt_secret: str = "change-me-in-production-use-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    allow_public_signup: bool = True  # local development only

    # --- CORS ----------------------------------------------------------------
    cors_origins: str = (
        "http://localhost:3000,https://peopleopslab.in,https://www.peopleopslab.in"
    )
    cors_origin_regex: str = ""  # e.g. r"^https://.*\.vercel\.app$"

    # --- Behaviour flags -----------------------------------------------------
    # Local-only convenience: when True and there is no Authorization header,
    # the API resolves requests to the built-in system user. **Always False in
    # production** — set ALLOW_ANONYMOUS_API=false in your hosting env.
    allow_anonymous_api: bool = True

    # --- Background validation worker ----------------------------------------
    # On by default since the upload screen validates through the queue: a
    # server with no worker would leave every validation waiting forever,
    # which is a silent failure. It was off while nothing enqueued. Turn it off
    # only on a process that must never run validations (e.g. an API replica
    # beside a dedicated `python -m app.worker`).
    validation_worker_enabled: bool = True
    validation_worker_concurrency: int = 1

    # --- PeopleOps Reports ----------------------------------------------------
    report_worker_enabled: bool = True
    report_artifact_max_mb: int = 10
    report_artifact_retention_days: int = 30

    # --- PeopleOps Studio: integration API -----------------------------------
    # Requests per minute per API key. Enforced in the API process: with more
    # than one API instance the effective ceiling multiplies (see ratelimit.py).
    integration_rate_limit_per_minute: int = 120
    # Largest request body the integration API accepts, in megabytes.
    integration_max_request_mb: int = 25
    # Most records one import batch may carry.
    integration_max_records: int = 50000
    # How long a rejected record's own copy is kept for inspection and retry.
    # The rejection itself (row, code, reason) is kept with the run.
    studio_rejection_retention_days: int = 30
    # Encrypts stored connection and webhook secrets (Fernet). One or more
    # urlsafe-base64 32-byte keys, comma separated: the first encrypts, all
    # decrypt, so a key can be rotated in. Unset in production means secrets
    # cannot be stored at all — never stored in clear.
    studio_secret_key: str = ""
    # Local development and tests only: lets connections and webhooks reach
    # private and loopback addresses. Forced off in production.
    studio_allow_private_destinations: bool = False
    # Outbound requests to connected systems.
    studio_http_timeout_seconds: int = 30
    studio_http_max_response_mb: int = 50

    # ------------------------------------------------------------------ utils
    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Render/Heroku style "postgres://" → SQLAlchemy expects "postgresql://"
        if v.startswith("postgres://"):
            return "postgresql+psycopg2://" + v[len("postgres://") :]
        if v.startswith("postgresql://") and "+" not in v.split("://", 1)[0]:
            # Default to psycopg2 driver when no driver is specified
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v


settings = Settings()


# ---------------------------------------------------------------------------
# Production hardening: warn loudly when defaults leak into production.
# ---------------------------------------------------------------------------
if settings.is_production:
    if settings.allow_public_signup:
        logger.warning("Public signup cannot be enabled in production; forcing False.")
        object.__setattr__(settings, "allow_public_signup", False)
    # This comparison *is* the check that the shipped default did not reach
    # production. The literal has to be here for it to work.
    if settings.jwt_secret == "change-me-in-production-use-long-random-secret":  # nosec B105
        # Don't crash — but make sure the operator notices and can't ignore it.
        # Generate a one-shot secret so the process boots; tokens won't survive
        # restarts, forcing the operator to fix the env.
        ephemeral = secrets.token_urlsafe(48)
        logger.error(
            "JWT_SECRET is unset in production — using an ephemeral secret. "
            "Existing tokens will be invalidated on every restart. "
            "Set JWT_SECRET to a stable value!"
        )
        object.__setattr__(settings, "jwt_secret", ephemeral)

    if settings.allow_anonymous_api:
        logger.warning(
            "ALLOW_ANONYMOUS_API=true in production — refusing. Forcing False."
        )
        object.__setattr__(settings, "allow_anonymous_api", False)

    if settings.studio_allow_private_destinations:
        logger.warning("STUDIO_ALLOW_PRIVATE_DESTINATIONS=true in production — refusing. Forcing False.")
        object.__setattr__(settings, "studio_allow_private_destinations", False)

    if settings.database_url.startswith("sqlite"):
        # The most expensive mistake this product can make, because it does not
        # look like a mistake: the service starts, answers, and passes its
        # health check, and then loses every row on the next deploy. Nothing
        # else in the system will say so, so this has to.
        logger.error(
            "DATABASE_URL is unset in production — running on SQLite, on a disk "
            "that does not survive a deploy. Every upload, finding and audit "
            "record written now WILL BE LOST. Point DATABASE_URL at PostgreSQL "
            "before any client data is entered."
        )
