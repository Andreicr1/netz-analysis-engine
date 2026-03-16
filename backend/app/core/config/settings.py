"""
Application Settings — Netz Analysis Engine
============================================

Merged from Private Credit OS + Wealth OS. Single source of truth for all
environment variables. Uses Pydantic Settings with .env file support.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    adobe_sign_integration_key: str = ""

    # ── SEC EDGAR (public identifier — required by SEC policy) ──
    edgar_identity: str = "Netz Analysis Engine tech@netzco.com"

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

    def validate_production_secrets(self) -> None:
        """Reject weak or missing secrets in production."""
        if self.is_development:
            return
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
