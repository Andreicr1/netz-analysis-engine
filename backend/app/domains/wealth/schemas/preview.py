"""PR-A13.1 — preview-cvar endpoint DTOs.

Separate from ``schemas/model_portfolio.py`` (568 lines; adding the four
DTOs here would push it past the readability threshold). The preview
endpoint is a single concern; the schema module mirrors that.

Shape parity with the cascade telemetry persisted on
``portfolio_construction_runs.cascade_telemetry`` so the frontend can
use the same ``previewBand ?? serverBand`` merge without transforming.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PreviewCvarRequest(BaseModel):
    """Operator probe of a proposed CVaR limit.

    ``cvar_limit`` bounds match the Builder slider's ``min=0.005,
    max=0.20`` (PR-A13 Section C.2), widened slightly on the floor
    (0.0005) so unit tests exercising the below-universe-floor edge
    case remain inside the accepted range.
    """

    model_config = ConfigDict(extra="forbid")

    cvar_limit: float = Field(..., ge=0.0005, le=0.20)
    mandate: Literal["conservative", "moderate", "growth", "aggressive"] | None = None


class AchievableReturnBandDTO(BaseModel):
    """Mirrors ``cascade_telemetry.achievable_return_band`` exactly."""

    model_config = ConfigDict(extra="forbid")

    lower: float
    upper: float
    lower_at_cvar: float
    upper_at_cvar: float


class OperatorSignalDTO(BaseModel):
    """Sanitised operator signal — same enum as the persisted telemetry."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "feasible",
        "cvar_limit_below_universe_floor",
        "upstream_data_missing",
        "constraint_polytope_empty",
    ]
    binding: str | None = None
    message_key: str


class PreviewCvarResponse(BaseModel):
    """Preview band + min-CVaR + operator signal + cache metadata."""

    model_config = ConfigDict(extra="forbid")

    achievable_return_band: AchievableReturnBandDTO
    min_achievable_cvar: float
    operator_signal: OperatorSignalDTO
    cached: bool
    wall_ms: int
