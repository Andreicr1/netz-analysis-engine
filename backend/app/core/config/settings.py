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

    # ── Core (REQUIRED) ──────────────────────────────────────
    # database_url: PostgreSQL (Timescale Cloud in prod, docker-compose in dev)
    database_url: str = "postgresql+asyncpg://netz:password@localhost:5434/netz_engine"
    database_url_sync: str = "postgresql+psycopg://netz:password@localhost:5434/netz_engine"
    # redis_url: Upstash in prod, localhost in dev
    redis_url: str = "redis://localhost:6379/0"

    # ── Auth (REQUIRED) ──────────────────────────────────────
    clerk_jwks_url: str = ""
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""

    # ── Dev bypass ───────────────────────────────────────────
    dev_actor_header: str = "X-DEV-ACTOR"
    dev_token: str = "dev-token-change-me"

    # ── App ──────────────────────────────────────────────────
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

    # ── AI (REQUIRED) ────────────────────────────────────────
    openai_api_key: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"

    # ── External APIs ────────────────────────────────────────
    fred_api_key: str = ""

    # ── Data Commons (free key from https://apikeys.datacommons.org/) ──
    dc_api_key: str = ""

    # ── FE fundinfo (production fund data provider) ────────────────
    feature_fefundinfo_enabled: bool = False
    fefundinfo_client_id: str = ""
    fefundinfo_client_secret: str = ""
    fefundinfo_subscription_key: str = ""
    fefundinfo_token_url: str = "https://auth.fefundinfo.com/connect/token"

    # ── SEC EDGAR (public identifier — required by SEC policy) ──
    edgar_identity: str = "Netz Analysis Engine tech@netzco.com"

    # ── Rate Limiting ─────────────────────────────────────────
    rate_limit_enabled: bool = True
    rate_limit_default_rpm: int = 100
    rate_limit_compute_rpm: int = 10

    # ── Feature Flags ────────────────────────────────────────
    feature_lipper_enabled: bool = False
    feature_auto_rebalance: bool = False
    feature_adls_enabled: bool = False
    feature_wealth_fact_sheets: bool = True
    feature_wealth_content: bool = False
    feature_wealth_monitoring: bool = False

    # ── Storage ──────────────────────────────────────────────
    # LocalStorageClient (filesystem) is default for dev.
    # R2StorageClient (Cloudflare R2) is default for prod (Milestone 2.5+).
    # ADLSStorageClient (Azure) is deprecated.
    local_storage_root: str = ""

    # ── Cloudflare R2 ─────────────────────────────────────────
    feature_r2_enabled: bool = False
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "netz-data-lake"
    r2_endpoint_url: str = ""  # auto-derived from r2_account_id if empty

    # ── Local dev providers (NEVER use in production) ─────────
    # LLM: routes pipeline through LM Studio instead of OpenAI API
    use_local_llm: bool = False
    local_llm_url: str = "http://localhost:1234/v1"  # LM Studio default port
    # Embeddings: routes embedding generation through Ollama
    use_local_embeddings: bool = False
    local_embedding_model: str = "nomic-embed-text"
    local_embedding_url: str = "http://localhost:11434"
    local_embedding_dimensions: int = 768
    # OCR: routes document extraction through local provider
    use_local_ocr: bool = False
    local_ocr_provider: str = "pymupdf"  # pymupdf | qwen2vl

    # ── Pipeline cache (reduces API costs during development) ──
    # Caches OCR text and embedding vectors in a local SQLite DB.
    # Cache hit = zero API cost for that step.
    enable_pipeline_cache: bool = False
    pipeline_cache_dir: str = ".data/cache"

    # ── Pipeline mode ─────────────────────────────────────────
    # dry    — local LLM + cached OCR/embeddings, zero paid API calls
    # golden — external providers (Mistral/OpenAI), small curated dataset
    # standard — whatever providers are configured (default)
    pipeline_mode: str = "standard"  # standard | dry | golden

    # ── Confidence fallback (dry mode) ────────────────────────
    # If local LLM classification confidence < threshold, escalate to OpenAI
    local_confidence_threshold: float = 0.0  # 0.0 = never escalate

    # ── Calibration ──────────────────────────────────────────
    calibration_path: str = ""

    # ── LLM concurrency ──────────────────────────────────────
    # Controls asyncio.Semaphore slots for concurrent LLM calls in deep_review.
    # Resolved lazily at call-time; never captured at module level.
    netz_llm_concurrency: int = 5

    # ── DEPRECATED (Azure services — kept for rollback, 2026-03-18) ──────────
    storage_account_url: str = ""  # DEPRECATED: use LocalStorageClient
    keyvault_url: str = ""  # DEPRECATED: use platform env vars (Railway secrets)
    service_bus_namespace: str = ""  # DEPRECATED: use Redis pub/sub + BackgroundTasks
    applicationinsights_connection_string: str = ""  # DEPRECATED: use structlog → stdout
    azure_openai_endpoint: str = ""  # DEPRECATED: use OpenAI direct + retry
    azure_openai_key: str = ""  # DEPRECATED
    azure_openai_api_version: str = "2025-03-01-preview"  # DEPRECATED
    azure_search_endpoint: str = ""  # DEPRECATED: use pgvector
    azure_search_key: str = ""  # DEPRECATED
    SEARCH_INDEX_NAME: str = ""  # DEPRECATED
    SEARCH_CHUNKS_INDEX_NAME: str = "global-vector-chunks-v2"  # DEPRECATED
    NETZ_ENV: str = "dev"  # DEPRECATED: search index prefixing no longer needed
    adls_account_name: str = ""  # DEPRECATED: use LocalStorageClient
    adls_account_key: str = ""  # DEPRECATED
    adls_container_name: str = "netz-analysis"  # DEPRECATED
    adls_connection_string: str = ""  # DEPRECATED

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def prefixed_index(self, base_name: str) -> str:
        """Apply NETZ_ENV prefix to Azure Search index names.

        DEPRECATED: Azure Search replaced by pgvector (2026-03-18).
        Kept for rollback compatibility.
        """
        if self.NETZ_ENV in ("prod", "production"):
            return base_name
        return f"{self.NETZ_ENV}-{base_name}"

    def canonical_search_chunks_index_name(self) -> str:
        """Resolve the canonical env-scoped chunks index name.

        DEPRECATED: Azure Search replaced by pgvector (2026-03-18).
        """
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
        if self.feature_r2_enabled:
            if not self.r2_account_id:
                raise RuntimeError("R2_ACCOUNT_ID must be set when FEATURE_R2_ENABLED=true.")
            if not self.r2_access_key_id or not self.r2_secret_access_key:
                raise RuntimeError("R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY must be set when FEATURE_R2_ENABLED=true.")
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
