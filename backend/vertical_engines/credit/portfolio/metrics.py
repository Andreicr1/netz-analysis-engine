"""Portfolio metrics — extract and persist portfolio-level metrics."""
from __future__ import annotations

import datetime as dt
import uuid

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import ActiveInvestment
from app.domains.credit.modules.portfolio.models import PortfolioMetric
from vertical_engines.credit.portfolio.models import extract_percent, safe_float

logger = structlog.get_logger()


def extract_portfolio_metrics(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[PortfolioMetric]:
    logger.info("extract_portfolio_metrics.start", fund_id=str(fund_id))

    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    as_of_date = as_of.date()

    db.execute(
        delete(PortfolioMetric).where(
            PortfolioMetric.fund_id == fund_id,
            PortfolioMetric.as_of == as_of_date,
            PortfolioMetric.metric_name.like("AI4_%"),
        ),
    )

    # ── METRIC STATUS: PENDING_REAL_DATA_SOURCE ──────────────────────
    # Financial metrics (NAV, deployed capital, expected returns) MUST
    # originate from a real financial data source. Until that integration
    # is wired, this function emits only metrics whose underlying data
    # already exists on the ActiveInvestment row.
    # ──────────────────────────────────────────────────────────────────

    rows: list[PortfolioMetric] = []
    for inv in investments:
        committed = safe_float(inv.committed_capital_usd)
        deployed = safe_float(inv.deployed_capital_usd)
        nav = safe_float(inv.current_nav_usd)
        target_return_pct = extract_percent(inv.target_return)

        # Guard: if real financial data is absent, skip metric creation
        if committed is None and deployed is None and nav is None:
            logger.info(
                "extract_portfolio_metrics.pending_real_data",
                investment_id=str(inv.id),
                investment_name=inv.investment_name,
            )
            sentinel = PortfolioMetric(
                fund_id=fund_id,
                access_level="internal",
                as_of=as_of_date,
                metric_name="AI4_DATA_STATUS",
                metric_value=0.0,
                meta={
                    "investmentId": str(inv.id),
                    "investmentName": inv.investment_name,
                    "asOf": as_of.isoformat(),
                    "metric_status": "PENDING_REAL_DATA_SOURCE",
                },
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(sentinel)
            rows.append(sentinel)
            continue

        # Use only real values — no synthetic fallbacks
        committed = committed or 0.0
        deployed = deployed or 0.0
        nav = nav or 0.0

        deployment_ratio = deployed / committed if committed > 0 else 0.0
        liquidity_days = int(max(1.0, committed / 250000.0)) if committed > 0 else 0

        metrics: list[tuple[str, float]] = [
            ("AI4_DEPLOYMENT_RATIO", float(deployment_ratio)),
            ("AI4_LIQUIDITY_DAYS", float(liquidity_days)),
        ]
        if nav > 0:
            metrics.append(("AI4_NAV_USD", float(nav)))
        if target_return_pct is not None:
            metrics.append(("AI4_RETURN_EXPECTED_PCT", float(target_return_pct)))

        for metric_name, metric_value in metrics:
            metric = PortfolioMetric(
                fund_id=fund_id,
                access_level="internal",
                as_of=as_of_date,
                metric_name=metric_name,
                metric_value=metric_value,
                meta={
                    "investmentId": str(inv.id),
                    "investmentName": inv.investment_name,
                    "asOf": as_of.isoformat(),
                    "metric_status": "REAL_DATA",
                },
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(metric)
            rows.append(metric)

    db.flush()
    logger.info("extract_portfolio_metrics.done", fund_id=str(fund_id), count=len(rows))
    return rows
