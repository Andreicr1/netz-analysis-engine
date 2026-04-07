"""Screener import job runner.

Stability Guardrails Phase 4 (§4.3 B3.1 + B3.2): the screener import
no longer runs synchronously inside the request handler. The route
validates the input, calls ``dispatch_screener_import``, and returns
``202 Accepted`` with a ``job_id``. The actual work runs as a
background coroutine that publishes progress events to the same
``job:{job_id}:events`` Redis channel the existing SSE infrastructure
already serves.

Why a coroutine and not a separate process worker?
--------------------------------------------------
The import operation is short (hundreds of milliseconds against the
local DB) and bounded. A long-lived worker daemon adds operational
surface for no benefit. The coroutine pattern keeps the work on the
same event loop, reuses the existing job tracker / SSE plumbing, and
gives the route a clean handoff via ``register_job_owner``.

Concurrency guarantees
----------------------
- ``dispatch_screener_import`` returns the same ``job_id`` for the
  same ``(org_id, identifier, block_id)`` triple within ~5 minutes,
  using an in-process ``SingleFlightLock`` keyed on the same triple.
  Cross-process dedup lives one layer up in the ``@idempotent``
  route decorator (§2.7).
- ``run_import_job`` opens its own DB session, sets the RLS org via
  ``SET LOCAL``, and serialises against concurrent calls for the
  same identifier with ``pg_advisory_xact_lock`` (see
  ``screener_import_service.SCREENER_IMPORT_LOCK_ID``).
- Failures publish a typed ``error`` event and persist a terminal
  state via ``persist_job_state`` so SSE clients that reconnect after
  the channel closed can still observe the outcome.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.core.jobs.tracker import (
    persist_job_state,
    publish_event,
    publish_terminal_event,
    register_job_owner,
)
from app.core.runtime.single_flight import SingleFlightLock
from app.domains.wealth.services.screener_import_service import (
    ImportResult,
    ImportStatus,
    import_instrument,
)

logger = structlog.get_logger(__name__)
_stdlog = logging.getLogger(__name__)


# ── In-process dedup for the dispatch path ────────────────────────
#
# Two clicks landing on two different uvicorn workers within the same
# process get coalesced by the ``@idempotent`` decorator (Redis-backed,
# §2.7). Two clicks on the *same* worker race for the same job_id —
# this single-flight lock guarantees only one ``register_job_owner``
# / ``create_task`` pair fires per (org, identifier, block) triple
# during the wait window.
_dispatch_lock: SingleFlightLock[tuple[str, str, str], "JobHandle"] = SingleFlightLock()


@dataclass(frozen=True)
class JobHandle:
    """Return value of ``dispatch_screener_import``.

    The route encodes this as JSON and returns it from the 202
    response so the frontend knows where to attach the SSE stream.
    """

    job_id: str
    identifier: str

    def to_dict(self) -> dict[str, str]:
        return {"job_id": self.job_id, "identifier": self.identifier}


# ── Public API ─────────────────────────────────────────────────────


async def dispatch_screener_import(
    *,
    organization_id: uuid.UUID,
    identifier: str,
    block_id: str | None,
    strategy: str | None,
) -> JobHandle:
    """Spawn a background import task and return the handle.

    Idempotent within the same process for ~5 minutes via
    ``SingleFlightLock``. Cross-process dedup is the @idempotent
    decorator's job at the route layer.
    """
    normalized_id = (identifier or "").strip().upper()
    if not normalized_id:
        raise ValueError("identifier must be non-empty")

    key = (str(organization_id), normalized_id, block_id or "")

    async def _create() -> JobHandle:
        job_id = str(uuid.uuid4())
        await register_job_owner(job_id, str(organization_id))

        # Fire-and-forget the actual work. The task is held by the
        # event loop until completion; we don't await it here because
        # the route has already returned 202 by then.
        asyncio.create_task(
            run_import_job(
                job_id=job_id,
                organization_id=organization_id,
                identifier=normalized_id,
                block_id=block_id,
                strategy=strategy,
            ),
            name=f"screener_import_{job_id}",
        )
        return JobHandle(job_id=job_id, identifier=normalized_id)

    # 5 minute dedup window — long enough to ride out double-click
    # storms but short enough that a stale handle doesn't strand a
    # user looking at progress for a previous attempt.
    return await _dispatch_lock.run(key, _create, ttl_s=300)


async def run_import_job(
    *,
    job_id: str,
    organization_id: uuid.UUID,
    identifier: str,
    block_id: str | None,
    strategy: str | None,
) -> None:
    """Execute the import end-to-end and publish SSE progress events.

    Event sequence on the happy path::

        progress {step: "validating",   pct: 5}
        progress {step: "resolving_sec", pct: 25}
        progress {step: "writing",       pct: 75}
        done     {result: ImportResult.to_dict()}

    On failure::

        error    {code, message, recoverable}
    """
    logger.info(
        "screener_import_started",
        job_id=job_id,
        organization_id=str(organization_id),
        identifier=identifier,
        block_id=block_id,
    )

    try:
        await publish_event(job_id, "progress", {"step": "validating", "pct": 5})

        async with async_session_factory() as db:
            # Bind the org for RLS — services downstream join
            # ``instruments_org`` which has RLS policies.
            #
            # IMPORTANT: ``SET LOCAL <param> = $1`` is invalid SQL —
            # PostgreSQL's ``SET`` command does not accept bind
            # parameters. We use ``set_config(name, value, is_local)``
            # instead, which is the parameter-friendly equivalent and
            # is just as transaction-scoped (third arg ``true``).
            #
            # Reproducible failure mode this guards against: the
            # original ``SET LOCAL`` form silently broke every worker
            # invocation under PostgreSQL — ``import_instrument``
            # never ran, no rows were inserted, the SSE done event
            # was never published. Detected by the Phase 4 reproducible
            # benchmark in ``backend/scripts/benchmark_stability_phase4.py``.
            await db.execute(
                text(
                    "SELECT set_config('app.current_organization_id', :org_id, true)",
                ),
                {"org_id": str(organization_id)},
            )

            await publish_event(
                job_id, "progress", {"step": "resolving_sec", "pct": 25},
            )

            try:
                result: ImportResult = await import_instrument(
                    db,
                    organization_id,
                    identifier,
                    block_id=block_id,
                    strategy=strategy,
                )
            except LookupError as exc:
                await db.rollback()
                await _publish_error(
                    job_id,
                    code="NOT_FOUND",
                    message=str(exc),
                    recoverable=False,
                )
                return
            except ValueError as exc:
                await db.rollback()
                await _publish_error(
                    job_id,
                    code="VALIDATION",
                    message=str(exc),
                    recoverable=False,
                )
                return

            await publish_event(
                job_id, "progress", {"step": "writing", "pct": 75},
            )

            await db.commit()

        await publish_terminal_event(
            job_id,
            "done",
            {"result": result.to_dict()},
        )
        await persist_job_state(
            job_id,
            terminal_state="success" if result.status != ImportStatus.ALREADY_IN_ORG else "degraded",
            attempted_chunk_count=1,
            successful_chunk_count=1,
            failed_chunk_count=0,
            retryable=False,
        )
        logger.info(
            "screener_import_done",
            job_id=job_id,
            instrument_id=result.instrument_id,
            status=result.status.value,
        )

    except Exception as exc:  # noqa: BLE001 — terminal failure path
        _stdlog.exception(
            "screener_import_unhandled job_id=%s identifier=%s",
            job_id,
            identifier,
        )
        try:
            await _publish_error(
                job_id,
                code="UNKNOWN",
                message=f"{type(exc).__name__}: {exc}",
                recoverable=True,
            )
        except Exception:  # noqa: BLE001
            _stdlog.exception(
                "screener_import_publish_failed job_id=%s",
                job_id,
            )


async def _publish_error(
    job_id: str,
    *,
    code: str,
    message: str,
    recoverable: bool,
) -> None:
    """Single sanctioned error publishing path. Sends the typed
    ``error`` event AND persists the terminal state so a reconnect
    after channel close can still observe the failure via the job
    status polling endpoint.
    """
    await publish_terminal_event(
        job_id,
        "error",
        {"code": code, "message": message, "recoverable": recoverable},
    )
    await persist_job_state(
        job_id,
        terminal_state="failed",
        attempted_chunk_count=1,
        successful_chunk_count=0,
        failed_chunk_count=1,
        retryable=recoverable,
        errors=[f"{code}: {message}"],
    )


__all__: list[str] = [
    "JobHandle",
    "dispatch_screener_import",
    "run_import_job",
]


# Sentinel re-export for callers that want to read the worker-side
# constants without importing the service module directly.
def _untyped_any() -> Any:  # pragma: no cover - prevents Any import warning
    return None
