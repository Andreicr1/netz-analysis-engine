"""
Application Settings — Netz Analysis Engine
============================================

Merged from Private Credit OS + Wealth OS. Single source of truth for all
environment variables. Uses Pydantic Settings with .env file support.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://netz:password@localhost:5434/netz_engine"
    database_url_sync: str = "postgresql+psycopg://netz:password@localhost:5434/netz_engine"
    redis_url: str = "redis://localhost:6379/0"

    # ── Auth (Clerk) ─────────────────────────────────────
    clerk_jwks_url: str = ""
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""

    # ── Dev bypass ───────────────────────────────────────
    dev_actor_header: str = "X-DEV-ACTOR"
    dev_token: str = "dev-token-change-me"

    # ── App ──────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://localhost:5179",
        "http://localhost:5180",
        "http://localhost:4173",
    ]

    # ── Azure Services ───────────────────────────────────
    storage_account_url: str = ""
    keyvault_url: str = ""
    service_bus_namespace: str = ""
    applicationinsights_connection_string: str = ""

    # ── Azure AI Search ──────────────────────────────────
    azure_search_endpoint: str = ""
    azure_search_key: str = ""
    SEARCH_INDEX_NAME: str = ""
    SEARCH_CHUNKS_INDEX_NAME: str = "global-vector-chunks-v2"
    NETZ_ENV: str = "dev"

    # ── Embedding ─────────────────────────────────────────
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"

    # ── OpenAI / Azure OpenAI ────────────────────────────
    openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_api_version: str = "2025-03-01-preview"

    # ── External APIs ────────────────────────────────────
    fred_api_key: str = ""

    # ── SEC EDGAR (public identifier — required by SEC policy) ──
    edgar_identity: str = "Netz Analysis Engine tech@netzco.com"

    # ── Rate Limiting ─────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_default_rpm: int = 100
    rate_limit_compute_rpm: int = 10

    # ── Feature Flags ────────────────────────────────────
    feature_lipper_enabled: bool = False
    feature_auto_rebalance: bool = False
    feature_adls_enabled: bool = False
    feature_wealth_fact_sheets: bool = True
    feature_wealth_content: bool = False
    feature_wealth_monitoring: bool = False

    # ── ADLS Gen2 (Data Lake) ──────────────────────────
    adls_account_name: str = ""
    adls_account_key: str = ""
    adls_container_name: str = "netz-analysis"
    adls_connection_string: str = ""

    # ── Local Storage (dev) ────────────────────────────
    local_storage_root: str = ""

    # ── Calibration ──────────────────────────────────────
    calibration_path: str = ""

    # ── LLM concurrency ──────────────────────────────────
    # Controls asyncio.Semaphore slots for concurrent LLM calls in deep_review.
    # Resolved lazily at call-time; never captured at module level.
    netz_llm_concurrency: int = 5

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def prefixed_index(self, base_name: str) -> str:
        """Apply NETZ_ENV prefix to Azure Search index names.

        Prevents cross-environment contamination (dev/staging/prod).
        Production uses unprefixed names; dev/staging get ``{env}-`` prefix.
        """
        if self.NETZ_ENV in ("prod", "production"):
            return base_name
        return f"{self.NETZ_ENV}-{base_name}"

    def canonical_search_chunks_index_name(self) -> str:
        """Resolve the canonical env-scoped chunks index name."""
        return self.prefixed_index(
            self.SEARCH_CHUNKS_INDEX_NAME or "global-vector-chunks-v2",
        )

    def validate_production_secrets(self) -> None:
        """Reject weak or missing secrets in production."""
        # SR-8: Guard against APP_ENV defaulting to "development" in a real
        # deployment.  If production-grade secrets are present the environment
        # should NOT be "development" — that would silently enable the dev
        # auth bypass (X-DEV-ACTOR header).
        if self.is_development:
            _production_secrets_present = bool(
                self.clerk_secret_key and self.clerk_jwks_url
            )
            if _production_secrets_present:
                _log.critical(
                    "Production auth secrets detected but APP_ENV is "
                    "'development'. Set APP_ENV to 'staging' or 'production' "
                    "to disable the dev auth bypass.",
                )
                raise RuntimeError(
                    "APP_ENV is 'development' but production auth secrets "
                    "(CLERK_SECRET_KEY, CLERK_JWKS_URL) are set. Refusing to "
                    "start — set APP_ENV appropriately.",
                )
            return

        # Non-development: Clerk auth secrets are mandatory.
        if not self.clerk_secret_key:
            raise RuntimeError("CLERK_SECRET_KEY must be set in production.")
        if not self.clerk_jwks_url:
            raise RuntimeError("CLERK_JWKS_URL must be set in production.")
        if self.dev_token == "dev-token-change-me":
            raise RuntimeError("DEV_TOKEN must be changed from default in production.")
        if self.feature_adls_enabled:
            if not self.adls_account_name:
                raise RuntimeError("ADLS_ACCOUNT_NAME must be set when FEATURE_ADLS_ENABLED=true.")
            if not (self.adls_account_key or self.adls_connection_string):
                raise RuntimeError("ADLS credentials (account key or connection string) must be set when FEATURE_ADLS_ENABLED=true.")


settings = Settings()


def get_calibration_path() -> Path:
    """Resolve calibration config directory."""
    if settings.calibration_path:
        return Path(settings.calibration_path).resolve()
    return Path(__file__).resolve().parents[3] / "calibration" / "config"
