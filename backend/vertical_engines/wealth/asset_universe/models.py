"""Frozen dataclasses for asset universe operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Input for creating a universe approval."""

    fund_id: uuid.UUID
    dd_report_id: uuid.UUID
    created_by: str
    organization_id: str


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Input for deciding on a universe approval."""

    approval_id: uuid.UUID
    decision: str  # "approved" | "rejected" | "watchlist"
    rationale: str | None
    decided_by: str


@dataclass(frozen=True, slots=True)
class UniverseAsset:
    """Read-only view of an approved fund in the universe."""

    fund_id: uuid.UUID
    fund_name: str
    block_id: str | None
    geography: str | None
    asset_class: str | None
    approval_status: str | None
    approval_decision: str
    approved_at: datetime | None


@dataclass(frozen=True, slots=True)
class DeactivationResult:
    """Result of deactivating an asset from the universe."""

    fund_id: uuid.UUID
    was_active: bool
    rebalance_needed: bool
