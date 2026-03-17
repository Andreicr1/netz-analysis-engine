"""Peer Group Engine domain models.

Frozen dataclasses for cross-boundary safety. These are NOT ORM models —
ORM models live in backend/app/domains/wealth/models/.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PeerGroup:
    """A dynamically computed peer group for an instrument."""

    peer_group_key: str
    instrument_type: str
    block_id: str
    member_count: int
    members: tuple[uuid.UUID, ...]  # instrument_ids in this group
    fallback_level: int  # 0=full, 1=partial, 2=block_only


@dataclass(frozen=True, slots=True)
class MetricRanking:
    """Percentile ranking for a single metric within a peer group."""

    metric: str
    value: float | None
    percentile: float | None  # 0.0-100.0
    lower_is_better: bool


@dataclass(frozen=True, slots=True)
class PeerRanking:
    """Full peer ranking result for one instrument."""

    instrument_id: uuid.UUID
    peer_group_key: str
    peer_count: int
    fallback_level: int
    rankings: tuple[MetricRanking, ...]
    composite_percentile: float | None  # weighted avg of metric percentiles
    ranked_at: datetime


@dataclass(frozen=True, slots=True)
class PeerGroupNotFound:
    """Returned when no valid peer group can be formed."""

    instrument_id: uuid.UUID
    reason: str  # "instrument_not_found" | "insufficient_peers" | "no_block_assigned" | "no_metrics"
