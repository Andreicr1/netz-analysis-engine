"""Portfolio ingest orchestrator — runs full portfolio monitoring pipeline.

Error contract: never-raises (orchestration engine called during portfolio ingest).
Catches all exceptions, logs with exc_info=True, and re-raises to allow
caller-controlled transaction rollback.
"""
from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy.orm import Session

from vertical_engines.credit.portfolio.briefs import build_board_monitoring_briefs
from vertical_engines.credit.portfolio.covenants import build_covenant_surveillance
from vertical_engines.credit.portfolio.discovery import discover_active_investments
from vertical_engines.credit.portfolio.drift import detect_performance_drift
from vertical_engines.credit.portfolio.metrics import extract_portfolio_metrics
from vertical_engines.credit.portfolio.risk import (
    _evaluate_liquidity_cash_impact,
    reclassify_investment_risk,
)

logger = structlog.get_logger()


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def run_portfolio_ingest(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    as_of: dt.datetime | None = None,
) -> dict[str, int | str]:
    monitoring_as_of = as_of or _now_utc()
    logger.info("run_portfolio_ingest.start", fund_id=str(fund_id), as_of=monitoring_as_of.isoformat())

    try:
        investments = discover_active_investments(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        metrics = extract_portfolio_metrics(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        drifts = detect_performance_drift(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        covenants = build_covenant_surveillance(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        cash_flags = _evaluate_liquidity_cash_impact(db, fund_id=fund_id)
        risk_registry = reclassify_investment_risk(db, fund_id=fund_id, as_of=monitoring_as_of, actor_id=actor_id)
        briefs = build_board_monitoring_briefs(
            db,
            fund_id=fund_id,
            as_of=monitoring_as_of,
            actor_id=actor_id,
            investments=investments,
            drifts=drifts,
            covenants=covenants,
            cash_flags=cash_flags,
            risks=risk_registry,
        )

        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "run_portfolio_ingest.failed",
            fund_id=str(fund_id),
        )
        raise

    logger.info("run_portfolio_ingest.done", fund_id=str(fund_id))
    return {
        "asOf": monitoring_as_of.isoformat(),
        "investments": len(investments),
        "metrics": len(metrics),
        "drifts": len(drifts),
        "covenants": len(covenants),
        "cashFlags": len(cash_flags),
        "riskRegistry": len(risk_registry),
        "briefs": len(briefs),
    }
