"""CVaR (Conditional Value-at-Risk) service.

Provides rolling CVaR computation for individual funds and portfolio-level
CVaR evaluation with breach detection.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "portfolio_profiles").
"""

from dataclasses import dataclass
from typing import TypedDict

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.portfolio import PortfolioSnapshot

logger = structlog.get_logger()


class ProfileCVaRConfig(TypedDict):
    """Typed configuration for per-profile CVaR parameters."""

    window_months: int
    confidence: float
    limit: float
    warning_pct: float
    breach_days: int


# Hardcoded fallback — used only if config parameter is not provided.
_DEFAULT_CVAR_CONFIG: dict[str, ProfileCVaRConfig] = {
    "conservative": {
        "window_months": 12,
        "confidence": 0.95,
        "limit": -0.08,
        "warning_pct": 0.80,
        "breach_days": 5,
    },
    "moderate": {
        "window_months": 3,
        "confidence": 0.95,
        "limit": -0.06,
        "warning_pct": 0.80,
        "breach_days": 3,
    },
    "growth": {
        "window_months": 6,
        "confidence": 0.95,
        "limit": -0.12,
        "warning_pct": 0.80,
        "breach_days": 5,
    },
}


def resolve_cvar_config(
    config: dict | None = None,
) -> dict[str, ProfileCVaRConfig]:
    """Extract per-profile CVaR config from portfolio_profiles config dict.

    Falls back to hardcoded defaults if config is None or malformed.
    """
    if config is None:
        return _DEFAULT_CVAR_CONFIG

    try:
        profiles = config.get("profiles", config)
        return {
            name: ProfileCVaRConfig(
                window_months=int(profile["cvar"]["window_months"]),
                confidence=float(profile["cvar"]["confidence"]),
                limit=float(profile["cvar"]["limit"]),
                warning_pct=float(profile["cvar"]["warning_pct"]),
                breach_days=int(profile["cvar"]["breach_days"]),
            )
            for name, profile in profiles.items()
            if isinstance(profile, dict) and "cvar" in profile
        }
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Malformed CVaR config, using defaults", error=str(e))
        return _DEFAULT_CVAR_CONFIG


@dataclass
class BreachStatus:
    trigger_status: str  # ok | warning | breach
    cvar_current: float
    cvar_limit: float
    cvar_utilized_pct: float
    consecutive_breach_days: int


def compute_cvar_from_returns(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Compute CVaR and VaR from a returns array.

    CVaR (Expected Shortfall) = mean of returns below VaR threshold.
    Returns (cvar, var) as negative numbers (losses).
    """
    if len(returns) < 5:
        return 0.0, 0.0

    sorted_returns = np.sort(returns)
    cutoff_idx = int(len(sorted_returns) * (1 - confidence))
    if cutoff_idx == 0:
        cutoff_idx = 1

    var = float(sorted_returns[cutoff_idx])
    cvar = float(sorted_returns[:cutoff_idx].mean())

    return cvar, var


def get_cvar_utilization(cvar_current: float, cvar_limit: float) -> float:
    """Compute CVaR utilization as a percentage of the limit.

    Both cvar_current and cvar_limit are negative numbers (losses).
    Returns a positive percentage (0-100+).
    """
    if cvar_limit == 0:
        return 0.0
    return abs(cvar_current / cvar_limit) * 100.0


def classify_trigger_status(
    utilization_pct: float,
    consecutive_days: int,
    warning_threshold_pct: float = 80.0,
    breach_consecutive_days: int = 5,
) -> str:
    """Classify CVaR trigger status. Returns 'ok', 'warning', or 'breach'."""
    if utilization_pct >= 100.0 and consecutive_days >= breach_consecutive_days:
        return "breach"
    if utilization_pct >= warning_threshold_pct:
        return "warning"
    return "ok"


async def check_breach_status(
    db: AsyncSession,
    profile: str,
    cvar_current: float,
    config: dict | None = None,
) -> BreachStatus:
    """Check breach status for a profile given current CVaR.

    Args:
        config: portfolio_profiles config dict from ConfigService.
               Falls back to hardcoded defaults if None.
    """
    profiles = resolve_cvar_config(config)
    profile_config = profiles.get(profile, _DEFAULT_CVAR_CONFIG.get(profile, {}))
    cvar_limit = profile_config["limit"]

    utilization = get_cvar_utilization(cvar_current, cvar_limit)

    # Get previous consecutive breach days from last snapshot
    stmt = (
        select(PortfolioSnapshot.consecutive_breach_days)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    prev_days = row if row is not None else 0

    if utilization >= 100.0:
        consecutive_days = prev_days + 1
    else:
        consecutive_days = 0

    trigger = classify_trigger_status(
        utilization,
        consecutive_days,
        warning_threshold_pct=profile_config["warning_pct"] * 100,
        breach_consecutive_days=profile_config["breach_days"],
    )

    return BreachStatus(
        trigger_status=trigger,
        cvar_current=cvar_current,
        cvar_limit=cvar_limit,
        cvar_utilized_pct=utilization,
        consecutive_breach_days=consecutive_days,
    )
