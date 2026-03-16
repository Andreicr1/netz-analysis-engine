"""Frozen dataclasses for DD Report Engine.

All types that cross async/thread boundaries MUST be frozen dataclasses
(CLAUDE.md rule: ORM thread safety).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Chapter definitions ──────────────────────────────────────────

CHAPTER_REGISTRY: list[dict[str, Any]] = [
    {"tag": "executive_summary", "order": 1, "title": "Executive Summary", "type": "ANALYTICAL", "max_tokens": 3000},
    {"tag": "investment_strategy", "order": 2, "title": "Investment Strategy & Process", "type": "DESCRIPTIVE", "max_tokens": 2500},
    {"tag": "manager_assessment", "order": 3, "title": "Fund Manager Assessment", "type": "ANALYTICAL", "max_tokens": 4000},
    {"tag": "performance_analysis", "order": 4, "title": "Performance Analysis", "type": "ANALYTICAL", "max_tokens": 4000},
    {"tag": "risk_framework", "order": 5, "title": "Risk Management Framework", "type": "ANALYTICAL", "max_tokens": 4000},
    {"tag": "fee_analysis", "order": 6, "title": "Fee Analysis", "type": "DESCRIPTIVE", "max_tokens": 2500},
    {"tag": "operational_dd", "order": 7, "title": "Operational Due Diligence", "type": "DESCRIPTIVE", "max_tokens": 2500},
    {"tag": "recommendation", "order": 8, "title": "Recommendation", "type": "ANALYTICAL", "max_tokens": 4000},
]

# Tags that can be generated in parallel (1-7)
PARALLEL_CHAPTER_TAGS = [ch["tag"] for ch in CHAPTER_REGISTRY if ch["order"] <= 7]
# Recommendation must be sequential (depends on chapters 1-7)
SEQUENTIAL_CHAPTER_TAG = "recommendation"

# Minimum chapters required to generate recommendation
MIN_CHAPTERS_FOR_RECOMMENDATION = 5


@dataclass(frozen=True, slots=True)
class ChapterResult:
    """Result of a single chapter generation."""

    tag: str
    order: int
    title: str
    content_md: str | None
    evidence_refs: dict[str, Any] = field(default_factory=dict)
    quant_data: dict[str, Any] = field(default_factory=dict)
    critic_iterations: int = 0
    critic_status: str = "pending"
    status: str = "completed"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DDReportResult:
    """Complete DD Report result — crosses async/thread boundary."""

    fund_id: str
    chapters: list[ChapterResult]
    confidence_score: float
    decision_anchor: str | None
    status: str
    error: str | None = None
