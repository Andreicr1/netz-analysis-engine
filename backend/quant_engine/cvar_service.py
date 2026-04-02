"""CVaR (Conditional Value-at-Risk) service.

Provides rolling CVaR computation for individual funds and portfolio-level
CVaR evaluation with breach detection.

Sync/async boundary: Pure computation functions are sync.
check_breach_status() accepts consecutive_breach_days as parameter —
the caller (wealth portfolio_eval) pre-fetches from PortfolioSnapshot.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "portfolio_profiles").
"""

from dataclasses import dataclass
from typing import Any, TypedDict

import numpy as np
import structlog

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
    config: dict[str, Any] | None = None,
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


def compute_regime_cvar(
    returns: np.ndarray,
    regime_probs: np.ndarray,
    confidence: float = 0.95,
    regime_threshold: float = 0.5,
) -> float:
    """CVaR conditional on stress regime.

    Uses only observations where regime_probs > threshold.
    Falls back to unconditional CVaR if stress subset has < 30 observations.

    Parameters
    ----------
    returns : np.ndarray
        (T,) portfolio returns.
    regime_probs : np.ndarray
        (T,) probability of being in stress regime per observation.
    confidence : float
        Confidence level (e.g. 0.95).
    regime_threshold : float
        Minimum regime probability to classify as stress.

    Returns
    -------
    float
        Conditional CVaR (negative = loss).

    """
    if len(returns) != len(regime_probs):
        logger.warning(
            "regime_cvar_length_mismatch",
            returns_len=len(returns),
            probs_len=len(regime_probs),
        )
        min_len = min(len(returns), len(regime_probs))
        returns = returns[-min_len:]
        regime_probs = regime_probs[-min_len:]

    stress_mask = regime_probs > regime_threshold
    if stress_mask.sum() >= 30:
        stress_returns = returns[stress_mask]
    else:
        logger.warning("cvar_conditional_insufficient_data", n=int(stress_mask.sum()))
        stress_returns = returns

    cvar, _ = compute_cvar_from_returns(stress_returns, confidence)
    return cvar


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


def check_breach_status(
    profile: str,
    cvar_current: float,
    consecutive_breach_days: int = 0,
    config: dict[str, Any] | None = None,
) -> BreachStatus:
    """Check breach status for a profile given current CVaR.

    Pure function — no DB access. Caller pre-fetches consecutive_breach_days
    from PortfolioSnapshot (or provides 0 for first evaluation).

    Args:
        profile: Portfolio profile name (conservative/moderate/growth).
        cvar_current: Current CVaR value (negative number = loss).
        consecutive_breach_days: Previous consecutive days in breach state.
            Caller fetches from PortfolioSnapshot.consecutive_breach_days.
        config: portfolio_profiles config dict from ConfigService.
               Falls back to hardcoded defaults if None.

    """
    profiles = resolve_cvar_config(config)
    profile_config: ProfileCVaRConfig = profiles.get(
        profile, _DEFAULT_CVAR_CONFIG.get(profile, _DEFAULT_CVAR_CONFIG["conservative"]),
    )
    cvar_limit = profile_config["limit"]

    utilization = get_cvar_utilization(cvar_current, cvar_limit)

    if utilization >= 100.0:
        new_consecutive = consecutive_breach_days + 1
    else:
        new_consecutive = 0

    trigger = classify_trigger_status(
        utilization,
        new_consecutive,
        warning_threshold_pct=profile_config["warning_pct"] * 100,
        breach_consecutive_days=profile_config["breach_days"],
    )

    return BreachStatus(
        trigger_status=trigger,
        cvar_current=cvar_current,
        cvar_limit=cvar_limit,
        cvar_utilized_pct=utilization,
        consecutive_breach_days=new_consecutive,
    )
