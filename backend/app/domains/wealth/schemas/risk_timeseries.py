"""Response schemas for risk timeseries endpoint.

Flat [{time, value}] arrays optimized for TradingView chart injection.

Sanitisation retrofit — Phase 2 Session C commit 2
--------------------------------------------------
Audit §C.2 flagged this schema as leaking raw quant jargon
(``volatility_garch`` field, ``RISK_ON``/``RISK_OFF``/``CRISIS``
regime enums inside ``regime_prob``) directly to the frontend. This
module now routes the wire format through
``app.domains.wealth.schemas.sanitized`` at the API boundary:

* ``volatility_garch`` still exists as the internal Python attribute
  name (keeping every backend caller stable) but Pydantic emits it
  as ``conditional_volatility`` on the wire via
  ``serialization_alias``. Consumers call the route with
  ``response_model_by_alias=True`` so FastAPI honours the alias.
* Each ``regime_prob`` element's ``regime`` field is rewritten by a
  model-level ``@model_validator(mode='after')`` before the schema
  reaches ``model_dump()``: enum codes go through
  ``humanize_regime`` and come out as ``Expansion`` / ``Cautious``
  / ``Stress``.

No ``v2/`` split — per sanitized.py §1 the engine is contract-
breaking and the frontend adapts in the same PR wave.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.wealth.schemas.sanitized import humanize_regime


class TimeseriesPoint(BaseModel):
    time: str  # ISO-8601 date
    value: float


class RegimePoint(BaseModel):
    time: str  # ISO-8601 date
    value: float  # p_high_vol probability
    regime: str  # sanitised regime label (Expansion / Cautious / Stress)


class RiskTimeseriesOut(BaseModel):
    """Risk timeseries payload consumed by TradingView overlays.

    ``populate_by_name`` lets internal code construct the schema with
    ``volatility_garch=...`` while the wire format uses
    ``conditional_volatility``.
    """

    model_config = ConfigDict(populate_by_name=True)

    instrument_id: str
    ticker: str | None  # resolved from instruments_universe for display only
    from_date: date
    to_date: date
    drawdown: list[dict[str, Any]]  # [{time, value}]
    volatility_garch: list[dict[str, Any]] = Field(
        serialization_alias="conditional_volatility",
    )  # [{time, value}] — wire key is "conditional_volatility"
    regime_prob: list[dict[str, Any]]  # [{time, value, regime}]

    @model_validator(mode="after")
    def _sanitize_regime_points(self) -> "RiskTimeseriesOut":
        """Translate enum regime codes to institutional phrasing in place.

        Iterates the ``regime_prob`` list and rewrites each element's
        ``regime`` field through ``humanize_regime``. Non-string values
        and unknown codes pass through unchanged (by design — a new
        regime state added to the backend must remain visible until a
        label is registered).
        """
        rp = self.regime_prob
        if isinstance(rp, list):
            for point in rp:
                if isinstance(point, dict) and "regime" in point:
                    point["regime"] = humanize_regime(point["regime"])
        return self
