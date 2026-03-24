"""
FastAPI Application — Netz Analysis Engine
============================================

Unified backend serving credit and wealth verticals.
Dual mount pattern: root + /api prefix (for Cloudflare gateway proxy).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config.settings import settings
from app.core.db.engine import engine
from app.core.jobs.sse import create_job_stream
from app.core.jobs.tracker import close_redis_pool, get_job_state, publish_event, verify_job_owner
from app.core.security.clerk_auth import Actor, get_actor

# ── Admin domain routers ─────────────────────────────────────
from app.domains.admin.routes.assets import router as admin_assets_router
from app.domains.admin.routes.audit import router as admin_audit_router
from app.domains.admin.routes.branding import router as admin_branding_router
from app.domains.admin.routes.configs import router as admin_configs_router
from app.domains.admin.routes.health import router as admin_health_router
from app.domains.admin.routes.inspect import router as admin_inspect_router
from app.domains.admin.routes.internal import router as internal_router
from app.domains.admin.routes.prompts import router as admin_prompts_router
from app.domains.admin.routes.tenants import router as admin_tenants_router

# Actions
from app.domains.credit.actions.routes.actions import router as credit_actions_router

# Dashboard
from app.domains.credit.dashboard.routes import router as credit_dashboard_router
from app.domains.credit.dashboard.task_inbox import router as credit_task_inbox_router
from app.domains.credit.deals.routes.conversion import router as credit_conversion_router

# ── Credit domain routers ────────────────────────────────────
# Deals
from app.domains.credit.deals.routes.deals import router as credit_deals_router
from app.domains.credit.deals.routes.ic_memos import router as credit_ic_memos_router
from app.domains.credit.deals.routes.provenance import router as credit_provenance_router
from app.domains.credit.documents.routes.auditor import router as credit_auditor_router
from app.domains.credit.documents.routes.evidence import router as credit_evidence_router
from app.domains.credit.documents.routes.ingest import router as credit_ingest_router
from app.domains.credit.documents.routes.review import router as credit_review_router

# Documents
from app.domains.credit.documents.routes.upload_url import router as credit_upload_url_router
from app.domains.credit.documents.routes.uploads import router as credit_uploads_router

# Modules — AI (aggregated router), Deals, Documents
from app.domains.credit.modules.ai import (
    get_ai_router_diagnostics,
)
from app.domains.credit.modules.ai import (
    router as credit_ai_router,
)
from app.domains.credit.modules.deals.routes import router as credit_pipeline_deals_router
from app.domains.credit.modules.documents.routes import router as credit_module_documents_router
from app.domains.credit.portfolio.routes.actions import router as credit_portfolio_actions_router
from app.domains.credit.portfolio.routes.alerts import router as credit_alerts_router

# Portfolio
from app.domains.credit.portfolio.routes.assets import router as credit_assets_router
from app.domains.credit.portfolio.routes.fund_investments import (
    router as credit_fund_investments_router,
)
from app.domains.credit.portfolio.routes.obligations import router as credit_obligations_router
from app.domains.credit.reporting.routes.evidence_pack import router as credit_evidence_pack_router
from app.domains.credit.reporting.routes.investor_portal import (
    router as credit_investor_portal_router,
)

# Reporting
from app.domains.credit.reporting.routes.report_packs import router as credit_report_packs_router
from app.domains.credit.reporting.routes.reports import router as credit_reports_router
from app.domains.credit.reporting.routes.schedules import router as credit_schedules_router
from app.domains.wealth.routes.allocation import router as wealth_allocation_router
from app.domains.wealth.routes.analytics import router as wealth_analytics_router
from app.domains.wealth.routes.attribution import router as wealth_attribution_router
from app.domains.wealth.routes.blended_benchmark import router as wealth_blended_benchmark_router
from app.domains.wealth.routes.content import router as wealth_content_router
from app.domains.wealth.routes.correlation_regime import router as wealth_correlation_regime_router
from app.domains.wealth.routes.dd_reports import router as wealth_dd_reports_router
from app.domains.wealth.routes.documents import router as wealth_documents_router
from app.domains.wealth.routes.esma import router as wealth_esma_router
from app.domains.wealth.routes.exposure import router as wealth_exposure_router
from app.domains.wealth.routes.fact_sheets import router as wealth_fact_sheets_router

# ── Wealth domain routers ────────────────────────────────────
from app.domains.wealth.routes.funds import router as wealth_funds_router
from app.domains.wealth.routes.instruments import router as wealth_instruments_router
from app.domains.wealth.routes.macro import router as wealth_macro_router
from app.domains.wealth.routes.manager_screener import router as wealth_manager_screener_router
from app.domains.wealth.routes.model_portfolios import router as wealth_model_portfolios_router
from app.domains.wealth.routes.portfolios import router as wealth_portfolios_router
from app.domains.wealth.routes.risk import router as wealth_risk_router
from app.domains.wealth.routes.screener import router as wealth_screener_router
from app.domains.wealth.routes.strategy_drift import router as wealth_strategy_drift_router
from app.domains.wealth.routes.universe import router as wealth_universe_router
from app.domains.wealth.routes.workers import router as wealth_workers_router

logger = logging.getLogger(__name__)


async def _verify_config_completeness() -> None:
    """Verify all expected (vertical, config_type) pairs exist in vertical_config_defaults.

    Raises RuntimeError in production if any are missing — prevents silent
    YAML fallback masking a failed migration (HC-3).
    In development, logs ERROR but allows startup without full DB seed.
    """
    from sqlalchemy import select

    from app.core.config.config_service import _YAML_FALLBACK_MAP
    from app.core.config.models import VerticalConfigDefault
    from app.core.db.engine import async_session_factory

    # Expected pairs are exactly the keys in _YAML_FALLBACK_MAP —
    # these are the configs that would silently degrade to YAML if missing.
    expected_pairs = set(_YAML_FALLBACK_MAP.keys())

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(
                    VerticalConfigDefault.vertical,
                    VerticalConfigDefault.config_type,
                )
            )
            found = {(row[0], row[1]) for row in result.all()}

        missing = expected_pairs - found
        if missing:
            for vertical, config_type in sorted(missing):
                logger.error(
                    "Missing config default — check migration 0004: (%s, %s)",
                    vertical,
                    config_type,
                )
            if not settings.is_development:
                raise RuntimeError(
                    f"Boot-time config check failed: {len(missing)} config defaults "
                    f"missing from DB. Run 'alembic upgrade head' to seed defaults. "
                    f"Missing: {sorted(missing)}"
                )
            logger.warning(
                "Config defaults missing — continuing in dev mode (YAML fallback active)"
            )
        else:
            logger.info("Config health check OK — all %d defaults present", len(expected_pairs))
    except RuntimeError:
        raise  # re-raise our own RuntimeError
    except Exception as e:
        if not settings.is_development:
            raise RuntimeError(
                f"Boot-time config check failed — DB may not be migrated: {e}"
            ) from e
        logger.error("Config health check failed — DB may not be migrated: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifespan: validate secrets, log startup, cleanup on shutdown."""
    settings.validate_production_secrets()

    # SEC EDGAR identity — must be set once before any edgartools calls.
    # set_identity() is idempotent but NOT thread-safe (closes HTTP clients),
    # so we call it here at startup, before worker threads are spawned.
    try:
        from edgar import set_identity
        set_identity(settings.edgar_identity)
        logger.info("EDGAR identity set to: %s", settings.edgar_identity)
    except ImportError:
        logger.debug("edgartools not installed — EDGAR identity not set")

    logger.info(
        "Netz Analysis Engine starting — env=%s",
        settings.app_env,
    )
    await _verify_config_completeness()

    # Start PgNotifier for config cache invalidation
    from app.core.config.config_service import ConfigService
    from app.core.config.pg_notify import PgNotifier

    pg_notifier: PgNotifier | None = None
    if settings.database_url:
        # Convert async URL to sync for asyncpg (remove +asyncpg suffix)
        raw_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        pg_notifier = PgNotifier(raw_dsn)

        def _on_config_changed(data: dict) -> None:
            ConfigService.invalidate(
                data.get("vertical", ""),
                data.get("config_type", ""),
                data.get("organization_id"),
            )

        pg_notifier.subscribe("config_changed", _on_config_changed)
        await pg_notifier.start()
        app.state.pg_notifier = pg_notifier
        logger.info("PgNotifier started — listening for config changes")

    yield
    # Cleanup
    if pg_notifier:
        await pg_notifier.stop()
    await engine.dispose()
    await close_redis_pool()
    logger.info("Netz Analysis Engine shutdown complete")


app = FastAPI(
    title="Netz Analysis Engine",
    description="Unified multi-tenant analysis engine for institutional investment verticals",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — exact origins + regex for Cloudflare Pages preview subdomains
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://[\w-]+\.netz-(wealth|credit|admin)\.pages\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting (after CORS so preflight OPTIONS requests are not rate-limited)
from app.core.middleware.rate_limit import RateLimitMiddleware  # noqa: E402

app.add_middleware(RateLimitMiddleware)


# ── Health endpoints ─────────────────────────────────────────


@app.get("/health", tags=["admin"])
@app.get("/api/health", tags=["admin"])
async def health() -> dict[str, object]:
    ai_router = get_ai_router_diagnostics()
    status = "ok" if ai_router.status == "healthy" else "degraded"
    return {
        "status": status,
        "service": "netz-analysis-engine",
        "ai_router_status": ai_router.status,
        "ai_router_loaded_modules": list(ai_router.loaded_modules),
        "ai_router_degraded_modules": list(ai_router.degraded_modules),
    }


# ── API v1 router ────────────────────────────────────────────

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/", tags=["admin"])
async def api_root() -> dict:
    return {
        "service": "netz-analysis-engine",
        "version": "0.1.0",
        "verticals": ["credit", "wealth"],
    }


# ── SSE job stream endpoint ──────────────────────────────────

@api_v1.get("/jobs/{job_id}/stream", tags=["jobs"])
async def stream_job(request: Request, job_id: str, actor: Actor = Depends(get_actor)):
    """SSE endpoint for job progress streaming.

    Workers publish events to Redis pub/sub → this endpoint subscribes and streams.
    Frontend consumes via fetch() + ReadableStream (not EventSource — auth headers needed).
    """
    if not await verify_job_owner(job_id, str(actor.organization_id)):
        raise HTTPException(status_code=403, detail="Job not found")
    return await create_job_stream(request, job_id)


# ── Job status polling endpoint (SSE fallback) ───────────────

@api_v1.get("/jobs/{job_id}/status", tags=["jobs"])
async def get_job_status(job_id: str, actor: Actor = Depends(get_actor)):
    """Poll terminal job state from Redis — fallback when SSE connection drops.

    Returns the persisted terminal state (success/degraded/failed) with
    chunk counts, or 404 if the job hasn't reached a terminal state yet.
    Clients should poll this when SSE disconnects before receiving a
    terminal event (done/error/ingestion_complete).
    """
    if not await verify_job_owner(job_id, str(actor.organization_id)):
        raise HTTPException(status_code=403, detail="Job not found")
    state = await get_job_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job state not available yet")
    return state


# ── SSE test endpoint (dev only) ─────────────────────────────

@api_v1.post("/test/sse/{job_id}/emit", tags=["admin"])
async def test_emit_event(job_id: str, event_type: str = "test", message: str = "hello"):
    """Dev-only: publish a test event to a job channel."""
    if not settings.is_development:
        return {"error": "Only available in development mode"}
    await publish_event(job_id, event_type, {"message": message})
    return {"status": "published", "job_id": job_id, "event": event_type}


# ── Mount admin domain routes ────────────────────────────────

api_v1.include_router(admin_branding_router)
api_v1.include_router(admin_assets_router)
api_v1.include_router(admin_configs_router)
api_v1.include_router(admin_tenants_router)
api_v1.include_router(admin_prompts_router)
api_v1.include_router(admin_health_router)
api_v1.include_router(admin_audit_router)
api_v1.include_router(admin_inspect_router)

# ── Mount wealth domain routes ───────────────────────────────

# DEPRECATED: Fund routes kept for backward compat — use /instruments (SR-4)
api_v1.include_router(wealth_funds_router)
api_v1.include_router(wealth_instruments_router)
api_v1.include_router(wealth_allocation_router)
api_v1.include_router(wealth_analytics_router)
api_v1.include_router(wealth_portfolios_router)
api_v1.include_router(wealth_risk_router)
api_v1.include_router(wealth_macro_router)
api_v1.include_router(wealth_workers_router)
api_v1.include_router(wealth_dd_reports_router)
api_v1.include_router(wealth_documents_router)
api_v1.include_router(wealth_universe_router)
api_v1.include_router(wealth_model_portfolios_router)
api_v1.include_router(wealth_fact_sheets_router)
api_v1.include_router(wealth_content_router)
api_v1.include_router(wealth_screener_router)
api_v1.include_router(wealth_manager_screener_router)
api_v1.include_router(wealth_strategy_drift_router)
api_v1.include_router(wealth_attribution_router)
api_v1.include_router(wealth_correlation_regime_router)
api_v1.include_router(wealth_esma_router)
api_v1.include_router(wealth_exposure_router)
api_v1.include_router(wealth_blended_benchmark_router)

# ── Mount credit domain routes ───────────────────────────────

# Deals
api_v1.include_router(credit_deals_router)
api_v1.include_router(credit_ic_memos_router)
api_v1.include_router(credit_provenance_router)
api_v1.include_router(credit_conversion_router)

# Portfolio
api_v1.include_router(credit_assets_router)
api_v1.include_router(credit_alerts_router)
api_v1.include_router(credit_obligations_router)
api_v1.include_router(credit_portfolio_actions_router)
api_v1.include_router(credit_fund_investments_router)

# Documents
api_v1.include_router(credit_uploads_router)
api_v1.include_router(credit_upload_url_router)
api_v1.include_router(credit_review_router)
api_v1.include_router(credit_evidence_router)
api_v1.include_router(credit_auditor_router)
api_v1.include_router(credit_ingest_router)

# Reporting
api_v1.include_router(credit_report_packs_router)
api_v1.include_router(credit_investor_portal_router)
api_v1.include_router(credit_evidence_pack_router)
api_v1.include_router(credit_reports_router)
api_v1.include_router(credit_schedules_router)

# Dashboard
api_v1.include_router(credit_dashboard_router)
api_v1.include_router(credit_task_inbox_router)

# Actions
api_v1.include_router(credit_actions_router)

# Modules — AI, Pipeline Deals, Documents
api_v1.include_router(credit_ai_router)
api_v1.include_router(credit_pipeline_deals_router)
api_v1.include_router(credit_module_documents_router)

# ── Mount API v1 ─────────────────────────────────────────────

app.include_router(api_v1)

# ── Internal routes (Cloudflare Cron Workers only) ───────────
# Mounted on root, not under /api/v1 — gateway blocks /internal/* without secret.
app.include_router(internal_router)
