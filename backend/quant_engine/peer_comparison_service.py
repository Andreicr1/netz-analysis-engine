"""Peer comparison service — ranks fund against peers within block.

Domain-agnostic, reusable across verticals. Uses batch queries (no N+1).

Pure sync, config as parameter.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.risk import FundRiskMetrics

logger = structlog.get_logger()


@dataclass(frozen=True)
class PeerRank:
    """A fund's ranking within its peer group."""

    fund_id: uuid.UUID
    fund_name: str
    manager_score: float | None
    sharpe_1y: float | None
    return_1y: float | None
    rank: int
    peer_count: int


@dataclass(frozen=True)
class PeerComparison:
    """Result of peer comparison for a target fund."""

    target_fund_id: uuid.UUID
    block_id: str
    peers: list[PeerRank] = field(default_factory=list)
    target_rank: int | None = None
    peer_count: int = 0


def compare(
    db: Session,
    *,
    fund_id: uuid.UUID,
    block_id: str,
    aum_min: Decimal | None = None,
    aum_max: Decimal | None = None,
    config: dict[str, Any] | None = None,
) -> PeerComparison:
    """Rank a fund against its peers within a block.

    Uses a single batch query with IN clause + BETWEEN for AUM filter.
    No N+1 queries.

    Parameters
    ----------
    db : Session
        Database session.
    fund_id : uuid.UUID
        Target fund to rank.
    block_id : str
        Allocation block for peer grouping.
    aum_min, aum_max : Decimal | None
        Optional AUM range filter.
    config : dict | None
        Optional config overrides.
    """
    # Batch query: all active, approved funds in the same block
    stmt = select(Fund).where(
        Fund.block_id == block_id,
        Fund.is_active.is_(True),
        Fund.approval_status == "approved",
    )

    if aum_min is not None:
        stmt = stmt.where(Fund.aum_usd >= aum_min)
    if aum_max is not None:
        stmt = stmt.where(Fund.aum_usd <= aum_max)

    funds_result = db.execute(stmt)
    funds = list(funds_result.scalars().all())

    if not funds:
        return PeerComparison(target_fund_id=fund_id, block_id=block_id)

    peer_fund_ids = [f.fund_id for f in funds]

    # Batch fetch latest risk metrics (DISTINCT ON)
    risk_stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.fund_id.in_(peer_fund_ids))
        .order_by(FundRiskMetrics.fund_id, FundRiskMetrics.calc_date.desc())
        .distinct(FundRiskMetrics.fund_id)
    )
    risk_result = db.execute(risk_stmt)
    risk_map = {r.fund_id: r for r in risk_result.scalars().all()}

    # Build scored peers
    scored = []
    for f in funds:
        risk = risk_map.get(f.fund_id)
        scored.append({
            "fund_id": f.fund_id,
            "fund_name": f.name,
            "manager_score": float(risk.manager_score) if risk and risk.manager_score else None,
            "sharpe_1y": float(risk.sharpe_1y) if risk and risk.sharpe_1y else None,
            "return_1y": float(risk.return_1y) if risk and risk.return_1y else None,
        })

    # Sort by manager_score descending (None at end)
    scored.sort(key=lambda s: s["manager_score"] or -999, reverse=True)

    peers = []
    target_rank = None
    for i, s in enumerate(scored, 1):
        peer = PeerRank(
            fund_id=s["fund_id"],
            fund_name=s["fund_name"],
            manager_score=s["manager_score"],
            sharpe_1y=s["sharpe_1y"],
            return_1y=s["return_1y"],
            rank=i,
            peer_count=len(scored),
        )
        peers.append(peer)
        if s["fund_id"] == fund_id:
            target_rank = i

    return PeerComparison(
        target_fund_id=fund_id,
        block_id=block_id,
        peers=peers,
        target_rank=target_rank,
        peer_count=len(scored),
    )
