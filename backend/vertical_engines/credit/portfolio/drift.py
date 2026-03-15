"""Portfolio drift detection — detect performance drift across monitoring periods."""
from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    PerformanceDriftFlag,
)
from app.domains.credit.modules.portfolio.models import PortfolioMetric
from vertical_engines.credit.portfolio.models import safe_float

logger = structlog.get_logger()


def _latest_metric_by_investment(rows: list[PortfolioMetric], metric_name: str) -> dict[uuid.UUID, float]:
    out: dict[uuid.UUID, float] = {}
    for row in rows:
        if row.metric_name != metric_name:
            continue
        investment_id_raw = (row.meta or {}).get("investmentId")
        if not investment_id_raw:
            continue
        try:
            investment_id = uuid.UUID(str(investment_id_raw))
        except Exception:
            continue
        out[investment_id] = safe_float(row.metric_value) or 0.0
    return out


def detect_performance_drift(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[PerformanceDriftFlag]:
    logger.info("detect_performance_drift.start", fund_id=str(fund_id))

    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    if not investments:
        return []

    dates = list(
        db.execute(
            select(PortfolioMetric.as_of)
            .where(PortfolioMetric.fund_id == fund_id, PortfolioMetric.metric_name.like("AI4_%"))
            .group_by(PortfolioMetric.as_of)
            .order_by(PortfolioMetric.as_of.desc())
            .limit(2),
        ).scalars().all(),
    )

    db.execute(delete(PerformanceDriftFlag).where(PerformanceDriftFlag.fund_id == fund_id))
    if len(dates) < 2:
        db.flush()
        return []

    # Single query for both periods (excludes sentinel AI4_DATA_STATUS rows)
    both_period_rows = list(
        db.execute(
            select(PortfolioMetric).where(
                PortfolioMetric.fund_id == fund_id,
                PortfolioMetric.as_of.in_(dates),
                PortfolioMetric.metric_name.like("AI4_%"),
                PortfolioMetric.metric_name != "AI4_DATA_STATUS",
            ),
        ).scalars().all(),
    )
    current_rows = [r for r in both_period_rows if r.as_of == dates[0]]
    baseline_rows = [r for r in both_period_rows if r.as_of == dates[1]]

    current_by_metric = {
        "AI4_RETURN_EXPECTED_PCT": _latest_metric_by_investment(current_rows, "AI4_RETURN_EXPECTED_PCT"),
        "AI4_DEPLOYMENT_RATIO": _latest_metric_by_investment(current_rows, "AI4_DEPLOYMENT_RATIO"),
        "AI4_LIQUIDITY_DAYS": _latest_metric_by_investment(current_rows, "AI4_LIQUIDITY_DAYS"),
    }
    baseline_by_metric = {
        "AI4_RETURN_EXPECTED_PCT": _latest_metric_by_investment(baseline_rows, "AI4_RETURN_EXPECTED_PCT"),
        "AI4_DEPLOYMENT_RATIO": _latest_metric_by_investment(baseline_rows, "AI4_DEPLOYMENT_RATIO"),
        "AI4_LIQUIDITY_DAYS": _latest_metric_by_investment(baseline_rows, "AI4_LIQUIDITY_DAYS"),
    }

    thresholds = {
        "AI4_RETURN_EXPECTED_PCT": 10.0,
        "AI4_DEPLOYMENT_RATIO": 20.0,
        "AI4_LIQUIDITY_DAYS": 30.0,
    }

    flags: list[PerformanceDriftFlag] = []
    for inv in investments:
        for metric_name, threshold in thresholds.items():
            baseline = baseline_by_metric.get(metric_name, {}).get(inv.id)
            current = current_by_metric.get(metric_name, {}).get(inv.id)
            if baseline is None or current is None:
                continue
            if baseline == 0:
                drift_pct = 100.0 if current != 0 else 0.0
            else:
                drift_pct = ((current - baseline) / abs(baseline)) * 100.0

            if abs(drift_pct) < threshold:
                continue

            severity = "MEDIUM"
            if abs(drift_pct) >= (threshold * 1.5):
                severity = "HIGH"

            flag = PerformanceDriftFlag(
                fund_id=fund_id,
                access_level="internal",
                investment_id=inv.id,
                metric_name=metric_name,
                baseline_value=float(baseline),
                current_value=float(current),
                drift_pct=float(drift_pct),
                severity=severity,
                reasoning=(
                    f"Metric {metric_name} drift for {inv.investment_name} moved from {baseline:.4f} to {current:.4f} "
                    f"({drift_pct:.2f}%), above threshold {threshold:.2f}%."
                ),
                status="OPEN",
                as_of=as_of,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(flag)
            flags.append(flag)

    db.flush()
    logger.info("detect_performance_drift.done", fund_id=str(fund_id), count=len(flags))
    return flags
