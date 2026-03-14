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

    # ── OpenAI / Azure OpenAI ────────────────────────────
    openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_api_version: str = "2025-03-01-preview"

    # ── External APIs ────────────────────────────────────
    fred_api_key: str = ""
    adobe_sign_integration_key: str = ""

    # ── Feature Flags ────────────────────────────────────
    feature_lipper_enabled: bool = False
    feature_auto_rebalance: bool = False

    # ── Calibration ──────────────────────────────────────
    calibration_path: str = ""

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def validate_production_secrets(self) -> None:
        """Reject weak or missing secrets in production."""
        if self.is_development:
            return
        if not self.clerk_jwks_url:
            raise RuntimeError("CLERK_JWKS_URL must be set in production.")
        if self.dev_token == "dev-token-change-me":
            raise RuntimeError("DEV_TOKEN must be changed from default in production.")


settings = Settings()


def get_calibration_path() -> Path:
    """Resolve calibration config directory."""
    if settings.calibration_path:
        return Path(settings.calibration_path).resolve()
    return Path(__file__).resolve().parents[3] / "calibration" / "config"
