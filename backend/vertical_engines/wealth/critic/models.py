"""Critic Engine frozen dataclasses.

CriticVerdict is the output of the critic engine. Frozen for thread safety
when crossing async/sync boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CriticVerdict:
    """Immutable critic verdict for a DD Report chapter.

    Taxonomy:
        ACCEPT   — chapter meets quality standards, no rewrite needed
        REVISE   — specific feedback provided, chapter will be regenerated
        ESCALATE — human review required (circuit breaker or fatal flaws)
    """

    chapter_tag: str = ""
    taxonomy: str = "ACCEPT"  # ACCEPT | REVISE | ESCALATE
    fatal_flaws: list[dict[str, str]] = field(default_factory=list)
    material_gaps: list[dict[str, str]] = field(default_factory=list)
    optimism_bias: list[dict[str, str]] = field(default_factory=list)
    data_quality_flags: list[dict[str, str]] = field(default_factory=list)
    macro_consistency_flags: list[dict[str, Any]] = field(default_factory=list)
    confidence_delta: float = 0.0
    overall_assessment: str = ""
    feedback: str = ""

    @property
    def total_issues(self) -> int:
        return (
            len(self.fatal_flaws)
            + len(self.material_gaps)
            + len(self.optimism_bias)
            + len(self.data_quality_flags)
        )

    @property
    def rewrite_required(self) -> bool:
        return self.taxonomy == "REVISE"

    @property
    def escalation_required(self) -> bool:
        return self.taxonomy == "ESCALATE"


@dataclass(frozen=True, slots=True)
class CriticReport:
    """Aggregate critic results for an entire DD Report."""

    verdicts: list[CriticVerdict] = field(default_factory=list)
    wall_clock_seconds: float = 0.0
    circuit_breaker_triggered: bool = False
    chapters_escalated: list[str] = field(default_factory=list)

    @property
    def all_accepted(self) -> bool:
        return all(v.taxonomy == "ACCEPT" for v in self.verdicts)

    @property
    def total_issues(self) -> int:
        return sum(v.total_issues for v in self.verdicts)
