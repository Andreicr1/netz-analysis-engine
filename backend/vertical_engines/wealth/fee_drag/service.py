"""Fee Drag service — entry point for fee drag analysis.

Computes net expected returns after management, performance, and other fees.
Identifies fee-inefficient instruments and calculates portfolio-level aggregate.
Pure logic — no DB access.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from vertical_engines.wealth.fee_drag.models import (
    FeeBreakdown,
    FeeDragResult,
    PortfolioFeeDrag,
)

logger = structlog.get_logger(__name__)

# Default fee drag threshold — instruments above this are flagged
DEFAULT_FEE_DRAG_THRESHOLD = 0.50  # 50% of gross return consumed by fees


class FeeDragService:
    """Computes fee drag for instruments and portfolios."""

    def __init__(self, fee_drag_threshold: float = DEFAULT_FEE_DRAG_THRESHOLD) -> None:
        self._threshold = fee_drag_threshold

    def compute_fee_drag(
        self,
        instrument_id: uuid.UUID,
        instrument_name: str,
        instrument_type: str,
        attributes: dict[str, Any],
        gross_expected_return: float | None = None,
    ) -> FeeDragResult:
        """Compute fee drag for a single instrument.

        Fee data is extracted from JSONB attributes per instrument type:
        - fund: management_fee_pct, performance_fee_pct
        - bond: bid_ask_spread_pct
        - equity: brokerage_fee_pct

        Args:
            instrument_id: UUID of the instrument.
            instrument_name: Display name.
            instrument_type: 'fund', 'bond', or 'equity'.
            attributes: JSONB attributes dict with fee fields.
            gross_expected_return: Annualized gross return %. If None,
                uses attributes['expected_return_pct'].

        Returns:
            FeeDragResult with fee breakdown and efficiency flag.
        """
        fees = self._extract_fees(instrument_type, attributes)
        gross = gross_expected_return
        if gross is None:
            gross = float(attributes.get("expected_return_pct", 0.0))

        net = gross - fees.total_fee_pct

        # Fee drag ratio: what fraction of gross return is consumed by fees
        if gross > 0:
            drag_ratio = fees.total_fee_pct / gross
        else:
            drag_ratio = 1.0 if fees.total_fee_pct > 0 else 0.0

        return FeeDragResult(
            instrument_id=instrument_id,
            instrument_name=instrument_name,
            instrument_type=instrument_type,
            gross_expected_return=gross,
            fee_breakdown=fees,
            net_expected_return=net,
            fee_drag_pct=drag_ratio,
            fee_efficient=drag_ratio < self._threshold,
        )

    def compute_portfolio_fee_drag(
        self,
        instruments: list[dict[str, Any]],
        weights: dict[uuid.UUID, float] | None = None,
    ) -> PortfolioFeeDrag:
        """Compute portfolio-level aggregate fee drag.

        Args:
            instruments: List of dicts with instrument_id, name, instrument_type,
                        attributes, and optionally gross_expected_return.
            weights: Optional map of instrument_id -> portfolio weight (0.0-1.0).
                    If None, equal weight assumed.

        Returns:
            PortfolioFeeDrag with weighted aggregates.
        """
        results: list[FeeDragResult] = []

        for inst in instruments:
            try:
                result = self.compute_fee_drag(
                    instrument_id=inst["instrument_id"],
                    instrument_name=inst.get("name", str(inst["instrument_id"])),
                    instrument_type=inst.get("instrument_type", "fund"),
                    attributes=inst.get("attributes", {}),
                    gross_expected_return=inst.get("gross_expected_return"),
                )
                results.append(result)
            except Exception:
                logger.warning(
                    "fee_drag_computation_failed",
                    instrument_id=str(inst.get("instrument_id")),
                    exc_info=True,
                )

        if not results:
            return PortfolioFeeDrag(
                total_instruments=0,
                weighted_gross_return=0.0,
                weighted_net_return=0.0,
                weighted_fee_drag_pct=0.0,
                inefficient_count=0,
                results=(),
            )

        # Compute weighted aggregates
        n = len(results)
        if weights:
            total_weight = sum(weights.get(r.instrument_id, 0.0) for r in results)
            if total_weight > 0:
                w_gross = sum(
                    r.gross_expected_return * weights.get(r.instrument_id, 0.0)
                    for r in results
                ) / total_weight
                w_net = sum(
                    r.net_expected_return * weights.get(r.instrument_id, 0.0)
                    for r in results
                ) / total_weight
            else:
                w_gross = sum(r.gross_expected_return for r in results) / n
                w_net = sum(r.net_expected_return for r in results) / n
        else:
            w_gross = sum(r.gross_expected_return for r in results) / n
            w_net = sum(r.net_expected_return for r in results) / n

        w_drag = (w_gross - w_net) / w_gross if w_gross > 0 else 0.0
        inefficient = sum(1 for r in results if not r.fee_efficient)

        return PortfolioFeeDrag(
            total_instruments=n,
            weighted_gross_return=w_gross,
            weighted_net_return=w_net,
            weighted_fee_drag_pct=w_drag,
            inefficient_count=inefficient,
            results=tuple(results),
        )

    @staticmethod
    def _extract_fees(
        instrument_type: str,
        attributes: dict[str, Any],
    ) -> FeeBreakdown:
        """Extract fee components from JSONB attributes by instrument type."""
        mgmt = float(attributes.get("management_fee_pct", 0.0))
        perf = float(attributes.get("performance_fee_pct", 0.0))
        other = 0.0

        if instrument_type == "bond":
            other = float(attributes.get("bid_ask_spread_pct", 0.0))
        elif instrument_type == "equity":
            other = float(attributes.get("brokerage_fee_pct", 0.0))

        return FeeBreakdown(
            management_fee_pct=mgmt,
            performance_fee_pct=perf,
            other_fees_pct=other,
            total_fee_pct=mgmt + perf + other,
        )
