"""Cashflow service stub — operational module not yet implemented.

Cash management is out of scope for the analysis engine (see CLAUDE.md).
This stub allows dependent modules (ai/portfolio.py, domain_ai/service.py)
to load without error. Functions return empty results.

When the cash_management add-on module is built, replace this stub
with real implementations.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class CashflowEntry:
    flow_date: date
    flow_type: str
    currency: str
    amount: Decimal
    description: str | None = None


def list_cashflows(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    limit: int = 50,
) -> list[CashflowEntry]:
    """Return cashflows for a deal. Stub: returns empty list."""
    logger.debug("cashflow_service.list_cashflows stub called (deal_id=%s)", deal_id)
    return []


def calculate_performance(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> dict[str, Any]:
    """Calculate deal performance metrics. Stub: returns zeros."""
    logger.debug("cashflow_service.calculate_performance stub called (deal_id=%s)", deal_id)
    return {
        "total_invested": 0.0,
        "total_received": 0.0,
        "net_cashflow": 0.0,
        "moic": None,
        "cash_to_cash_days": None,
    }


def calculate_portfolio_monitoring_metrics(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> dict[str, Any]:
    """Calculate portfolio monitoring metrics. Stub: returns zeros."""
    logger.debug("cashflow_service.calculate_portfolio_monitoring_metrics stub called (deal_id=%s)", deal_id)
    return {
        "total_contributions": 0.0,
        "total_distributions": 0.0,
        "interest_received": 0.0,
        "principal_returned": 0.0,
        "net_cash_position": 0.0,
        "cash_to_cash_multiple": 0.0,
        "irr_estimate": 0.0,
        "cashflow_events": [],
    }
