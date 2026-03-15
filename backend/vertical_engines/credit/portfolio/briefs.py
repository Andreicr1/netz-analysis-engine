"""Portfolio board monitoring briefs — executive summaries per investment."""
from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    BoardMonitoringBrief,
    CashImpactFlag,
    CovenantStatusRegister,
    InvestmentRiskRegistry,
    PerformanceDriftFlag,
)

logger = structlog.get_logger()


def build_board_monitoring_briefs(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
    actor_id: str = "ai-engine",
    investments: list[ActiveInvestment] | None = None,
    drifts: list[PerformanceDriftFlag] | None = None,
    covenants: list[CovenantStatusRegister] | None = None,
    cash_flags: list[CashImpactFlag] | None = None,
    risks: list[InvestmentRiskRegistry] | None = None,
) -> list[BoardMonitoringBrief]:
    logger.info("build_board_monitoring_briefs.start", fund_id=str(fund_id))

    if investments is None:
        investments = list(db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id)).scalars().all())
    if drifts is None:
        drifts = list(db.execute(select(PerformanceDriftFlag).where(PerformanceDriftFlag.fund_id == fund_id)).scalars().all())
    if covenants is None:
        covenants = list(db.execute(select(CovenantStatusRegister).where(CovenantStatusRegister.fund_id == fund_id)).scalars().all())
    if cash_flags is None:
        cash_flags = list(db.execute(select(CashImpactFlag).where(CashImpactFlag.fund_id == fund_id)).scalars().all())
    if risks is None:
        risks = list(db.execute(select(InvestmentRiskRegistry).where(InvestmentRiskRegistry.fund_id == fund_id)).scalars().all())

    by_inv_drift: dict[uuid.UUID, list[PerformanceDriftFlag]] = defaultdict(list)
    for row in drifts:
        by_inv_drift[row.investment_id].append(row)

    by_inv_cov: dict[uuid.UUID, list[CovenantStatusRegister]] = defaultdict(list)
    for row in covenants:
        by_inv_cov[row.investment_id].append(row)

    by_inv_cash: dict[uuid.UUID, list[CashImpactFlag]] = defaultdict(list)
    for row in cash_flags:
        by_inv_cash[row.investment_id].append(row)

    by_inv_risk: dict[uuid.UUID, list[InvestmentRiskRegistry]] = defaultdict(list)
    for row in risks:
        by_inv_risk[row.investment_id].append(row)

    saved: list[BoardMonitoringBrief] = []
    for inv in investments:
        drift_rows = by_inv_drift.get(inv.id, [])
        cov_rows = by_inv_cov.get(inv.id, [])
        cash_rows = by_inv_cash.get(inv.id, [])
        risk_rows = by_inv_risk.get(inv.id, [])

        overall = next((r for r in risk_rows if r.risk_type == "OVERALL"), None)
        overall_level = overall.risk_level if overall else "LOW"

        performance_view = f"{len(drift_rows)} drift events registered; high severity count: {sum(1 for r in drift_rows if r.severity == 'HIGH')}."
        covenant_view = f"{len(cov_rows)} covenant status entries; breach/warning count: {sum(1 for r in cov_rows if r.status in {'BREACH', 'WARNING'})}."
        liquidity_view = f"{len(cash_rows)} cash impact events; high severity count: {sum(1 for r in cash_rows if r.severity == 'HIGH')}."
        risk_view = f"Current overall risk level is {overall_level}; lifecycle status {inv.lifecycle_status}."

        actions = [
            "Review high-severity drift flags and validate baseline assumptions.",
            "Confirm covenant testing cadence and remediation ownership.",
            "Validate liquidity forecast against projected capital calls/distributions.",
        ]

        brief_payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "investment_id": inv.id,
            "executive_summary": (
                f"{inv.investment_name} monitored as of {as_of.isoformat()} with overall risk {overall_level}."
            ),
            "performance_view": performance_view,
            "covenant_view": covenant_view,
            "liquidity_view": liquidity_view,
            "risk_reclassification_view": risk_view,
            "recommended_actions": actions,
            "last_generated_at": as_of,
            "as_of": as_of,
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        existing = db.execute(
            select(BoardMonitoringBrief).where(
                BoardMonitoringBrief.fund_id == fund_id,
                BoardMonitoringBrief.investment_id == inv.id,
            ),
        ).scalar_one_or_none()

        if existing is None:
            row = BoardMonitoringBrief(**brief_payload)
            db.add(row)
            db.flush()
        else:
            for key_name, value in brief_payload.items():
                if key_name == "created_by":
                    continue
                setattr(existing, key_name, value)
            db.flush()
            row = existing

        saved.append(row)

    db.flush()
    logger.info("build_board_monitoring_briefs.done", fund_id=str(fund_id), count=len(saved))
    return saved
