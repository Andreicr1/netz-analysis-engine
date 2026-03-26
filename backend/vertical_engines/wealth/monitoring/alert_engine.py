"""Alert Engine — wealth-specific monitoring alerts.

Consumes existing worker events and adds wealth-specific alert conditions:
- DD Report expiry (>12 months since last DD)
- Rebalance overdue (no rebalance within configured window)

Publishes alerts via Redis pub/sub for SSE consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

logger = structlog.get_logger()

_DD_EXPIRY_MONTHS = 12
_REBALANCE_OVERDUE_DAYS = 90


@dataclass(frozen=True, slots=True)
class Alert:
    """A single monitoring alert."""

    alert_type: str  # dd_expiry | rebalance_overdue
    severity: str  # info | warning | critical
    title: str
    detail: str
    entity_id: str | None = None
    entity_type: str | None = None


@dataclass(frozen=True, slots=True)
class AlertBatch:
    """Batch of alerts from a single scan."""

    alerts: list[Alert]
    scanned_at: datetime
    organization_id: str


def scan_alerts(
    db: Session,
    *,
    organization_id: str,
) -> AlertBatch:
    """Run all alert checks and return a batch of alerts.

    Pure sync function — designed to run in asyncio.to_thread().
    """
    alerts: list[Alert] = []

    alerts.extend(_check_dd_expiry(db, organization_id))
    alerts.extend(_check_rebalance_overdue(db, organization_id))

    logger.info(
        "alert_scan_completed",
        organization_id=organization_id,
        alert_count=len(alerts),
    )

    return AlertBatch(
        alerts=alerts,
        scanned_at=datetime.now(timezone.utc),
        organization_id=organization_id,
    )


def _check_dd_expiry(db: Session, organization_id: str) -> list[Alert]:
    """Check for DD Reports older than 12 months.

    Uses a single LEFT JOIN query to fetch all active funds with their
    latest current DDReport, avoiding N+1 per-fund queries.
    """
    from app.domains.wealth.models.dd_report import DDReport
    from app.domains.wealth.models.fund import Fund

    cutoff = datetime.now(timezone.utc) - timedelta(days=_DD_EXPIRY_MONTHS * 30)
    alerts: list[Alert] = []

    # Single LEFT JOIN: all active funds with their latest current DDReport
    rows = (
        db.query(Fund, DDReport)
        .outerjoin(
            DDReport,
            (DDReport.instrument_id == Fund.fund_id)
            & (DDReport.organization_id == organization_id)
            & (DDReport.is_current.is_(True)),
        )
        .filter(
            Fund.organization_id == organization_id,
            Fund.is_active.is_(True),
        )
        .all()
    )

    for fund, latest_report in rows:
        if latest_report is None:
            alerts.append(Alert(
                alert_type="dd_expiry",
                severity="warning",
                title=f"No DD Report for {fund.name}",
                detail=f"Fund {fund.name} ({fund.isin}) has no DD Report on file.",
                entity_id=str(fund.fund_id),
                entity_type="fund",
            ))
        elif latest_report.created_at and latest_report.created_at < cutoff:
            age_days = (datetime.now(timezone.utc) - latest_report.created_at).days
            alerts.append(Alert(
                alert_type="dd_expiry",
                severity="warning",
                title=f"DD Report expired for {fund.name}",
                detail=(
                    f"Last DD Report for {fund.name} is {age_days} days old "
                    f"(threshold: {_DD_EXPIRY_MONTHS * 30} days)."
                ),
                entity_id=str(fund.fund_id),
                entity_type="fund",
            ))

    return alerts


def _check_rebalance_overdue(db: Session, organization_id: str) -> list[Alert]:
    """Check for portfolios that haven't been rebalanced within threshold.

    Uses a single query to fetch the latest RebalanceEvent per profile,
    then matches against live portfolios — avoiding N+1 per-portfolio queries.
    """
    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.models.rebalance import RebalanceEvent

    alerts: list[Alert] = []
    cutoff = date.today() - timedelta(days=_REBALANCE_OVERDUE_DAYS)

    # 1. Get all live portfolios in a single query
    portfolios = (
        db.query(ModelPortfolio)
        .filter(
            ModelPortfolio.organization_id == organization_id,
            ModelPortfolio.status == "live",
        )
        .all()
    )

    if not portfolios:
        return alerts

    # 2. Get latest rebalance date per profile in a single grouped query
    profile_values = {p.profile for p in portfolios}
    latest_rebalances = (
        db.query(
            RebalanceEvent.profile,
            func.max(RebalanceEvent.event_date).label("latest_date"),
        )
        .filter(
            RebalanceEvent.organization_id == organization_id,
            RebalanceEvent.profile.in_(profile_values),
        )
        .group_by(RebalanceEvent.profile)
        .all()
    )
    rebalance_by_profile: dict[str, date] = {
        row.profile: row.latest_date for row in latest_rebalances
    }

    # 3. Match portfolios against the pre-fetched map
    for portfolio in portfolios:
        last_date = rebalance_by_profile.get(portfolio.profile)

        if last_date is None or last_date < cutoff:
            if last_date is None:
                detail_str = (
                    f"Portfolio '{portfolio.display_name}' has never been rebalanced "
                    f"(threshold: {_REBALANCE_OVERDUE_DAYS} days)."
                )
            else:
                days_since = (date.today() - last_date).days
                detail_str = (
                    f"Portfolio '{portfolio.display_name}' last rebalanced "
                    f"{days_since} days ago (threshold: {_REBALANCE_OVERDUE_DAYS} days)."
                )
            alerts.append(Alert(
                alert_type="rebalance_overdue",
                severity="info",
                title=f"Rebalance overdue for {portfolio.display_name}",
                detail=detail_str,
                entity_id=str(portfolio.id),
                entity_type="model_portfolio",
            ))

    return alerts


def alerts_to_json(batch: AlertBatch) -> list[dict[str, Any]]:
    """Serialize AlertBatch to JSON-compatible list for Redis pub/sub."""
    return [
        {
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "detail": a.detail,
            "entity_id": a.entity_id,
            "entity_type": a.entity_type,
            "scanned_at": batch.scanned_at.isoformat(),
            "organization_id": batch.organization_id,
        }
        for a in batch.alerts
    ]
