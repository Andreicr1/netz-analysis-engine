"""Pipeline ingest orchestrator.

Implements run_pipeline_ingest() — the top-level entrypoint that
orchestrates discovery, document aggregation, profile building,
IC briefs, and monitoring.
"""
from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy.orm import Session

from vertical_engines.credit.pipeline.discovery import (
    aggregate_deal_documents,
    discover_pipeline_deals,
)
from vertical_engines.credit.pipeline.monitoring import (
    build_deal_intelligence_profiles,
    build_ic_briefs,
    run_pipeline_monitoring,
)

logger = structlog.get_logger()


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def run_pipeline_ingest(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> dict[str, int | str]:
    """Orchestrate full pipeline ingest: discover, aggregate, profile, monitor."""
    deals = discover_pipeline_deals(db, fund_id=fund_id, actor_id=actor_id)
    deal_docs = aggregate_deal_documents(db, fund_id=fund_id, actor_id=actor_id)
    profiles = build_deal_intelligence_profiles(db, fund_id=fund_id, actor_id=actor_id)
    briefs = build_ic_briefs(db, fund_id=fund_id, actor_id=actor_id)
    alerts = run_pipeline_monitoring(db, fund_id=fund_id, actor_id=actor_id)

    return {
        "asOf": _now_utc().isoformat(),
        "deals": len(deals),
        "dealDocuments": len(deal_docs),
        "profiles": len(profiles),
        "briefs": len(briefs),
        "alerts": len(alerts),
    }
