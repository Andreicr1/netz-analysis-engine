"""Drift Monitor — bridge to quant_engine/drift_service with universe awareness.

Adds universe-aware drift detection: when a fund is deactivated, flags
all affected portfolios containing that fund.

Bridge pattern: does NOT duplicate drift calculation logic from quant_engine.
Instead, consumes existing drift metrics and adds wealth-specific context.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger()

# DTW drift threshold (from quant_engine convention)
_DRIFT_THRESHOLD = 0.15


@dataclass(frozen=True, slots=True)
class DriftAlert:
    """A single drift alert for a fund or portfolio."""

    instrument_id: str
    fund_name: str
    drift_score: float | None
    drift_type: str  # style_drift | universe_removal | tracking_error
    affected_portfolios: list[str]
    detail: str


@dataclass(frozen=True, slots=True)
class DriftScanResult:
    """Result of a universe-aware drift scan."""

    alerts: list[DriftAlert]
    scanned_at: datetime
    organization_id: str


def scan_drift(
    db: Session,
    *,
    organization_id: str,
    drift_threshold: float = _DRIFT_THRESHOLD,
) -> DriftScanResult:
    """Scan for drift alerts across the fund universe.

    Combines quant drift metrics with universe status to produce
    actionable alerts.

    Pure sync function — designed to run in asyncio.to_thread().
    """
    # Build inverted index once: fund_id -> list[portfolio_display_name]
    portfolio_map = _build_portfolio_fund_map(db, organization_id)

    alerts: list[DriftAlert] = []

    alerts.extend(
        _check_style_drift(db, organization_id, drift_threshold, portfolio_map)
    )
    alerts.extend(
        _check_universe_removal_impact(db, organization_id, portfolio_map)
    )

    logger.info(
        "drift_scan_completed",
        organization_id=organization_id,
        alert_count=len(alerts),
    )

    return DriftScanResult(
        alerts=alerts,
        scanned_at=datetime.now(timezone.utc),
        organization_id=organization_id,
    )


def _build_portfolio_fund_map(
    db: Session,
    organization_id: str,
) -> dict[str, list[str]]:
    """Load all live portfolios once and build fund_id -> portfolio names map.

    Returns a dict where keys are fund_id strings and values are lists of
    portfolio display names that hold that fund. O(1) lookup per fund.
    """
    from app.domains.wealth.models.model_portfolio import ModelPortfolio

    portfolios = (
        db.query(ModelPortfolio)
        .filter(
            ModelPortfolio.organization_id == organization_id,
            ModelPortfolio.status == "live",
        )
        .all()
    )

    fund_to_portfolios: dict[str, list[str]] = defaultdict(list)
    for p in portfolios:
        portfolio_name = p.display_name or str(p.id)
        fund_selection = p.fund_selection_schema or {}
        for f in fund_selection.get("funds", []):
            fid = f.get("instrument_id", "")
            if fid:
                fund_to_portfolios[fid].append(portfolio_name)

    return dict(fund_to_portfolios)


def _check_style_drift(
    db: Session,
    organization_id: str,
    threshold: float,
    portfolio_map: dict[str, list[str]],
) -> list[DriftAlert]:
    """Check for funds with DTW drift above threshold."""
    from app.domains.wealth.models.fund import Fund
    from app.domains.wealth.models.risk import FundRiskMetrics

    alerts: list[DriftAlert] = []

    # Get latest risk metrics with drift scores
    funds_with_risk = (
        db.query(Fund, FundRiskMetrics)
        .join(
            FundRiskMetrics,
            FundRiskMetrics.instrument_id == Fund.fund_id,
        )
        .filter(
            Fund.organization_id == organization_id,
            Fund.is_active.is_(True),
        )
        .all()
    )

    for fund, risk in funds_with_risk:
        dtw_drift = getattr(risk, "dtw_drift", None)
        if dtw_drift is not None and float(dtw_drift) > threshold:
            affected = portfolio_map.get(str(fund.fund_id), [])
            alerts.append(DriftAlert(
                instrument_id=str(fund.fund_id),
                fund_name=fund.name,
                drift_score=float(dtw_drift),
                drift_type="style_drift",
                affected_portfolios=affected,
                detail=(
                    f"DTW drift score {float(dtw_drift):.3f} exceeds "
                    f"threshold {threshold:.3f}."
                ),
            ))

    return alerts


def _check_universe_removal_impact(
    db: Session,
    organization_id: str,
    portfolio_map: dict[str, list[str]],
) -> list[DriftAlert]:
    """Check impact of deactivated funds on live portfolios."""
    from app.domains.wealth.models.fund import Fund

    alerts: list[DriftAlert] = []

    deactivated = (
        db.query(Fund)
        .filter(
            Fund.organization_id == organization_id,
            Fund.is_active.is_(False),
        )
        .all()
    )

    for fund in deactivated:
        affected = portfolio_map.get(str(fund.fund_id), [])
        if affected:
            alerts.append(DriftAlert(
                instrument_id=str(fund.fund_id),
                fund_name=fund.name,
                drift_score=None,
                drift_type="universe_removal",
                affected_portfolios=affected,
                detail=(
                    f"Fund {fund.name} has been deactivated but is present in "
                    f"{len(affected)} live portfolio(s). Rebalance required."
                ),
            ))

    return alerts


def drift_alerts_to_json(result: DriftScanResult) -> list[dict[str, Any]]:
    """Serialize DriftScanResult to JSON-compatible list."""
    return [
        {
            "instrument_id": a.instrument_id,
            "fund_name": a.fund_name,
            "drift_score": a.drift_score,
            "drift_type": a.drift_type,
            "affected_portfolios": a.affected_portfolios,
            "detail": a.detail,
            "scanned_at": result.scanned_at.isoformat(),
            "organization_id": result.organization_id,
        }
        for a in result.alerts
    ]
