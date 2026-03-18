"""Peer comparison types — data access moved to app.domains.wealth.services.quant_queries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog

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
