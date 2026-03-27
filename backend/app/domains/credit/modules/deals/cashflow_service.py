"""Cashflow analytics service for private credit deal performance.

Queries the deal_cashflows ledger to compute investment return metrics:
MOIC, net cash position, cash-to-cash multiple, IRR estimate, and
per-flow-type aggregations used by IC memo generation and portfolio monitoring.

This is analytical (investment performance), not operational cash management.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.deals.models import DealCashflow

logger = logging.getLogger(__name__)

# Flow types that represent money going OUT to the investment
_OUTFLOW_TYPES = frozenset({"disbursement", "capital_call"})

# Flow types that represent money coming BACK from the investment
_INFLOW_TYPES = frozenset({"repayment_principal", "repayment_interest", "distribution"})


@dataclass
class CashflowEntry:
    flow_date: date
    flow_type: str
    currency: str
    amount: Decimal
    description: str | None = None


def list_cashflows(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    limit: int = 50,
) -> list[CashflowEntry]:
    """Return cashflows for a deal, ordered by flow_date descending."""
    stmt = (
        select(DealCashflow)
        .where(
            DealCashflow.deal_id == deal_id,
            DealCashflow.fund_id == fund_id,
        )
        .order_by(DealCashflow.flow_date.desc())
        .limit(limit)
    )
    result = db.execute(stmt)
    rows = result.scalars().all()

    return [
        CashflowEntry(
            flow_date=r.flow_date,
            flow_type=r.flow_type,
            currency=r.currency,
            amount=Decimal(str(r.amount)),
            description=r.description,
        )
        for r in rows
    ]


def calculate_performance(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> dict[str, Any]:
    """Calculate deal-level performance metrics from cashflow ledger.

    Returns:
        total_invested: sum of outflows (disbursements + capital calls)
        total_received: sum of inflows (repayments + distributions)
        net_cashflow: total_received - total_invested
        moic: total_received / total_invested (None if no outflows)
        cash_to_cash_days: days between first outflow and first inflow (None if no inflows)

    """
    stmt = (
        select(
            DealCashflow.flow_type,
            func.sum(DealCashflow.amount).label("total"),
        )
        .where(
            DealCashflow.deal_id == deal_id,
            DealCashflow.fund_id == fund_id,
        )
        .group_by(DealCashflow.flow_type)
    )
    result = db.execute(stmt)
    totals_by_type = {row.flow_type: float(row.total) for row in result.all()}

    total_invested = sum(
        totals_by_type.get(ft, 0.0) for ft in _OUTFLOW_TYPES
    )
    total_received = sum(
        totals_by_type.get(ft, 0.0) for ft in _INFLOW_TYPES
    )
    # Fees reduce net position
    total_fees = totals_by_type.get("fee", 0.0)

    net_cashflow = total_received - total_invested - total_fees
    moic = (total_received / total_invested) if total_invested > 0 else None

    # Cash-to-cash: days between first outflow and first inflow
    cash_to_cash_days = _compute_cash_to_cash_days(db, fund_id=fund_id, deal_id=deal_id)

    return {
        "total_invested": total_invested,
        "total_received": total_received,
        "net_cashflow": net_cashflow,
        "moic": round(moic, 4) if moic is not None else None,
        "cash_to_cash_days": cash_to_cash_days,
    }


def calculate_portfolio_monitoring_metrics(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> dict[str, Any]:
    """Calculate portfolio monitoring metrics for IC dashboard.

    Breaks down cashflows by category for the CashflowSummary schema:
    contributions, distributions, interest, principal, net position,
    cash-to-cash multiple, IRR estimate, and event list.
    """
    # Per-type aggregation
    stmt = (
        select(
            DealCashflow.flow_type,
            func.sum(DealCashflow.amount).label("total"),
        )
        .where(
            DealCashflow.deal_id == deal_id,
            DealCashflow.fund_id == fund_id,
        )
        .group_by(DealCashflow.flow_type)
    )
    result = db.execute(stmt)
    by_type = {row.flow_type: float(row.total) for row in result.all()}

    total_contributions = (
        by_type.get("disbursement", 0.0) + by_type.get("capital_call", 0.0)
    )
    total_distributions = by_type.get("distribution", 0.0)
    interest_received = by_type.get("repayment_interest", 0.0)
    principal_returned = by_type.get("repayment_principal", 0.0)

    total_inflows = total_distributions + interest_received + principal_returned
    net_cash_position = total_inflows - total_contributions

    cash_to_cash_multiple = (
        (total_inflows / total_contributions)
        if total_contributions > 0
        else 0.0
    )

    # IRR estimate via simple annualized return
    irr_estimate = _estimate_irr(db, fund_id=fund_id, deal_id=deal_id, total_contributions=total_contributions)

    # Event list for timeline
    events = _build_cashflow_events(db, fund_id=fund_id, deal_id=deal_id)

    return {
        "total_contributions": round(total_contributions, 2),
        "total_distributions": round(total_distributions, 2),
        "interest_received": round(interest_received, 2),
        "principal_returned": round(principal_returned, 2),
        "net_cash_position": round(net_cash_position, 2),
        "cash_to_cash_multiple": round(cash_to_cash_multiple, 4),
        "irr_estimate": round(irr_estimate, 4) if irr_estimate is not None else 0.0,
        "cashflow_events": events,
    }


# ── Internal helpers ──────────────────────────────────────────────


def _compute_cash_to_cash_days(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> int | None:
    """Days between first outflow and first inflow."""
    first_out = db.execute(
        select(func.min(DealCashflow.flow_date)).where(
            DealCashflow.deal_id == deal_id,
            DealCashflow.fund_id == fund_id,
            DealCashflow.flow_type.in_(list(_OUTFLOW_TYPES)),
        ),
    ).scalar()

    if first_out is None:
        return None

    first_in = db.execute(
        select(func.min(DealCashflow.flow_date)).where(
            DealCashflow.deal_id == deal_id,
            DealCashflow.fund_id == fund_id,
            DealCashflow.flow_type.in_(list(_INFLOW_TYPES)),
        ),
    ).scalar()

    if first_in is None:
        return None

    return (first_in - first_out).days


def _estimate_irr(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    total_contributions: float,
) -> float | None:
    """Simple annualized return estimate.

    Uses (total_inflows / total_outflows)^(365/holding_days) - 1.
    Not a true IRR (no NPV solver) but sufficient for monitoring display.
    A proper IRR would require scipy.optimize which is not in deps.
    """
    if total_contributions <= 0:
        return None

    # Total inflows
    total_inflows_result = db.execute(
        select(func.sum(DealCashflow.amount)).where(
            DealCashflow.deal_id == deal_id,
            DealCashflow.fund_id == fund_id,
            DealCashflow.flow_type.in_(list(_INFLOW_TYPES)),
        ),
    ).scalar()

    total_inflows = float(total_inflows_result) if total_inflows_result else 0.0
    if total_inflows <= 0:
        return None

    # Holding period
    holding_days = _compute_cash_to_cash_days(db, fund_id=fund_id, deal_id=deal_id)
    if not holding_days or holding_days <= 0:
        # Use first outflow to today
        first_out = db.execute(
            select(func.min(DealCashflow.flow_date)).where(
                DealCashflow.deal_id == deal_id,
                DealCashflow.fund_id == fund_id,
                DealCashflow.flow_type.in_(list(_OUTFLOW_TYPES)),
            ),
        ).scalar()
        if first_out is None:
            return None
        holding_days = (date.today() - first_out).days
        if holding_days <= 0:
            return None

    moic = total_inflows / total_contributions
    years = holding_days / 365.0

    if years <= 0:
        return None

    # Annualized: MOIC^(1/years) - 1
    try:
        return moic ** (1.0 / years) - 1.0
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


_FLOW_TYPE_TO_EVENT = {
    "capital_call": "CAPITAL_CALL",
    "disbursement": "DISBURSEMENT",
    "repayment_principal": "PRINCIPAL_REPAYMENT",
    "repayment_interest": "INTEREST_PAYMENT",
    "distribution": "DISTRIBUTION",
    "fee": "FEE",
}


def _build_cashflow_events(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Build event list for CashflowEventItem schema."""
    stmt = (
        select(DealCashflow)
        .where(
            DealCashflow.deal_id == deal_id,
            DealCashflow.fund_id == fund_id,
        )
        .order_by(DealCashflow.flow_date.desc())
        .limit(limit)
    )
    result = db.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "eventDate": r.flow_date.isoformat(),
            "eventType": _FLOW_TYPE_TO_EVENT.get(r.flow_type, r.flow_type.upper()),
            "amount": float(r.amount),
            "currency": r.currency,
            "notes": r.description or "",
        }
        for r in rows
    ]
