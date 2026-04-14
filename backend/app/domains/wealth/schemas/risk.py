"""Risk metrics response schemas.

CVaR / regime / GARCH fields are sanitised through the Wealth
nomenclature layer (`app.domains.wealth.schemas.sanitized`) before
reaching the API boundary. Field names (e.g. `cvar_95_1m`) remain
stable because they are contract-bearing identifiers; only values
(regime enums) and free-form dict keys (`score_components`) are
translated. See the charter in `sanitized.py`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.domains.wealth.schemas.sanitized import (
    SanitizedRegimeFieldMixin,
    SanitizedScoreComponentsMixin,
)


class FundRiskRead(SanitizedScoreComponentsMixin):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    instrument_id: uuid.UUID
    calc_date: date
    cvar_95_1m: Decimal | None = None
    cvar_95_3m: Decimal | None = None
    cvar_95_6m: Decimal | None = None
    cvar_95_12m: Decimal | None = None
    var_95_1m: Decimal | None = None
    var_95_3m: Decimal | None = None
    var_95_6m: Decimal | None = None
    var_95_12m: Decimal | None = None
    return_1m: Decimal | None = None
    return_3m: Decimal | None = None
    return_6m: Decimal | None = None
    return_1y: Decimal | None = None
    return_3y_ann: Decimal | None = None
    return_5y_ann: Decimal | None = None
    return_10y_ann: Decimal | None = None
    volatility_1y: Decimal | None = None
    max_drawdown_1y: Decimal | None = None
    max_drawdown_3y: Decimal | None = None
    sharpe_1y: Decimal | None = None
    sharpe_3y: Decimal | None = None
    sortino_1y: Decimal | None = None
    alpha_1y: Decimal | None = None
    beta_1y: Decimal | None = None
    information_ratio_1y: Decimal | None = None
    tracking_error_1y: Decimal | None = None
    rsi_14: Decimal | None = None
    bb_position: Decimal | None = None
    nav_momentum_score: Decimal | None = None
    flow_momentum_score: Decimal | None = None
    blended_momentum_score: Decimal | None = None
    volatility_garch: Decimal | None = None
    cvar_95_conditional: Decimal | None = None
    dtw_drift_score: Decimal | None = None
    manager_score: Decimal | None = None
    score_components: dict[str, Any] | None = None
    computed_at: datetime | None = None


class FundScoreRead(SanitizedScoreComponentsMixin):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    fund_id: uuid.UUID
    name: str
    ticker: str | None = None
    manager_score: Decimal | None = None
    score_components: dict[str, Any] | None = None
    cvar_95_3m: Decimal | None = None
    sharpe_1y: Decimal | None = None
    return_1y: Decimal | None = None


class CVaRStatus(SanitizedRegimeFieldMixin):
    profile: str
    calc_date: date | None = None
    cvar_current: Decimal | None = None
    cvar_limit: Decimal | None = None
    cvar_utilized_pct: Decimal | None = None
    trigger_status: str | None = None
    consecutive_breach_days: int = 0
    regime: str | None = None
    # Bayesian credible interval bounds (negative = loss, same sign as cvar_current).
    # cvar_lower_5 is the 5th posterior percentile (worst-case tail);
    # cvar_upper_95 is the 95th percentile (best-case tail within the interval).
    # Both are None until the Bayesian CVaR worker has run for the snapshot date.
    cvar_lower_5: Decimal | None = None
    cvar_upper_95: Decimal | None = None
    computed_at: datetime | None = None  # server-side computation timestamp
    next_expected_update: datetime | None = None  # next expected update
    # Momentum signals — profile-level averages from fund_risk_metrics
    rsi_14: float | None = None
    bb_position: float | None = None
    nav_momentum_score: float | None = None
    flow_momentum_score: float | None = None
    blended_momentum_score: float | None = None


class CVaRPoint(BaseModel):
    snapshot_date: date
    cvar_current: Decimal | None = None
    cvar_limit: Decimal | None = None
    cvar_utilized_pct: Decimal | None = None
    trigger_status: str | None = None


# RegimeRead — backward-compatible re-export.
# Canonical location: app.shared.schemas.RegimeRead
# This re-export will be removed after migration is verified.
from app.shared.schemas import RegimeRead  # noqa: F401


class RiskSummaryBatch(BaseModel):
    """Response for GET /risk/summary?profiles=a,b,c"""

    profile: str
    risk: CVaRStatus | None = None
    error: str | None = None  # if this profile failed, don't break the whole batch
    computed_at: datetime | None = None


class BatchRiskSummaryOut(BaseModel):
    """Aggregated risk summary for multiple profiles in a single request."""

    profiles: dict[str, CVaRStatus | None]
    computed_at: datetime
    profile_count: int


class RegimeHistoryPoint(SanitizedRegimeFieldMixin):
    snapshot_date: date
    profile: str
    regime: str | None = None


class ProfileMomentum(BaseModel):
    """Weighted-average momentum signals for a single risk profile."""

    profile: str
    rsi_14: float | None = None
    bb_position: float | None = None
    nav_momentum_score: float | None = None
    flow_momentum_score: float | None = None
    blended_momentum_score: float | None = None
    instrument_count: int = 0


class MomentumSummaryOut(BaseModel):
    """Aggregated momentum across all profiles."""

    profiles: dict[str, ProfileMomentum]
    computed_at: datetime
