"""
Worker Function App — Azure Service Bus consumers.

Processes pipeline jobs enqueued by the backend API:
  • extraction-worker  → document extraction pipeline
  • ingest-worker      → domain ingest pipeline
  • memo-generation    → IC Memo deep review

Shares the App Service Plan S1 with the backend (netz-prod-plan).
maxConcurrentCalls = 1 to avoid resource contention.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid

import azure.functions as func

# ── Make backend packages importable ──────────────────────────────────
# Local repo layout:
#   worker_app/function_app.py
#   backend/
# Deployed package layout:
#   function_app.py
#   backend/
_current_dir = os.path.dirname(__file__)
_backend_candidates = (
    os.path.abspath(os.path.join(_current_dir, "backend")),
    os.path.abspath(os.path.join(_current_dir, "..", "backend")),
)
for _backend_root in _backend_candidates:
    if os.path.isdir(_backend_root) and _backend_root not in sys.path:
        sys.path.insert(0, _backend_root)
        break

logger = logging.getLogger(__name__)

app = func.FunctionApp()


# Keys injected by dispatch but not accepted by target functions.
_DISPATCH_META_KEYS = frozenset({"triggered_by"})


def _normalize_actor_payload(payload: dict, *, preferred_key: str = "actor_id") -> dict:
    """Backfill actor aliases and strip dispatch-only meta keys."""
    normalized = dict(payload)
    actor_value = normalized.get(preferred_key)
    if actor_value is None:
        actor_value = normalized.get("triggered_by")
    if actor_value is not None:
        normalized[preferred_key] = actor_value
    for key in _DISPATCH_META_KEYS:
        normalized.pop(key, None)
    return normalized


def _strip_dispatch_meta(payload: dict) -> dict:
    """Remove dispatch-only meta keys that target functions don't accept."""
    return {k: v for k, v in payload.items() if k not in _DISPATCH_META_KEYS}


# ── Document Pipeline: Extraction ─────────────────────────────────────
@app.service_bus_topic_trigger(
    arg_name="msg",
    topic_name="document-pipeline",
    subscription_name="extraction-worker",
    connection="SERVICE_BUS_CONNECTION",
)
def extraction_worker(msg: func.ServiceBusMessage) -> None:
    """Process extraction pipeline jobs (Mistral OCR → Cohere → embed → index)."""
    body = msg.get_body().decode("utf-8")
    envelope = json.loads(body)
    job_id = envelope.get("job_id", "unknown")
    logger.info("extraction_worker: received job %s (attempt %s)", job_id, envelope.get("attempt", 1))

    try:
        from ai_engine.extraction.extraction_orchestrator import run_extraction_pipeline

        payload = _strip_dispatch_meta(envelope.get("payload", {}))
        run_extraction_pipeline(**payload)
        logger.info("extraction_worker: completed job %s", job_id)
    except Exception:
        logger.exception("extraction_worker: failed job %s", job_id)
        raise  # Let Service Bus handle retry / DLQ


# ── Document Pipeline: Ingest ─────────────────────────────────────────
@app.service_bus_topic_trigger(
    arg_name="msg",
    topic_name="document-pipeline",
    subscription_name="ingest-worker",
    connection="SERVICE_BUS_CONNECTION",
)
async def ingest_worker(msg: func.ServiceBusMessage) -> None:
    """Process domain ingest pipeline jobs (scan → discover → bridge → AI analysis)."""
    body = msg.get_body().decode("utf-8")
    envelope = json.loads(body)
    job_id = envelope.get("job_id", "unknown")
    logger.info("ingest_worker: received job %s (attempt %s)", job_id, envelope.get("attempt", 1))

    try:
        from ai_engine.ingestion.pipeline_ingest_runner import async_run_full_pipeline_ingest

        payload = _normalize_actor_payload(envelope.get("payload", {}), preferred_key="actor_id")
        await async_run_full_pipeline_ingest(**payload)
        logger.info("ingest_worker: completed job %s", job_id)
    except Exception:
        logger.exception("ingest_worker: failed job %s", job_id)
        raise


# ── Memo Generation Queue ─────────────────────────────────────────────
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="memo-generation",
    connection="SERVICE_BUS_CONNECTION",
)
async def memo_worker(msg: func.ServiceBusMessage) -> None:
    """Process IC Memo generation jobs (async for parallel deep review)."""
    body = msg.get_body().decode("utf-8")
    envelope = json.loads(body)
    job_id = envelope.get("job_id", "unknown")
    logger.info("memo_worker: received job %s (attempt %s)", job_id, envelope.get("attempt", 1))

    try:
        import datetime as dt

        from app.core.db.session import get_session_local
        from app.services.azure.pipeline_dispatch import update_deal_intelligence_status
        from vertical_engines.credit.deep_review import async_run_deal_deep_review_v4

        payload = envelope.get("payload", {})
        fund_id = payload.get("fund_id")
        deal_id = payload.get("deal_id")
        actor_id = payload.get("actor") or payload.get("triggered_by") or "ai-engine"
        force = payload.get("force", False)

        if not fund_id or not deal_id:
            raise ValueError("memo_worker requires fund_id and deal_id in payload")

        fund_uuid = uuid.UUID(str(fund_id))
        deal_uuid = uuid.UUID(str(deal_id))

        db = get_session_local()()
        try:
            result = await async_run_deal_deep_review_v4(
                db,
                fund_id=fund_uuid,
                deal_id=deal_uuid,
                actor_id=actor_id,
                force=force,
            )
            if "error" not in result:
                update_deal_intelligence_status(
                    db,
                    deal_id=deal_uuid,
                    fund_id=fund_uuid,
                    status="READY",
                    generated_at=dt.datetime.now(dt.timezone.utc),
                )
                db.commit()
            else:
                db.rollback()
                update_deal_intelligence_status(
                    db,
                    deal_id=deal_uuid,
                    fund_id=fund_uuid,
                    status="FAILED",
                )
                db.commit()
                raise RuntimeError(f"Deep review soft error: {result.get('error')}")
        except Exception:
            db.rollback()
            try:
                update_deal_intelligence_status(
                    db,
                    deal_id=deal_uuid,
                    fund_id=fund_uuid,
                    status="FAILED",
                )
                db.commit()
            except Exception:
                db.rollback()
            raise
        finally:
            db.close()
        logger.info("memo_worker: completed job %s", job_id)
    except Exception:
        logger.exception("memo_worker: failed job %s", job_id)
        raise


# ── DLQ Monitor ───────────────────────────────────────────────────────
@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer")
def dlq_monitor(timer: func.TimerRequest) -> None:
    """Check dead-letter queue counts every 5 minutes and alert if > 0.

    Emits structured custom events to Application Insights for alerting
    via Azure Monitor Action Groups.
    """
    try:
        from azure.servicebus.management import ServiceBusAdministrationClient

        # Prefer connection string to avoid pulling in azure.identity
        # (which depends on cryptography / GLIBC mismatches in Functions).
        conn_str = os.environ.get("SERVICE_BUS_CONNECTION")
        ns = os.environ.get("SERVICE_BUS_CONNECTION__fullyQualifiedNamespace")
        if conn_str:
            admin = ServiceBusAdministrationClient.from_connection_string(conn_str)
        elif ns:
            from azure.identity import DefaultAzureCredential
            admin = ServiceBusAdministrationClient(ns, DefaultAzureCredential())
        else:
            return
        total_dlq = 0

        # Check topics
        for topic_name in ("document-pipeline", "compliance-pipeline"):
            try:
                for sub in admin.list_subscriptions(topic_name):
                    runtime = admin.get_subscription_runtime_properties(topic_name, sub.name)
                    dlq_count = runtime.dead_letter_message_count or 0
                    if dlq_count > 0:
                        total_dlq += dlq_count
                        logger.warning(
                            "DLQ_ALERT topic=%s subscription=%s dead_letter_count=%d",
                            topic_name, sub.name, dlq_count,
                            extra={
                                "custom_dimensions": {
                                    "event": "dlq_alert",
                                    "resource_type": "topic",
                                    "topic": topic_name,
                                    "subscription": sub.name,
                                    "dlq_count": dlq_count,
                                }
                            },
                        )
            except Exception:
                logger.exception("DLQ monitor error for topic %s", topic_name)

        # Check queues
        for queue_name in ("memo-generation",):
            try:
                runtime = admin.get_queue_runtime_properties(queue_name)
                dlq_count = runtime.dead_letter_message_count or 0
                if dlq_count > 0:
                    total_dlq += dlq_count
                    logger.warning(
                        "DLQ_ALERT queue=%s dead_letter_count=%d",
                        queue_name, dlq_count,
                        extra={
                            "custom_dimensions": {
                                "event": "dlq_alert",
                                "resource_type": "queue",
                                "queue": queue_name,
                                "dlq_count": dlq_count,
                            }
                        },
                    )
            except Exception:
                logger.exception("DLQ monitor error for queue %s", queue_name)

        if total_dlq == 0:
            logger.info("DLQ monitor: all queues healthy (0 dead letters)")

    except Exception:
        logger.exception("DLQ monitor failed")


