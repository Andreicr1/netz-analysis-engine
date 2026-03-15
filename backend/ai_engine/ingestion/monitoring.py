from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.classification.document_classifier import classify_documents
from ai_engine.extraction.obligation_extractor import extract_obligation_register
from ai_engine.knowledge.knowledge_builder import build_manager_profiles
from app.domains.credit.modules.ai.models import GovernanceAlert, ObligationRegister

logger = logging.getLogger(__name__)


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _parse_due_date(rule: str | None) -> dt.date | None:
    if not rule:
        return None
    text = rule.strip()
    for token in text.replace("Due on", "").split():
        try:
            if len(token) == 10 and token[4] == "-" and token[7] == "-":
                return dt.date.fromisoformat(token)
        except Exception:
            continue
    return None


def _upsert_alert_batched(
    existing_by_alert_id: dict[str, GovernanceAlert],
    pending_adds: list[GovernanceAlert],
    *,
    fund_id: uuid.UUID,
    alert_id: str,
    domain: str,
    severity: str,
    entity_ref: str,
    title: str,
    actionable_next_step: str,
    as_of: dt.datetime,
    actor_id: str,
) -> GovernanceAlert:
    payload = {
        "fund_id": fund_id,
        "access_level": "internal",
        "alert_id": alert_id,
        "domain": domain,
        "severity": severity,
        "entity_ref": entity_ref,
        "title": title,
        "actionable_next_step": actionable_next_step,
        "as_of": as_of,
        "data_latency": 0,
        "data_quality": "OK",
        "created_by": actor_id,
        "updated_by": actor_id,
    }

    existing = existing_by_alert_id.get(alert_id)
    if existing is None:
        row = GovernanceAlert(**payload)
        pending_adds.append(row)
        return row

    for key, value in payload.items():
        if key == "created_by":
            continue
        setattr(existing, key, value)
    return existing


def run_daily_cycle(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> dict[str, int | str]:
    now = _now_utc()

    # Sequential by design: all three share the same SQLAlchemy Session which
    # is NOT thread-safe.  ThreadPoolExecutor would require separate sessions
    # and careful transaction coordination.  The combined wall-time is
    # acceptable for a daily batch cycle.
    classifications = classify_documents(db, fund_id=fund_id, actor_id=actor_id)
    profiles = build_manager_profiles(db, fund_id=fund_id, actor_id=actor_id)
    obligations = extract_obligation_register(db, fund_id=fund_id, actor_id=actor_id)

    today = now.date()
    missing_evidence_rows = list(
        db.execute(
            select(ObligationRegister).where(
                ObligationRegister.fund_id == fund_id,
                ObligationRegister.status == "MissingEvidence",
            ),
        ).scalars().all(),
    )

    all_existing_alerts = list(
        db.execute(
            select(GovernanceAlert).where(GovernanceAlert.fund_id == fund_id),
        ).scalars().all(),
    )
    existing_by_alert_id: dict[str, GovernanceAlert] = {
        a.alert_id: a for a in all_existing_alerts
    }

    alerts: list[GovernanceAlert] = []
    pending_adds: list[GovernanceAlert] = []

    alerts.append(
        _upsert_alert_batched(
            existing_by_alert_id,
            pending_adds,
            fund_id=fund_id,
            alert_id=f"ALERT-NEW-DOCS-{today.isoformat()}",
            domain="Reporting",
            severity="Info",
            entity_ref="DataRoom",
            title=f"{len(classifications)} documents classified in daily cycle",
            actionable_next_step="Review classification output and validate dataQuality before dissemination.",
            as_of=now,
            actor_id=actor_id,
        ),
    )

    if missing_evidence_rows:
        alerts.append(
            _upsert_alert_batched(
                existing_by_alert_id,
                pending_adds,
                fund_id=fund_id,
                alert_id=f"ALERT-MISSING-EVIDENCE-{today.isoformat()}",
                domain="Compliance",
                severity="Warning",
                entity_ref="ObligationRegister",
                title=f"{len(missing_evidence_rows)} obligations are missing evidence",
                actionable_next_step="Collect and link formal evidence for obligations marked MissingEvidence.",
                as_of=now,
                actor_id=actor_id,
            ),
        )

    overdue = 0
    approaching = 0
    for obligation in missing_evidence_rows:
        due_date = _parse_due_date(obligation.due_rule)
        if due_date is None:
            continue
        if due_date < today:
            overdue += 1
        elif (due_date - today).days <= 30:
            approaching += 1

    if overdue > 0:
        alerts.append(
            _upsert_alert_batched(
                existing_by_alert_id,
                pending_adds,
                fund_id=fund_id,
                alert_id=f"ALERT-OVERDUE-{today.isoformat()}",
                domain="Compliance",
                severity="Critical",
                entity_ref="ObligationRegister",
                title=f"{overdue} deliverables are overdue",
                actionable_next_step="Escalate overdue obligations to Compliance Officer and register remediation evidence.",
                as_of=now,
                actor_id=actor_id,
            ),
        )

    if approaching > 0:
        alerts.append(
            _upsert_alert_batched(
                existing_by_alert_id,
                pending_adds,
                fund_id=fund_id,
                alert_id=f"ALERT-APPROACHING-DUE-{today.isoformat()}",
                domain="Compliance",
                severity="Warning",
                entity_ref="ObligationRegister",
                title=f"{approaching} obligations are approaching due date (<=30 days)",
                actionable_next_step="Prepare deliverables and verify submission evidence before due dates.",
                as_of=now,
                actor_id=actor_id,
            ),
        )

    if profiles:
        alerts.append(
            _upsert_alert_batched(
                existing_by_alert_id,
                pending_adds,
                fund_id=fund_id,
                alert_id=f"ALERT-MANAGER-KNOWLEDGE-{today.isoformat()}",
                domain="Risk",
                severity="Info",
                entity_ref="ManagerProfile",
                title=f"{len(profiles)} manager profiles refreshed",
                actionable_next_step="Validate key declared risks and reporting cadence against latest source documents.",
                as_of=now,
                actor_id=actor_id,
            ),
        )

    db.add_all(pending_adds)
    db.flush()
    db.commit()

    return {
        "asOf": now.isoformat(),
        "classifiedDocuments": len(classifications),
        "managerProfiles": len(profiles),
        "obligations": len(obligations),
        "alerts": len(alerts),
    }
