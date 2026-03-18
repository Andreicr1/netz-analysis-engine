"""Pipeline dispatch — route async work to Service Bus or BackgroundTasks.

Centralises the ``USE_SERVICE_BUS`` feature-flag check so every pipeline
endpoint uses the same branching logic:

* **USE_SERVICE_BUS = True** → enqueue via Service Bus (workers pick up)
* **USE_SERVICE_BUS = False** → run in-process via FastAPI BackgroundTasks

Each ``dispatch_*`` function returns a dict suitable for the HTTP response.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import text as _sa_text

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Shared helper: intelligence_status updates ──────────────────────

def update_deal_intelligence_status(
    db_session: Any,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    status: str,
    generated_at: dt.datetime | None = None,
) -> None:
    """Update ``pipeline_deals.intelligence_status`` (and optionally
    ``intelligence_generated_at``) for a single deal.

    Used by both the Service Bus worker and the BackgroundTasks fallback
    to avoid duplicating raw SQL across modules.

    Parameters
    ----------
    db_session:
        An active SQLAlchemy session (will **not** be committed — the
        caller is responsible for commit/rollback).
    deal_id / fund_id:
        Primary-key pair that identifies the pipeline deal row.
    status:
        Target status literal, typically ``"READY"`` or ``"FAILED"``.
    generated_at:
        If provided, also sets ``intelligence_generated_at``.

    """
    if generated_at is not None:
        db_session.execute(
            _sa_text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:s AS intelligence_status_enum), "
                "    intelligence_generated_at = :ts "
                "WHERE id = :id AND fund_id = :fid",
            ),
            {
                "s": status,
                "ts": generated_at,
                "id": str(deal_id),
                "fid": str(fund_id),
            },
        )
    else:
        db_session.execute(
            _sa_text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:s AS intelligence_status_enum) "
                "WHERE id = :id AND fund_id = :fid",
            ),
            {"s": status, "id": str(deal_id), "fid": str(fund_id)},
        )


def _use_service_bus() -> bool:
    return bool(getattr(settings, "USE_SERVICE_BUS", False))


# ── Extraction Pipeline ─────────────────────────────────────────────

def dispatch_extraction(
    *,
    background_tasks: BackgroundTasks,
    source: str,
    deals_filter: str,
    dry_run: bool,
    skip_bootstrap: bool,
    skip_prepare: bool,
    skip_embed: bool,
    skip_enrich: bool,
    no_index: bool,
    job_id: str,
    actor_id: str,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "deals_filter": deals_filter,
        "dry_run": dry_run,
        "skip_bootstrap": skip_bootstrap,
        "skip_prepare": skip_prepare,
        "skip_embed": skip_embed,
        "skip_enrich": skip_enrich,
        "no_index": no_index,
        "job_id": job_id,
        "triggered_by": actor_id,
        "pipeline_name": "unified_pipeline",
        "legacy_path_invoked": False,
    }

    if _use_service_bus():
        from app.services.azure.servicebus_client import send_to_topic

        sb_job_id = send_to_topic("document-pipeline", payload, stage="extraction")
        logger.info("Extraction dispatched via Service Bus job=%s", sb_job_id)
        return {
            "status": "queued",
            "dispatch": "service_bus",
            "job_id": job_id,
            "sb_job_id": sb_job_id,
            "source": source,
            "deals_filter": deals_filter or "(all)",
            "dry_run": dry_run,
            "triggered_by": actor_id,
            "pipeline_name": "unified_pipeline",
        }

    from ai_engine.pipeline.unified_pipeline import run_extraction_pipeline

    def _run() -> None:
        try:
            run_extraction_pipeline(
                source=source,
                deals_filter=deals_filter,
                dry_run=dry_run,
                skip_bootstrap=skip_bootstrap,
                skip_prepare=skip_prepare,
                skip_embed=skip_embed,
                skip_enrich=skip_enrich,
                no_index=no_index,
                job_id=job_id,
            )
        except Exception:
            logger.error("Extraction pipeline failed job=%s source=%s", job_id, source, exc_info=True)

    background_tasks.add_task(_run)
    logger.info("Extraction dispatched via BackgroundTasks job=%s", job_id)
    return {
        "status": "scheduled",
        "dispatch": "background_tasks",
        "job_id": job_id,
        "source": source,
        "deals_filter": deals_filter or "(all)",
        "dry_run": dry_run,
        "triggered_by": actor_id,
        "pipeline_name": "unified_pipeline",
    }


# ── Full Pipeline Ingest ─────────────────────────────────────────────

def dispatch_ingest(
    *,
    background_tasks: BackgroundTasks,
    fund_id: uuid.UUID,
    deal_ids: list[uuid.UUID] | None,
    batch_size: int,
    actor_id: str,
) -> dict[str, Any]:
    payload = {
        "fund_id": str(fund_id),
        "deal_ids": [str(d) for d in deal_ids] if deal_ids else None,
        "batch_size": batch_size,
        "run_ai_analysis": True,
        "actor_id": actor_id,
        "triggered_by": actor_id,
    }

    if _use_service_bus():
        from app.services.azure.servicebus_client import send_to_topic

        sb_job_id = send_to_topic("document-pipeline", payload, stage="ingest")
        logger.info("Ingest dispatched via Service Bus job=%s fund=%s", sb_job_id, fund_id)
        return {
            "status": "queued",
            "dispatch": "service_bus",
            "sb_job_id": sb_job_id,
            "fund_id": str(fund_id),
            "batch_size": batch_size,
            "deal_ids": payload["deal_ids"],
            "triggered_by": actor_id,
        }

    from ai_engine.ingestion.pipeline_ingest_runner import async_run_full_pipeline_ingest

    _deal_ids = deal_ids

    async def _run() -> None:
        try:
            await async_run_full_pipeline_ingest(
                fund_id,
                deal_ids=_deal_ids,
                batch_size=batch_size,
                run_ai_analysis=True,
                actor_id=actor_id,
            )
        except Exception:
            logger.error("Full pipeline ingest failed for fund %s", fund_id, exc_info=True)

    background_tasks.add_task(_run)
    logger.info("Ingest dispatched via BackgroundTasks fund=%s", fund_id)
    return {
        "status": "scheduled",
        "dispatch": "background_tasks",
        "fund_id": str(fund_id),
        "batch_size": batch_size,
        "deal_ids": payload["deal_ids"],
        "triggered_by": actor_id,
    }


# ── Deep Review (Memo Generation) ───────────────────────────────────

def dispatch_deep_review(
    *,
    background_tasks: BackgroundTasks,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    actor: str,
    force: bool,
) -> dict[str, Any]:
    payload = {
        "fund_id": str(fund_id),
        "deal_id": str(deal_id),
        "actor": actor,
        "force": force,
        "triggered_by": actor,
    }

    if _use_service_bus():
        from app.services.azure.servicebus_client import send_to_queue

        sb_job_id = send_to_queue("memo-generation", payload, stage="memo")
        logger.info("Deep review dispatched via Service Bus job=%s deal=%s", sb_job_id, deal_id)
        return {
            "status": "queued",
            "dispatch": "service_bus",
            "sb_job_id": sb_job_id,
            "dealId": str(deal_id),
        }

    from app.core.db.session import sync_session_factory

    async def _run() -> None:
        await _execute_deep_review_lifecycle(
            session_factory=sync_session_factory,
            fund_id=fund_id,
            deal_id=deal_id,
            actor=actor,
            force=force,
        )

    background_tasks.add_task(_run)
    logger.info("Deep review dispatched via BackgroundTasks deal=%s", deal_id)
    return {
        "status": "scheduled",
        "dispatch": "background_tasks",
        "dealId": str(deal_id),
    }


async def _execute_deep_review_lifecycle(
    *,
    session_factory: Any,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    actor: str,
    force: bool,
) -> None:
    """Single orchestration path for deep review execution.

    Lifecycle semantics:
    - Exactly one terminal state is written (READY or FAILED).
    - A ``finally`` block guarantees no stale PROCESSING state survives.
    - Success writes READY with ``intelligence_generated_at`` timestamp.
    - Failure writes FAILED with the reason preserved in logs.
    - Soft errors (result contains ``"error"`` key) are treated as failures.

    The session used for artifact persistence (inside deep review) is
    separate from the session used for the terminal status update. This
    prevents a status-update failure from rolling back persisted artifacts,
    and vice versa.
    """
    from vertical_engines.credit.deep_review import async_run_deal_deep_review_v4

    log = logging.getLogger("ai.deep_review_v4")
    log.info("V4_BG_START deal_id=%s", deal_id)

    terminal_state_written = False
    result: dict[str, Any] = {}
    failure_reason: str = ""

    # ── Phase 1: Execute deep review (artifact persistence) ──────
    db = session_factory()
    try:
        result = await async_run_deal_deep_review_v4(
            db, fund_id=fund_id, deal_id=deal_id, actor_id=actor, force=force,
        )
        if "error" not in result:
            db.commit()
        else:
            failure_reason = result.get("error", "soft_error")
            db.rollback()
    except Exception as exc:
        failure_reason = f"exception: {exc}"
        log.error("deep-review-v4 FAILED deal_id=%s: %s", deal_id, exc, exc_info=True)
        db.rollback()
    finally:
        db.close()

    # ── Phase 2: Write exactly one terminal status ───────────────
    db_status = session_factory()
    try:
        if not failure_reason:
            update_deal_intelligence_status(
                db_status,
                deal_id=deal_id,
                fund_id=fund_id,
                status="READY",
                generated_at=dt.datetime.now(dt.UTC),
            )
            db_status.commit()
            terminal_state_written = True
            log.info("V4_STATUS_READY deal_id=%s", deal_id)
        else:
            log.warning(
                "deep-review-v4 TERMINAL_FAILED deal_id=%s reason=%s",
                deal_id, failure_reason,
            )
            update_deal_intelligence_status(
                db_status, deal_id=deal_id, fund_id=fund_id, status="FAILED",
            )
            db_status.commit()
            terminal_state_written = True
    except Exception:
        db_status.rollback()
        log.error(
            "Failed to write terminal status deal_id=%s",
            deal_id, exc_info=True,
        )
    finally:
        db_status.close()

    # ── Phase 3: Safety net — guarantee no stale PROCESSING ──────
    if not terminal_state_written:
        log.warning(
            "V4_SAFETY_NET forcing FAILED status deal_id=%s", deal_id,
        )
        db_fallback = session_factory()
        try:
            update_deal_intelligence_status(
                db_fallback,
                deal_id=deal_id,
                fund_id=fund_id,
                status="FAILED",
            )
            db_fallback.commit()
        except Exception:
            db_fallback.rollback()
            log.critical(
                "V4_SAFETY_NET_EXHAUSTED deal_id=%s — manual intervention required",
                deal_id,
            )
        finally:
            db_fallback.close()
