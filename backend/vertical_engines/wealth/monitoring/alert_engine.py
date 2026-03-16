"""Alert Engine — wealth-specific monitoring alerts.

Consumes existing worker events and adds wealth-specific alert conditions:
- DD Report expiry (>12 months since last DD)
- Fund watchlist triggers (deactivated funds in portfolios)
- Rebalance overdue (no rebalance within configured window)

Publishes alerts via Redis pub/sub for SSE consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger()

_DD_EXPIRY_MONTHS = 12
_REBALANCE_OVERDUE_DAYS = 90


@dataclass(frozen=True)
class Alert:
    """A single monitoring alert."""

    alert_type: str  # dd_expiry | fund_watchlist | rebalance_overdue
    severity: str  # info | warning | critical
    title: str
    detail: str
    entity_id: str | None = None
    entity_type: str | None = None


@dataclass(frozen=True)
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
    alerts.extend(_check_fund_watchlist(db, organization_id))
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
    """Check for DD Reports older than 12 months."""
    from app.domains.wealth.models.dd_report import DDReport
    from app.domains.wealth.models.fund import Fund

    cutoff = datetime.now(timezone.utc) - timedelta(days=_DD_EXPIRY_MONTHS * 30)
    alerts: list[Alert] = []

    # Get all active funds
    funds = (
        db.query(Fund)
        .filter(
            Fund.organization_id == organization_id,
            Fund.is_active.is_(True),
        )
        .all()
    )

    for fund in funds:
        latest_report = (
            db.query(DDReport)
            .filter(
                DDReport.fund_id == fund.fund_id,
                DDReport.organization_id == organization_id,
                DDReport.is_current.is_(True),
            )
            .first()
        )

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


def _check_fund_watchlist(db: Session, organization_id: str) -> list[Alert]:
    """Check for deactivated funds that are still in model portfolios."""
    from app.domains.wealth.models.fund import Fund
    from app.domains.wealth.models.model_portfolio import ModelPortfolio

    alerts: list[Alert] = []

    # Get all live portfolios
    portfolios = (
        db.query(ModelPortfolio)
        .filter(
            ModelPortfolio.organization_id == organization_id,
            ModelPortfolio.status == "live",
        )
        .all()
    )

    # Get deactivated fund IDs
    deactivated = (
        db.query(Fund.fund_id)
        .filter(
            Fund.organization_id == organization_id,
            Fund.is_active.is_(False),
        )
        .all()
    )
    deactivated_ids = {str(row[0]) for row in deactivated}

    for portfolio in portfolios:
        fund_selection = portfolio.fund_selection_schema or {}
        portfolio_funds = fund_selection.get("funds", [])

        for f in portfolio_funds:
            fid = f.get("fund_id", "")
            if fid in deactivated_ids:
                alerts.append(Alert(
                    alert_type="fund_watchlist",
                    severity="critical",
                    title=f"Deactivated fund in {portfolio.display_name}",
                    detail=(
                        f"Fund {f.get('fund_name', fid)} is deactivated but still "
                        f"present in model portfolio '{portfolio.display_name}'."
                    ),
                    entity_id=str(portfolio.id),
                    entity_type="model_portfolio",
                ))

    return alerts


def _check_rebalance_overdue(db: Session, organization_id: str) -> list[Alert]:
    """Check for portfolios that haven't been rebalanced within threshold."""
    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.models.rebalance import RebalanceEvent

    alerts: list[Alert] = []
    cutoff = date.today() - timedelta(days=_REBALANCE_OVERDUE_DAYS)

    portfolios = (
        db.query(ModelPortfolio)
        .filter(
            ModelPortfolio.organization_id == organization_id,
            ModelPortfolio.status == "live",
        )
        .all()
    )

    for portfolio in portfolios:
        last_rebalance = (
            db.query(RebalanceEvent)
            .filter(
                RebalanceEvent.organization_id == organization_id,
                RebalanceEvent.profile == portfolio.profile,
            )
            .order_by(RebalanceEvent.trigger_date.desc())
            .first()
        )

        if last_rebalance is None or last_rebalance.trigger_date < cutoff:
            days_since = (
                (date.today() - last_rebalance.trigger_date).days
                if last_rebalance else "never"
            )
            alerts.append(Alert(
                alert_type="rebalance_overdue",
                severity="info",
                title=f"Rebalance overdue for {portfolio.display_name}",
                detail=(
                    f"Portfolio '{portfolio.display_name}' (profile: {portfolio.profile}) "
                    f"last rebalanced {days_since} days ago "
                    f"(threshold: {_REBALANCE_OVERDUE_DAYS} days)."
                ),
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
