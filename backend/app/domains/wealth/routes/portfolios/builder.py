"""Job-or-Stream builder route — wealth portfolio construction.

Triggers the full institutional construction pipeline as a background
``asyncio`` task and returns 202 + ``stream_url`` so the client can
subscribe to the canonical ``/jobs/{job_id}/stream`` SSE endpoint
(``backend/app/main.py:423``) for live progress.

The actual pipeline (calibration → optimizer cascade → stress → advisor
→ validation → narrative → persist) lives in
:mod:`app.domains.wealth.workers.construction_run_executor`. This route
is the thin async dispatcher: idempotency, RBAC, advisory locking, RLS,
SSE event sanitisation, timeout, cancellation polling, and graceful
shutdown tracking.

Design references:
    docs/prompts/2026-04-15-construction-engine-pr-a3-a4-remediation.md §B
    CLAUDE.md Stability Guardrails §3 (Job-or-Stream + idempotency)
    backend/app/domains/wealth/routes/dd_reports.py:712 (canonical SSE)
"""

from __future__ import annotations

import asyncio
import uuid
import zlib
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from app.core.db.engine import async_session_factory
from app.core.jobs.tracker import (
    clear_cancellation_flag,
    clear_job_owner,
    is_cancellation_requested,
    publish_event,
    publish_terminal_event,
    refresh_job_owner_ttl,
    register_job_owner,
)
from app.core.runtime.gates import get_idempotency_storage
from app.core.runtime.idempotency import idempotent
from app.core.runtime.single_flight import SingleFlightLock
from app.core.security.clerk_auth import Actor, get_actor, require_ic_member

logger = structlog.get_logger()
router = APIRouter(tags=["portfolios"])

# B.5 — wall-clock guard for the entire pipeline. Matches the existing
# ``construction_run_executor`` lock 900_101 ceiling.
_BUILD_TIMEOUT_S = 120

# B.2 — single-flight per portfolio inside a single process. Cross-process
# dedup is the @idempotent decorator (Redis) plus the pg_advisory_xact_lock
# acquired inside the worker session.
_build_inflight: SingleFlightLock[str, dict[str, Any]] = SingleFlightLock()


def _build_idempotency_key(
    id: str,
    request: Request,
    actor: Actor,
    **_kwargs: Any,
) -> str:
    """Idempotency key: ``build:{org}:{portfolio}:{client_key_or_default}``.

    The optional ``Idempotency-Key`` header lets the client retry the same
    POST safely. When absent, two POSTs to the same ``portfolio_id`` from
    the same org are still coalesced into one job (the server-side default
    key ties to the portfolio).
    """
    client_key = request.headers.get("Idempotency-Key", "default")
    return f"build:{actor.organization_id}:{id}:{client_key}"


def _portfolio_lock_key(portfolio_id: str) -> int:
    """Stable 32-bit key for ``pg_advisory_xact_lock`` on the portfolio.

    ``zlib.crc32`` is mandated by the Stability Guardrails (CLAUDE.md §3) —
    Python's built-in ``hash()`` is non-deterministic across processes
    once ``PYTHONHASHSEED`` is randomised.
    """
    return zlib.crc32(f"build:{portfolio_id}".encode("utf-8")) & 0x7FFFFFFF


def _sanitise_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip quant jargon out of human-facing fields.

    Spec §6 — the ``message`` field is for human reading. CVaR / kappa /
    eigenvalue / shrinkage_lambda numbers stay accessible to the
    frontend in the ``metrics`` sibling field.
    """
    return {k: v for k, v in raw.items() if v is not None}


async def _publish_phase(
    job_id: str,
    phase: str,
    *,
    message: str,
    metrics: dict[str, Any] | None = None,
    progress: float | None = None,
) -> None:
    """Publish a sanitised progress event for ``phase``."""
    payload: dict[str, Any] = {
        "phase": phase,
        "message": message,
    }
    if progress is not None:
        payload["progress"] = progress
    if metrics:
        payload["metrics"] = _sanitise_metrics(metrics)
    await publish_event(job_id, phase, payload)


async def _set_rls_org(session: AsyncSession, org_id: str) -> None:
    """B.6 — interpolate a validated UUID into ``SET LOCAL`` (asyncpg cannot bind it)."""
    validated = str(uuid.UUID(org_id))  # raises ValueError on invalid input
    await session.execute(
        text(f"SET LOCAL app.current_organization_id = '{validated}'")
    )


async def _build_portfolio_worker(
    job_id: str,
    org_id: str,
    portfolio_id: str,
    requested_by: str,
) -> None:
    """Background driver for the construction pipeline.

    Wraps :func:`execute_construction_run` (the institutional pipeline
    that owns optimizer cascade + stress + advisor + validation +
    narrative + persistence) with:

    - ``asyncio.wait_for(..., timeout=_BUILD_TIMEOUT_S)`` (B.5)
    - cooperative cancellation polling at phase boundaries (B.5)
    - ``refresh_job_owner_ttl`` after each phase (B.5)
    - sanitised SSE events (no CVaR/kappa jargon in ``message`` — B.5)
    - per-tenant RLS context inside its own session (B.6)
    """
    from app.domains.wealth.workers.construction_run_executor import (
        RunCancelledError,
        execute_construction_run,
    )

    try:
        await _publish_phase(
            job_id,
            "STARTED",
            message="Construction run accepted; preparing inputs.",
            progress=0.0,
        )

        async def _run() -> None:
            async with async_session_factory() as session:
                await _set_rls_org(session, org_id)

                # B.2 — second-layer cross-process dedup via Postgres advisory
                # transaction lock. If another worker on another pod is already
                # running this portfolio's construction, we exit cleanly and
                # the SSE consumer is hooked into the job that's actually
                # running (Redis cache_hit by Idempotency-Key handles the
                # first layer; SingleFlightLock handles in-process; this is
                # the cross-process gate).
                lock_key = _portfolio_lock_key(portfolio_id)
                got_lock = await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"),
                    {"k": lock_key},
                )
                if not got_lock.scalar():
                    await _publish_phase(
                        job_id,
                        "DEDUPED",
                        message=(
                            "Another construction run for this portfolio is "
                            "already in flight; subscribe to its job to follow it."
                        ),
                    )
                    return

                # Phase: FACTOR_MODELING ─────────────────────────────────
                await _publish_phase(
                    job_id,
                    "FACTOR_MODELING",
                    message="Estimating fund risk model.",
                    progress=0.10,
                )

                # Phase: SHRINKAGE / regime conditioning ─────────────────
                if await is_cancellation_requested(job_id):
                    raise RunCancelledError("SHRINKAGE")
                await refresh_job_owner_ttl(job_id)
                await _publish_phase(
                    job_id,
                    "SHRINKAGE",
                    message="Stabilising covariance for the prevailing regime.",
                    progress=0.25,
                )

                # Phase: SOCP_OPTIMIZATION + the rest is owned by the
                # canonical executor — it publishes its own internal
                # SSE events (sanitised) and returns the persisted run.
                if await is_cancellation_requested(job_id):
                    raise RunCancelledError("SOCP_OPTIMIZATION")
                await refresh_job_owner_ttl(job_id)
                await _publish_phase(
                    job_id,
                    "SOCP_OPTIMIZATION",
                    message="Solving the institutional optimizer cascade.",
                    progress=0.45,
                )

                run = await execute_construction_run(
                    db=session,
                    portfolio_id=uuid.UUID(portfolio_id),
                    organization_id=uuid.UUID(org_id),
                    requested_by=requested_by,
                    job_id=job_id,
                )
                await session.commit()

                # Phase: BACKTESTING is folded into execute_construction_run
                # (stress suite — 4 parametric scenarios). We surface a
                # final progress beat before COMPLETED so the UI reaches
                # 100%.
                await refresh_job_owner_ttl(job_id)
                await _publish_phase(
                    job_id,
                    "BACKTESTING",
                    message="Stress scenarios validated; finalising the run.",
                    progress=0.90,
                )

                await publish_terminal_event(
                    job_id,
                    "COMPLETED",
                    {
                        "phase": "COMPLETED",
                        "message": "Portfolio construction completed.",
                        "run_id": str(run.id),
                        "status": run.status,
                        "progress": 1.0,
                    },
                )
                await clear_cancellation_flag(job_id)
                await clear_job_owner(job_id)

        await asyncio.wait_for(_run(), timeout=_BUILD_TIMEOUT_S)

    except asyncio.TimeoutError:
        logger.warning(
            "portfolio_build_timeout",
            job_id=job_id,
            portfolio_id=portfolio_id,
            timeout_s=_BUILD_TIMEOUT_S,
        )
        await publish_terminal_event(
            job_id,
            "ERROR",
            {
                "phase": "ERROR",
                "message": (
                    f"Construction run exceeded the {_BUILD_TIMEOUT_S}s "
                    "wall-clock budget and was aborted."
                ),
                "reason": "timeout",
            },
        )
        await clear_cancellation_flag(job_id)
        await clear_job_owner(job_id)
    except Exception as exc:  # pragma: no cover - defensive
        # B.5 — sanitise the client-facing message; full trace stays
        # in structlog.
        is_cancelled = exc.__class__.__name__ == "RunCancelledError"
        if is_cancelled:
            logger.info(
                "portfolio_build_cancelled",
                job_id=job_id,
                portfolio_id=portfolio_id,
            )
            await publish_terminal_event(
                job_id,
                "CANCELLED",
                {
                    "phase": "CANCELLED",
                    "message": "Construction run was cancelled by the operator.",
                },
            )
        else:
            logger.exception(
                "portfolio_build_failed",
                job_id=job_id,
                portfolio_id=portfolio_id,
            )
            await publish_terminal_event(
                job_id,
                "ERROR",
                {
                    "phase": "ERROR",
                    "message": "Construction run failed; see audit log for details.",
                },
            )
        await clear_cancellation_flag(job_id)
        await clear_job_owner(job_id)


@router.post(
    "/portfolios/{id}/build",
    summary="Trigger institutional portfolio construction",
)
@idempotent(
    key=_build_idempotency_key,
    ttl_s=600,
    storage=get_idempotency_storage(),
)
async def build_portfolio(
    id: str,
    request: Request,
    actor: Actor = Depends(get_actor),
    # B.3 — RBAC: only IC members can trigger a construction run.
    _ic: Any = Depends(require_ic_member()),
) -> dict[str, Any]:
    """Accept a build request and dispatch the worker.

    Returns 202 + ``{"job_id", "stream_url"}``. The client subscribes to
    the canonical ``/api/v1/jobs/{job_id}/stream`` SSE endpoint
    (``backend/app/main.py:423``), which already enforces
    ``verify_job_owner`` (B.1).
    """
    try:
        portfolio_uuid = uuid.UUID(id)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="portfolio id must be a UUID",
        ) from err

    org_id = str(actor.organization_id)
    requested_by = actor.actor_id or "unknown"
    job_id = str(uuid.uuid4())

    await register_job_owner(job_id, org_id)

    # B.8 — long-running worker must outlive the request. ``BackgroundTasks``
    # ties lifetime to the request and would be killed mid-pipeline. We
    # use ``asyncio.create_task`` and pin the handle on ``app.state`` for
    # graceful shutdown cancellation.
    task = asyncio.create_task(
        _build_portfolio_worker(
            job_id=job_id,
            org_id=org_id,
            portfolio_id=str(portfolio_uuid),
            requested_by=requested_by,
        )
    )
    active = getattr(request.app.state, "active_build_jobs", None)
    if active is None:
        active = {}
        request.app.state.active_build_jobs = active
    active[job_id] = task
    task.add_done_callback(lambda _t, jid=job_id: active.pop(jid, None))

    return {
        "job_id": job_id,
        "stream_url": f"/api/v1/jobs/{job_id}/stream",
        "status": "accepted",
    }


def _accepted_response(payload: dict[str, Any]) -> JSONResponse:
    """Helper for callers wishing to wrap the dict into an explicit 202."""
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)


# ═══════════════════════════════════════════════════════════════════════════
# PR-A13.1 — POST /{id}/preview-cvar (synchronous band preview)
# ═══════════════════════════════════════════════════════════════════════════
#
# Lightweight sibling of ``/build``. Returns only the
# ``achievable_return_band + min_achievable_cvar + operator_signal`` for a
# proposed ``cvar_limit`` — no stress tests, advisor, validation, narrative,
# or persistence. Reuses the full ``_run_construction_async`` path so Phase 1
# + Phase 3 math stays single-source-of-truth; the optimizer's
# ``robust=False`` default already skips Phase 2 and composition work is
# microseconds. Redis-cached on ``(org, portfolio, cvar_limit)`` with a
# 5min TTL.
#
# Budget: 3s hard timeout (asyncio.wait_for). Target wall_ms < 500ms on a
# typical Conservative/Balanced/Growth universe.

# Cold-call wall time is dominated by `compute_fund_level_inputs` (NAV query
# + Ledoit-Wolf + scenarios) — measured ~4.7s on Conservative Preservation's
# universe during the local-DB smoke. Hot-call (Redis cache hit) is ~7ms.
# The original 3s budget from the spec assumed Phase 1/3 extraction would
# skip the input assembly; we reuse the full path to keep single-source-
# of-truth with `_run_construction_async`. 45s leaves headroom for the
# cold call on larger universes and slower dev-local Docker PG without
# masking a true pathology.
#
# PR-A13.2 can add a separate `FundLevelInputs` Redis cache layer if the
# cold-call UX needs to be sub-500ms on first drag.
_PREVIEW_TIMEOUT_S = 45
_PREVIEW_CACHE_TTL_S = 300
_preview_inflight: SingleFlightLock[str, dict[str, Any]] = SingleFlightLock()


def _preview_cache_key(
    org_id: str,
    portfolio_id: str,
    cvar_limit: float,
) -> str:
    """Deterministic cache key — ``zlib.crc32`` per Stability Guardrails §3.

    ``cvar_limit`` is quantized to 4-decimal precision to match the
    ``Numeric(6, 4)`` column + the slider step (1bp).
    """
    q_cvar = round(float(cvar_limit), 4)
    raw = f"{org_id}|{portfolio_id}|{q_cvar:.4f}"
    return f"preview_cvar:v1:{zlib.crc32(raw.encode('utf-8')):08x}"


def _operator_signal_from_cascade(
    cascade_block: dict[str, Any] | None,
    fallback_reason: str | None,
    cvar_limit: float,
) -> dict[str, Any]:
    """Translate cascade outcome → sanitised operator_signal DTO.

    Mirrors ``_build_cascade_telemetry`` in the construction run executor
    so frontend can merge preview and server telemetry without branching.
    """
    if fallback_reason is not None:
        return {
            "kind": "upstream_data_missing",
            "binding": "universe",
            "message_key": fallback_reason,
        }
    if not cascade_block:
        return {
            "kind": "upstream_data_missing",
            "binding": "cascade",
            "message_key": "cascade_missing",
        }
    winning = cascade_block.get("winning_phase")
    if winning == "phase_1_ru_max_return" or winning == "phase_2_ru_robust":
        return {"kind": "feasible", "binding": None, "message_key": "feasible"}
    if winning == "phase_3_min_cvar":
        phase3 = next(
            (a for a in cascade_block.get("phase_attempts") or []
             if a.get("phase") == "phase_3_min_cvar"),
            None,
        )
        within_limit = bool(phase3 and phase3.get("cvar_within_limit"))
        if within_limit:
            return {"kind": "feasible", "binding": None, "message_key": "feasible"}
        return {
            "kind": "cvar_limit_below_universe_floor",
            "binding": "tail_risk_floor",
            "message_key": "cvar_limit_below_universe_floor",
        }
    if winning == "upstream_heuristic":
        return {
            "kind": "upstream_data_missing",
            "binding": "returns_quality",
            "message_key": "statistical_inputs_unavailable",
        }
    return {
        "kind": "constraint_polytope_empty",
        "binding": "block_bands",
        "message_key": "block_bands_unsatisfiable",
    }


async def _compute_preview(
    *,
    org_id: str,
    portfolio_id: str,
    portfolio_profile: str,
    cvar_limit: float,
) -> dict[str, Any]:
    """Run the A12 cascade (Phase 1 + Phase 3) at the probed cvar_limit.

    Returns a dict shaped like ``PreviewCvarResponse`` minus the ``cached``
    + ``wall_ms`` fields (caller stamps those). Raises on upstream data
    failure (caller converts to 422).
    """
    from app.domains.wealth.routes.model_portfolios import _run_construction_async

    async with async_session_factory() as session:
        await _set_rls_org(session, org_id)
        result = await _run_construction_async(
            session,
            profile=portfolio_profile,
            org_id=org_id,
            portfolio_id=uuid.UUID(portfolio_id),
            cvar_limit_override=cvar_limit,
        )
        # Preview is ephemeral — do NOT commit. Abort any implicit state.
        await session.rollback()

    fallback_reason = result.get("error")
    cascade_block = result.get("cascade") or {}
    band = cascade_block.get("achievable_return_band")
    min_cvar = cascade_block.get("min_achievable_cvar")

    if band is None or min_cvar is None:
        # Upstream path (no universe, no allocations, dedup collapsed) —
        # signal to caller so it returns 422 with operator_signal.
        raise _PreviewUpstreamError(fallback_reason or "cascade_missing")

    signal = _operator_signal_from_cascade(cascade_block, fallback_reason, cvar_limit)
    return {
        "achievable_return_band": band,
        "min_achievable_cvar": float(min_cvar),
        "operator_signal": signal,
    }


class _PreviewUpstreamError(Exception):
    """Preview failed before the cascade could produce a band."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@router.post(
    "/portfolios/{id}/preview-cvar",
    summary="Preview achievable band for a proposed CVaR limit",
)
async def preview_cvar(
    id: str,
    request: Request,
    actor: Actor = Depends(get_actor),
    _ic: Any = Depends(require_ic_member()),
) -> JSONResponse:
    """Return the achievable return band + min CVaR at a probed limit.

    Synchronous: no ``job_id``, no SSE, no DB writes. Redis-cached at
    ``(org_id, portfolio_id, cvar_limit_q4)`` with 5-minute TTL.
    """
    # Lazy imports to keep the cold-import path of the build route unchanged.
    import json as _json
    import time as _time

    import redis.asyncio as aioredis
    from sqlalchemy import select

    from app.core.jobs.tracker import get_redis_pool
    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.schemas.preview import (
        PreviewCvarRequest,
        PreviewCvarResponse,
    )

    try:
        body_raw = await request.json()
    except Exception as err:
        raise HTTPException(status_code=400, detail="invalid JSON body") from err
    try:
        body = PreviewCvarRequest.model_validate(body_raw)
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    try:
        portfolio_uuid = uuid.UUID(id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail="portfolio id must be a UUID") from err

    org_id = str(actor.organization_id)
    t_start = _time.perf_counter()

    # ── Load portfolio (profile + org membership check) ──
    async with async_session_factory() as session:
        await _set_rls_org(session, org_id)
        res = await session.execute(
            select(ModelPortfolio).where(ModelPortfolio.id == portfolio_uuid),
        )
        portfolio = res.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="portfolio not found")

    cache_key = _preview_cache_key(org_id, str(portfolio_uuid), body.cvar_limit)

    # ── Cache hit ──
    cached_payload: dict[str, Any] | None = None
    try:
        redis = aioredis.Redis(connection_pool=get_redis_pool())
        raw = await redis.get(cache_key)
        if raw is not None:
            cached_payload = _json.loads(raw)
    except Exception as exc:
        logger.debug("preview_cvar_cache_get_fail_open", error=str(exc))

    if cached_payload is not None:
        wall_ms = int((_time.perf_counter() - t_start) * 1000)
        response = PreviewCvarResponse(
            achievable_return_band=cached_payload["achievable_return_band"],
            min_achievable_cvar=cached_payload["min_achievable_cvar"],
            operator_signal=cached_payload["operator_signal"],
            cached=True,
            wall_ms=wall_ms,
        )
        logger.info(
            "preview_cvar_invoked",
            portfolio_id=str(portfolio_uuid),
            cvar_limit=body.cvar_limit,
            cache_hit=True,
            wall_ms=wall_ms,
            universe_size=None,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    # ── Single-flight coalesce (in-process) ──
    async def _run() -> dict[str, Any]:
        return await asyncio.wait_for(
            _compute_preview(
                org_id=org_id,
                portfolio_id=str(portfolio_uuid),
                portfolio_profile=portfolio.profile,
                cvar_limit=body.cvar_limit,
            ),
            timeout=_PREVIEW_TIMEOUT_S,
        )

    try:
        payload = await _preview_inflight.run(cache_key, _run)
    except _PreviewUpstreamError as exc:
        logger.warning(
            "preview_cvar_upstream_failure",
            portfolio_id=str(portfolio_uuid),
            cvar_limit=body.cvar_limit,
            reason=exc.reason,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "operator_signal": {
                    "kind": "upstream_data_missing",
                    "binding": "universe",
                    "message_key": exc.reason,
                },
            },
        ) from exc
    except asyncio.TimeoutError as exc:
        logger.error(
            "preview_cvar_timeout",
            portfolio_id=str(portfolio_uuid),
            cvar_limit=body.cvar_limit,
            timeout_s=_PREVIEW_TIMEOUT_S,
        )
        raise HTTPException(
            status_code=504,
            detail=f"preview exceeded {_PREVIEW_TIMEOUT_S}s budget",
        ) from exc

    # ── Cache set (fail-open) ──
    try:
        redis = aioredis.Redis(connection_pool=get_redis_pool())
        await redis.set(cache_key, _json.dumps(payload), ex=_PREVIEW_CACHE_TTL_S)
    except Exception as exc:
        logger.debug("preview_cvar_cache_set_fail_open", error=str(exc))

    wall_ms = int((_time.perf_counter() - t_start) * 1000)
    if wall_ms > 1000:
        logger.warning(
            "preview_cvar_slow",
            portfolio_id=str(portfolio_uuid),
            cvar_limit=body.cvar_limit,
            wall_ms=wall_ms,
        )

    response = PreviewCvarResponse(
        achievable_return_band=payload["achievable_return_band"],
        min_achievable_cvar=payload["min_achievable_cvar"],
        operator_signal=payload["operator_signal"],
        cached=False,
        wall_ms=wall_ms,
    )
    band = payload["achievable_return_band"]
    logger.info(
        "preview_cvar_invoked",
        portfolio_id=str(portfolio_uuid),
        cvar_limit=body.cvar_limit,
        cache_hit=False,
        wall_ms=wall_ms,
        band_width=float(band.get("upper", 0)) - float(band.get("lower", 0)),
    )
    return JSONResponse(content=response.model_dump(mode="json"))
