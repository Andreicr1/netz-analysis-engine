"""Cross-vertical Pydantic schemas and dataclasses.

Contains response schemas used by multiple verticals.
Import direction: app.shared (no deps) — safe leaf module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel


class RegimeRead(BaseModel):
    """Market regime classification response schema.

    Used by both wealth risk routes and credit macro overlay.
    Phase 2: optional regional_regimes for hierarchical regime.
    """

    regime: str | None = None
    as_of_date: date | None = None
    profiles: dict[str, str] | None = None
    reasons: dict[str, str] | None = None
    regional_regimes: dict[str, str] | None = None  # Phase 2: region → regime


@dataclass
class StressSeverityResult:
    """Macro stress severity scoring result.

    Mutable dataclass — matches existing quant_engine convention
    (BreachStatus, RegimeResult, BlockDrift, DriftReport all use @dataclass).
    """

    score: float = 0.0
    level: str = "none"  # none | mild | moderate | severe (lowercase)
    triggers: list[str] = field(default_factory=list)
    sub_dimensions: dict[str, str] = field(default_factory=dict)
