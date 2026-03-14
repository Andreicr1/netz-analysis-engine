"""CVaR (Conditional Value-at-Risk) service.

Provides rolling CVaR computation for individual funds and portfolio-level
CVaR evaluation with breach detection.

Profile CVaR config is loaded from calibration/config/profiles.yaml via
@lru_cache. Falls back to hardcoded defaults if the file is missing.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import TypedDict

import numpy as np
import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_calibration_path
from app.domains.wealth.models.portfolio import PortfolioSnapshot

logger = structlog.get_logger()


class ProfileCVaRConfig(TypedDict):
    """Typed configuration for per-profile CVaR parameters.

    Mirrors the ``cvar`` section of each profile in
    ``calibration/config/profiles.yaml``.
    """

    window_months: int
    confidence: float
    limit: float
    warning_pct: float
    breach_days: int


# Hardcoded fallback if profiles.yaml is missing
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


@lru_cache(maxsize=1)
def get_profile_cvar_config() -> dict[str, ProfileCVaRConfig]:
    """Load CVaR config from profiles.yaml, fallback to hardcoded defaults."""
    try:
        config_path = get_calibration_path() / "profiles.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)
        profiles = data["profiles"]
        return {
            name: ProfileCVaRConfig(
                window_months=int(profile["cvar"]["window_months"]),
                confidence=float(profile["cvar"]["confidence"]),
                limit=float(profile["cvar"]["limit"]),
                warning_pct=float(profile["cvar"]["warning_pct"]),
                breach_days=int(profile["cvar"]["breach_days"]),
            )
            for name, profile in profiles.items()
        }
    except FileNotFoundError:
        logger.warning("profiles.yaml not found, using default CVaR config")
        return _DEFAULT_CVAR_CONFIG
    except (KeyError, TypeError, ValueError) as e:
        logger.error("profiles.yaml malformed for CVaR config", error=str(e))
        return _DEFAULT_CVAR_CONFIG


# Module-level alias for backward compatibility — callers that import
# PROFILE_CVAR_CONFIG directly will get the cached YAML-loaded config.
PROFILE_CVAR_CONFIG = get_profile_cvar_config()


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
    """Primitive: compute CVaR utilization as a percentage of the limit.

    Both cvar_current and cvar_limit are negative numbers (losses).
    Returns a positive percentage (0-100+).
    Example: cvar_current=-0.05, cvar_limit=-0.08 → 62.5%
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
    """Pure function: classify CVaR trigger status.

    Returns one of: 'ok', 'warning', 'breach'.
    """
    if utilization_pct >= 100.0 and consecutive_days >= breach_consecutive_days:
        return "breach"
    if utilization_pct >= warning_threshold_pct:
        return "warning"
    return "ok"


async def check_breach_status(
    db: AsyncSession,
    profile: str,
    cvar_current: float,
) -> BreachStatus:
    """Check breach status for a profile given current CVaR."""
    config = PROFILE_CVAR_CONFIG[profile]
    cvar_limit = config["limit"]

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

    # If currently over limit, increment; otherwise reset
    if utilization >= 100.0:
        consecutive_days = prev_days + 1
    else:
        consecutive_days = 0

    trigger = classify_trigger_status(
        utilization,
        consecutive_days,
        warning_threshold_pct=config["warning_pct"] * 100,
        breach_consecutive_days=config["breach_days"],
    )

    return BreachStatus(
        trigger_status=trigger,
        cvar_current=cvar_current,
        cvar_limit=cvar_limit,
        cvar_utilized_pct=utilization,
        consecutive_breach_days=consecutive_days,
    )


