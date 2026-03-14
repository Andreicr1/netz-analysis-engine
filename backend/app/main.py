"""
FastAPI Application — Netz Analysis Engine
============================================

Unified backend serving credit and wealth verticals.
Dual mount pattern: root + /api prefix (for Azure SWA proxy).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config.settings import settings
from app.core.db.engine import engine
from app.core.jobs.sse import create_job_stream
from app.core.jobs.tracker import close_redis_pool, publish_event
from app.core.security.clerk_auth import Actor, get_actor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifespan: validate secrets, log startup, cleanup on shutdown."""
    settings.validate_production_secrets()
    logger.info(
        "Netz Analysis Engine starting — env=%s",
        settings.app_env,
    )
    yield
    # Cleanup
    await engine.dispose()
    await close_redis_pool()
    logger.info("Netz Analysis Engine shutdown complete")


app = FastAPI(
    title="Netz Analysis Engine",
    description="Unified multi-tenant analysis engine for institutional investment verticals",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health endpoints ─────────────────────────────────────────


@app.get("/health", tags=["admin"])
@app.get("/api/health", tags=["admin"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "netz-analysis-engine"}


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
    return await create_job_stream(request, job_id)


# ── SSE test endpoint (dev only) ─────────────────────────────

@api_v1.post("/test/sse/{job_id}/emit", tags=["admin"])
async def test_emit_event(job_id: str, event_type: str = "test", message: str = "hello"):
    """Dev-only: publish a test event to a job channel."""
    if not settings.is_development:
        return {"error": "Only available in development mode"}
    await publish_event(job_id, event_type, {"message": message})
    return {"status": "published", "job_id": job_id, "event": event_type}


# ── Mount API v1 ─────────────────────────────────────────────

app.include_router(api_v1)
