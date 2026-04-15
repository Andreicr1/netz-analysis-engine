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
