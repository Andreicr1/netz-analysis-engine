"""Frozen dataclasses for long-form report generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ChapterResult:
    """Result of a single chapter generation."""

    tag: str
    order: int
    title: str
    content: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"  # "completed" | "failed"
    confidence: float = 1.0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LongFormReportResult:
    """Complete long-form report result."""

    portfolio_id: str
    chapters: list[ChapterResult] = field(default_factory=list)
    status: str = "completed"  # "completed" | "partial" | "failed"
    error: str | None = None


CHAPTER_REGISTRY: list[dict[str, Any]] = [
    {"tag": "macro_context", "order": 1, "title": "Macro Context"},
    {"tag": "strategic_allocation", "order": 2, "title": "Strategic Allocation Rationale"},
    {"tag": "portfolio_composition", "order": 3, "title": "Portfolio Composition & Changes"},
    {"tag": "performance_attribution", "order": 4, "title": "Performance Attribution"},
    {"tag": "risk_decomposition", "order": 5, "title": "Risk Decomposition"},
    {"tag": "fee_analysis", "order": 6, "title": "Fee Analysis"},
    {"tag": "per_fund_highlights", "order": 7, "title": "Per-Fund Highlights"},
    {"tag": "forward_outlook", "order": 8, "title": "Forward Outlook"},
]
