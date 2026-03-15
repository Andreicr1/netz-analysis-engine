import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class FundRiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fund_id: uuid.UUID
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
    manager_score: Decimal | None = None
    score_components: dict[str, Any] | None = None


class FundScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fund_id: uuid.UUID
    name: str
    ticker: str | None = None
    manager_score: Decimal | None = None
    score_components: dict[str, Any] | None = None
    cvar_95_3m: Decimal | None = None
    sharpe_1y: Decimal | None = None
    return_1y: Decimal | None = None


class CVaRStatus(BaseModel):
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


class RegimeHistoryPoint(BaseModel):
    snapshot_date: date
    profile: str
    regime: str | None = None
