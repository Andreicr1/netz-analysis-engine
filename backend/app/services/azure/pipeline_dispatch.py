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
        }

    from ai_engine.extraction.extraction_orchestrator import run_extraction_pipeline

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

    from app.core.db.session import get_session_local
    from vertical_engines.credit.deep_review import async_run_deal_deep_review_v4

    async def _run() -> None:
        log = logging.getLogger("ai.deep_review_v4")
        log.info("V4_BG_START deal_id=%s", deal_id)
        db = get_session_local()()
        try:
            result = await async_run_deal_deep_review_v4(
                db, fund_id=fund_id, deal_id=deal_id, actor_id=actor, force=force,
            )
            if "error" not in result:
                db.commit()
            else:
                db.rollback()
        except Exception as exc:
            log.error("deep-review-v4 FAILED deal_id=%s: %s", deal_id, exc, exc_info=True)
            db.rollback()
            try:
                update_deal_intelligence_status(
                    db, deal_id=deal_id, fund_id=fund_id, status="FAILED",
                )
                db.commit()
            except Exception:
                db.rollback()
            return
        finally:
            db.close()

        if "error" not in result:
            db2 = get_session_local()()
            try:
                update_deal_intelligence_status(
                    db2,
                    deal_id=deal_id,
                    fund_id=fund_id,
                    status="READY",
                    generated_at=dt.datetime.now(dt.UTC),
                )
                db2.commit()
                log.info("V4_STATUS_READY deal_id=%s", deal_id)
            except Exception:
                db2.rollback()
                log.error("Failed to update status to READY deal_id=%s", deal_id, exc_info=True)
            finally:
                db2.close()
        else:
            log.warning("deep-review-v4 SOFT_ERROR deal_id=%s error=%s", deal_id, result.get("error"))
            db2 = get_session_local()()
            try:
                update_deal_intelligence_status(
                    db2, deal_id=deal_id, fund_id=fund_id, status="FAILED",
                )
                db2.commit()
            except Exception:
                db2.rollback()
                log.error("Failed to update status to FAILED deal_id=%s", deal_id, exc_info=True)
            finally:
                db2.close()

    background_tasks.add_task(_run)
    logger.info("Deep review dispatched via BackgroundTasks deal=%s", deal_id)
    return {
        "status": "scheduled",
        "dispatch": "background_tasks",
        "dealId": str(deal_id),
    }
