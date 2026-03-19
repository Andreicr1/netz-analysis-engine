"""Wealth domain status enums.

Provides typed enum constants for status/decision fields stored as String columns.
Use `.value` when assigning to ORM columns (e.g., DDReportStatus.approved.value).
Direct comparison works because both enums inherit from str.
"""

from enum import Enum


class DDReportStatus(str, Enum):
    draft = "draft"
    generating = "generating"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class UniverseDecision(str, Enum):
    pending = "pending"
    approved = "approved"
    watchlist = "watchlist"
    rejected = "rejected"
