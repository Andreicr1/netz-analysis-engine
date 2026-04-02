"""Portfolio risk reclassification — compute multi-dimensional risk levels."""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    CashImpactFlag,
    CovenantStatusRegister,
    InvestmentRiskRegistry,
    PerformanceDriftFlag,
)

logger = structlog.get_logger()


def _evaluate_liquidity_cash_impact(
    db: Session,
    *,
    fund_id: uuid.UUID,
) -> list[CashImpactFlag]:
    """Evaluate liquidity/cash impact for investments.

    NOTE: Cash management domain has been removed from scope.
    Returns an empty list. Will be re-implemented when cash management
    is brought back or replaced by an external cash data feed.
    """
    db.execute(delete(CashImpactFlag).where(CashImpactFlag.fund_id == fund_id))
    db.flush()
    logger.info("evaluate_liquidity_cash_impact.noop", fund_id=str(fund_id))
    return []


def reclassify_investment_risk(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
) -> list[InvestmentRiskRegistry]:
    logger.info("reclassify_investment_risk.start", fund_id=str(fund_id))

    investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())

    drifts = list(db.execute(select(PerformanceDriftFlag).where(PerformanceDriftFlag.fund_id == fund_id)).scalars().all())
    covenants = list(db.execute(select(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id)).scalars().all())
    cash_flags = list(db.execute(select(CashImpactFlag).where(CashImpactFlag.fund_id == fund_id)).scalars().all())

    by_inv_drift: dict[uuid.UUID, list[PerformanceDriftFlag]] = defaultdict(list)
    for drift_row in drifts:
        by_inv_drift[drift_row.investment_id].append(drift_row)

    by_inv_cov: dict[uuid.UUID, list[CovenantStatusRegister]] = defaultdict(list)
    for cov_row in covenants:
        by_inv_cov[cov_row.investment_id].append(cov_row)

    by_inv_cash: dict[uuid.UUID, list[CashImpactFlag]] = defaultdict(list)
    for cash_row in cash_flags:
        by_inv_cash[cash_row.investment_id].append(cash_row)

    db.execute(delete(InvestmentRiskRegistry).where(InvestmentRiskRegistry.fund_id == fund_id))

    saved: list[InvestmentRiskRegistry] = []
    for inv in investments:
        drift_high = any(flag.severity == "HIGH" for flag in by_inv_drift.get(inv.id, []))
        covenant_breach = any(row.status in {"BREACH", "WARNING"} for row in by_inv_cov.get(inv.id, []))
        cash_high = any(flag.severity == "HIGH" for flag in by_inv_cash.get(inv.id, []))

        performance_level = "MEDIUM" if by_inv_drift.get(inv.id) else "LOW"
        if drift_high:
            performance_level = "HIGH"

        covenant_level = "HIGH" if covenant_breach else ("MEDIUM" if by_inv_cov.get(inv.id) else "LOW")
        liquidity_level = "HIGH" if cash_high else ("MEDIUM" if by_inv_cash.get(inv.id) else "LOW")

        overall = "LOW"
        if "HIGH" in {performance_level, covenant_level, liquidity_level}:
            overall = "HIGH"
        elif "MEDIUM" in {performance_level, covenant_level, liquidity_level}:
            overall = "MEDIUM"

        risk_rows = [
            (
                "PERFORMANCE",
                performance_level,
                "STABLE" if performance_level == "LOW" else "UP",
                f"Performance monitoring derived from {len(by_inv_drift.get(inv.id, []))} drift flags.",
            ),
            (
                "COVENANT",
                covenant_level,
                "UP" if covenant_level in {"MEDIUM", "HIGH"} else "STABLE",
                f"Covenant surveillance shows {len(by_inv_cov.get(inv.id, []))} status records.",
            ),
            (
                "LIQUIDITY",
                liquidity_level,
                "UP" if liquidity_level in {"MEDIUM", "HIGH"} else "STABLE",
                f"Cash impact monitoring produced {len(by_inv_cash.get(inv.id, []))} flags.",
            ),
            (
                "OVERALL",
                overall,
                "UP" if overall in {"MEDIUM", "HIGH"} else "STABLE",
                "Overall risk reclassification computed from performance, covenant, and liquidity dimensions.",
            ),
        ]

        for risk_type, level, trend, rationale in risk_rows:
            risk_entry = InvestmentRiskRegistry(
                fund_id=fund_id,
                access_level="internal",
                investment_id=inv.id,
                risk_type=risk_type,
                risk_level=level,
                trend=trend,
                rationale=rationale,
                source_evidence={
                    "driftFlags": [str(x.id) for x in by_inv_drift.get(inv.id, [])],
                    "covenantRows": [str(x.id) for x in by_inv_cov.get(inv.id, [])],
                    "cashFlags": [str(x.id) for x in by_inv_cash.get(inv.id, [])],
                },
                as_of=as_of,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(risk_entry)
            saved.append(risk_entry)

    db.flush()
    logger.info("reclassify_investment_risk.done", fund_id=str(fund_id), count=len(saved))
    return saved
