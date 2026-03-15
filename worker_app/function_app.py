"""
Worker Function App — Azure Service Bus consumers.

Processes pipeline jobs enqueued by the backend API:
  • extraction-worker  → document extraction pipeline
  • ingest-worker      → domain ingest pipeline
  • compliance-worker  → compliance KB ingest
  • memo-generation    → IC Memo generation

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


# ── Compliance Pipeline ───────────────────────────────────────────────
@app.service_bus_topic_trigger(
    arg_name="msg",
    topic_name="compliance-pipeline",
    subscription_name="compliance-worker",
    connection="SERVICE_BUS_CONNECTION",
)
def compliance_worker(msg: func.ServiceBusMessage) -> None:
    """Process compliance KB ingest jobs (Fund Constitution, CIMA Reg, Service Providers)."""
    body = msg.get_body().decode("utf-8")
    envelope = json.loads(body)
    job_id = envelope.get("job_id", "unknown")
    logger.info("compliance_worker: received job %s (attempt %s)", job_id, envelope.get("attempt", 1))

    try:
        from app.domain.compliance.ingest.compliance_ingest_runner import ComplianceIngestRunner

        payload = _strip_dispatch_meta(envelope.get("payload", {}))
        fund_id = payload.get("fund_id")
        if not fund_id:
            raise ValueError("compliance_worker requires fund_id in payload")

        runner = ComplianceIngestRunner()
        result = runner.run(fund_id=fund_id)
        logger.info("compliance_worker: completed job %s result=%s", job_id, result)
    except Exception:
        logger.exception("compliance_worker: failed job %s", job_id)
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
        payload = envelope.get("payload", {})
        task = payload.get("task")

        if task == "ai_review_analysis":
            from app.core.db.session import get_session_local
            from app.domain.documents.models.review import DocumentReview
            from app.domain.documents.services.ai_review_analyzer import analyze_review_checklist
            from sqlalchemy import select

            review_id = payload.get("review_id")
            fund_id = payload.get("fund_id")
            if not review_id or not fund_id:
                raise ValueError("ai_review_analysis requires review_id and fund_id")
            review_uuid = uuid.UUID(str(review_id))
            fund_uuid = uuid.UUID(str(fund_id))

            SessionLocal = get_session_local()
            db = SessionLocal()
            try:
                review = db.execute(
                    select(DocumentReview).where(DocumentReview.id == review_uuid)
                ).scalar_one()
                stats = analyze_review_checklist(db, review=review, fund_id=fund_uuid)
                logger.info(
                    "memo_worker: completed ai_review_analysis job %s review=%s stats=%s",
                    job_id,
                    review_uuid,
                    stats,
                )
                db.commit()
            finally:
                db.close()
        else:
            # Async deep-review path: uses the parallel DAG orchestrator.
            import datetime as dt

            from vertical_engines.credit.deep_review import async_run_deal_deep_review_v4
            from app.core.db.session import get_session_local
            from app.services.azure.pipeline_dispatch import update_deal_intelligence_status

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


# ── Obligation Overdue Monitor ────────────────────────────────────────
@app.timer_trigger(schedule="0 0 6 * * *", arg_name="timer")
def obligation_monitor(timer: func.TimerRequest) -> None:
    """Daily check (06:00 UTC) for overdue portfolio obligations.

    Flags OPEN obligations past due date as OVERDUE, creates Alerts and
    Actions requiring evidence. Uses the backend DB session directly.
    """
    try:
        from app.core.db.session import get_session_local
        from app.domain.portfolio.services.obligation_monitor import check_overdue_obligations

        SessionLocal = get_session_local()
        db = SessionLocal()
        try:
            generated = check_overdue_obligations(db)
            logger.info(
                "obligation_monitor: completed — %d obligations flagged as overdue",
                generated,
                extra={
                    "custom_dimensions": {
                        "event": "obligation_overdue_check",
                        "overdue_count": generated,
                    }
                },
            )
        finally:
            db.close()

    except Exception:
        logger.exception("obligation_monitor failed")


# ── Report Schedule Runner ───────────────────────────────────────────
@app.timer_trigger(schedule="0 0 7 * * *", arg_name="timer")
def report_schedule_runner(timer: func.TimerRequest) -> None:
    """Daily check (07:00 UTC) for report schedules due today.

    Finds active schedules where next_run_date <= today, creates a
    ReportRun record, and advances the schedule to the next period.
    """
    try:
        from datetime import date, datetime, timezone

        from app.core.db.session import get_session_local
        from sqlalchemy import select

        SessionLocal = get_session_local()
        db = SessionLocal()
        try:
            from app.domain.reporting.models.schedules import ReportRun, ReportSchedule

            today = date.today()
            due_schedules = list(
                db.execute(
                    select(ReportSchedule).where(
                        ReportSchedule.is_active.is_(True),
                        ReportSchedule.next_run_date.isnot(None),
                        ReportSchedule.next_run_date <= today,
                    )
                ).scalars().all()
            )

            from dateutil.relativedelta import relativedelta
            _FREQ_DELTA = {
                "MONTHLY": relativedelta(months=1),
                "QUARTERLY": relativedelta(months=3),
                "SEMI_ANNUAL": relativedelta(months=6),
                "ANNUAL": relativedelta(years=1),
            }

            runs_created = 0
            for schedule in due_schedules:
                now = datetime.now(timezone.utc)
                run = ReportRun(
                    fund_id=schedule.fund_id,
                    schedule_id=schedule.id,
                    report_type=schedule.report_type,
                    status="RUNNING",
                    started_at=now,
                )
                db.add(run)

                schedule.last_run_at = now
                schedule.last_run_status = "SUCCESS"
                schedule.run_count = (schedule.run_count or 0) + 1

                delta = _FREQ_DELTA.get(schedule.frequency)
                if delta and schedule.next_run_date:
                    schedule.next_run_date = schedule.next_run_date + delta  # pyright: ignore[reportOperatorIssue]

                run.status = "SUCCESS"
                run.completed_at = datetime.now(timezone.utc)
                runs_created += 1

            db.commit()
            logger.info(
                "report_schedule_runner: completed — %d schedules processed",
                runs_created,
                extra={
                    "custom_dimensions": {
                        "event": "report_schedule_run",
                        "schedules_processed": runs_created,
                    }
                },
            )
        finally:
            db.close()

    except Exception:
        logger.exception("report_schedule_runner failed")
