"""CVaR (Conditional Value-at-Risk) service.

Provides rolling CVaR computation for individual funds and portfolio-level
CVaR evaluation with breach detection.

Sync/async boundary: Pure computation functions are sync.
check_breach_status() accepts consecutive_breach_days as parameter —
the caller (wealth portfolio_eval) pre-fetches from PortfolioSnapshot.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "portfolio_profiles").

Sign convention (PR-Q13): all methods return **return-space** values.
Losses are negative (e.g. CVaR = -0.08 means 8% loss). This is
consistent with the historical path and with check_breach_status()
which compares cvar_current (negative) against cvar_limit (negative).
"""

import math
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

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

# Floating-point tolerance for breach boundary detection.
# Prevents false breaches when utilization is exactly at the 100% boundary
# due to floating-point arithmetic (e.g. 100.0000000001).
_BREACH_EPSILON = 1e-6


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


# Minimum stress observations required to compute a *conditional* regime CVaR
# instead of falling back to the unconditional distribution. 30 is the
# convention used by the existing risk worker; surfaced here so callers and
# tests can inspect the threshold without re-deriving it.
MIN_STRESS_OBSERVATIONS = 30


@dataclass(frozen=True, slots=True)
class RegimeCVaRResult:
    """Audited result of a regime-conditional CVaR computation."""

    value: float
    is_conditional: bool
    audit_note: str
    n_stress_obs: int
    n_total_obs: int


@dataclass(frozen=True)
class CVaRResult:
    """Consolidated CVaR result for all computation methods."""

    cvar: float
    var: float
    confidence: float
    method: str
    n_obs: int
    evt_xi: float | None = None
    evt_beta: float | None = None
    evt_threshold: float | None = None
    evt_n_exceedances: int | None = None
    degraded: bool = False
    degraded_reason: str | None = None


def compute_cvar(
    returns: np.ndarray,
    confidence: float = 0.95,
    method: Literal["historical", "parametric", "evt_pot"] = "historical",
) -> CVaRResult:
    """Compute CVaR using specified method.

    Central entry point for all fund and portfolio CVaR calculations.
    All methods return return-space values (losses are negative).
    """
    clean_returns = returns[np.isfinite(returns)]
    n_obs = int(len(clean_returns))

    # Fix 10: early guard for insufficient observations across ALL methods.
    if n_obs < 5:
        return CVaRResult(
            cvar=float("nan"),
            var=float("nan"),
            confidence=confidence,
            method=method,
            n_obs=n_obs,
            degraded=True,
            degraded_reason=f"insufficient_obs_{n_obs}",
        )

    if method == "evt_pot":
        from quant_engine.evt.pot_gpd import extreme_var_evt

        res = extreme_var_evt(clean_returns, quantiles=(confidence,))

        # PR-Q14: pot_gpd now exposes ``quantile_results`` keyed by the
        # exact quantile passed in.
        if confidence not in res.quantile_results:
            if not res.degraded:
                logger.warning(
                    "evt_quantile_missing_unexpected",
                    confidence=confidence,
                    populated=list(res.quantile_results.keys()),
                )
            var, cvar = 0.0, 0.0
        else:
            var, cvar = res.quantile_results[confidence]
            # Fix 2: EVT returns loss-space (positive = loss magnitude).
            # Convert to return-space (negative = loss) for consistency
            # with historical and parametric paths.
            var = -var
            cvar = -cvar

        return CVaRResult(
            cvar=cvar,
            var=var,
            confidence=confidence,
            method="evt_pot",
            n_obs=n_obs,
            evt_xi=res.fit.xi,
            evt_beta=res.fit.beta,
            evt_threshold=res.fit.u,
            evt_n_exceedances=res.fit.n_exceedances,
            degraded=res.degraded,
            degraded_reason=res.degraded_reason,
        )

    if method == "parametric":
        from scipy.stats import norm

        mu = float(np.mean(clean_returns))
        # Fix 9: use sample std (ddof=1) instead of population std (ddof=0).
        sigma = float(np.std(clean_returns, ddof=1))
        z = norm.ppf(1 - confidence)
        phi_z = norm.pdf(z)
        # Fix 1: return return-space values (negative for losses).
        # z is negative (e.g. -1.6449 for 95%), so mu + z*sigma is negative
        # for typical loss tails — exactly the return-space convention.
        var = mu + z * sigma
        cvar = mu - sigma * phi_z / (1 - confidence)

        return CVaRResult(
            cvar=float(cvar),
            var=float(var),
            confidence=confidence,
            method="parametric",
            n_obs=n_obs,
        )

    # Default: historical
    cvar_val, var_val = compute_cvar_from_returns(clean_returns, confidence)

    # Fix 5/10: propagate NaN from insufficient obs as degraded.
    if math.isnan(cvar_val):
        return CVaRResult(
            cvar=cvar_val,
            var=var_val,
            confidence=confidence,
            method="historical",
            n_obs=n_obs,
            degraded=True,
            degraded_reason=f"insufficient_obs_{n_obs}",
        )

    return CVaRResult(
        cvar=cvar_val,
        var=var_val,
        confidence=confidence,
        method="historical",
        n_obs=n_obs,
    )


def compute_regime_cvar_audited(
    returns: np.ndarray,  # type: ignore[type-arg]
    regime_probs: np.ndarray,  # type: ignore[type-arg]
    confidence: float = 0.95,
    regime_threshold: float = 0.5,
) -> RegimeCVaRResult:
    """Compute regime-conditional CVaR with full audit metadata.

    Same statistical contract as :func:`compute_regime_cvar`, but the
    return value is an audited :class:`RegimeCVaRResult`. New callers
    should prefer this function so the conditional / fallback distinction
    is never lost in the cracks.
    """
    audit_notes: list[str] = []

    # Fix 6: validate regime_probs are probabilities in [0, 1].
    if regime_probs.size > 0 and not np.all(
        (regime_probs >= 0.0) & (regime_probs <= 1.0)
    ):
        raise ValueError(
            f"regime_probs must be in [0, 1]; got range "
            f"[{regime_probs.min():.4f}, {regime_probs.max():.4f}]"
        )

    # Fix 7: preserve original returns for unconditional fallback.
    original_returns = returns

    if len(returns) != len(regime_probs):
        logger.warning(
            "regime_cvar_length_mismatch",
            returns_len=len(returns),
            probs_len=len(regime_probs),
        )
        min_len = min(len(returns), len(regime_probs))
        aligned_returns = returns[-min_len:]
        regime_probs = regime_probs[-min_len:]
        audit_notes.append("length_mismatch_truncated")
    else:
        aligned_returns = returns

    stress_mask = regime_probs > regime_threshold
    n_stress = int(stress_mask.sum())
    # Fix 7: report total from original history, not truncated alignment.
    n_total = int(len(original_returns))

    if n_stress >= MIN_STRESS_OBSERVATIONS:
        stress_returns = aligned_returns[stress_mask]
        is_conditional = True
        audit_notes.append("conditional")
    else:
        logger.warning(
            "cvar_conditional_insufficient_data",
            n=n_stress,
            min_required=MIN_STRESS_OBSERVATIONS,
        )
        # Fix 7: unconditional fallback uses FULL original history,
        # not the truncated alignment slice.
        stress_returns = original_returns
        is_conditional = False
        audit_notes.append("insufficient_stress_obs_fallback_to_unconditional")

    cvar, _ = compute_cvar_from_returns(stress_returns, confidence)

    return RegimeCVaRResult(
        value=cvar,
        is_conditional=is_conditional,
        audit_note=";".join(audit_notes),
        n_stress_obs=n_stress,
        n_total_obs=n_total,
    )


def compute_regime_cvar(
    returns: np.ndarray,
    regime_probs: np.ndarray,
    confidence: float = 0.95,
    regime_threshold: float = 0.5,
) -> float:
    """CVaR conditional on stress regime — returns a bare float.

    Backwards-compatible thin wrapper around
    :func:`compute_regime_cvar_audited`. Existing callers (and tests)
    keep their float contract; new callers that need to know whether
    the fallback fired should call ``compute_regime_cvar_audited``
    directly.
    """
    return compute_regime_cvar_audited(
        returns=returns,
        regime_probs=regime_probs,
        confidence=confidence,
        regime_threshold=regime_threshold,
    ).value


def compute_cvar_from_returns(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Compute CVaR and VaR from a returns array.

    CVaR (Expected Shortfall) = mean of returns below VaR threshold.
    Returns (cvar, var) as negative numbers (losses).
    """
    # Fix 5: return NaN for insufficient data instead of optimistic 0.0.
    if len(returns) < 5:
        return float("nan"), float("nan")

    sorted_returns = np.sort(returns)
    # Fix 8: use math.ceil for correct tail count and consistent VaR/CVaR.
    # Round to 10 decimal places first to avoid floating-point edge cases
    # (e.g. 20 * 0.05 = 1.0000000000000009 which ceil() rounds to 2).
    n = len(sorted_returns)
    tail_count = max(1, math.ceil(round(n * (1.0 - confidence), 10)))
    var = float(sorted_returns[tail_count - 1])
    cvar = float(sorted_returns[:tail_count].mean())

    return cvar, var


def get_cvar_utilization(cvar_current: float, cvar_limit: float) -> float:
    """Compute CVaR utilization as a percentage of the limit.

    Both cvar_current and cvar_limit are in return-space (negative = losses).
    Returns a positive percentage (0-100+), clamped to 0 for gains.
    """
    # Fix 4: reject invalid limits (must be negative in return-space).
    if cvar_limit >= 0:
        raise ValueError(
            f"cvar_limit must be negative (return-space loss limit), got {cvar_limit}"
        )
    # Fix 3: use ratio instead of abs() to correctly handle gains.
    # When both are negative (loss case): ratio is positive → utilization > 0.
    # When cvar_current > 0 (gain case): ratio is negative → clamped to 0.
    ratio = cvar_current / cvar_limit
    return max(0.0, ratio * 100.0)


def classify_trigger_status(
    utilization_pct: float,
    consecutive_days: int,
    warning_threshold_pct: float = 80.0,
    breach_consecutive_days: int = 5,
) -> str:
    """Classify CVaR trigger status. Returns 'ok', 'warning', or 'breach'."""
    # Fix 11: add epsilon tolerance to prevent false breaches from
    # floating-point drift at the exact 100% boundary.
    if (
        utilization_pct >= (100.0 + _BREACH_EPSILON)
        and consecutive_days >= breach_consecutive_days
    ):
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

    # Fix 12: NaN cvar_current (from Fix 5 insufficient obs) must surface
    # as a "degraded" status, not silently resolve to "ok" via NaN arithmetic.
    if math.isnan(cvar_current):
        return BreachStatus(
            trigger_status="degraded",
            cvar_current=cvar_current,
            cvar_limit=cvar_limit,
            cvar_utilized_pct=float("nan"),
            consecutive_breach_days=0,
        )

    utilization = get_cvar_utilization(cvar_current, cvar_limit)

    # Fix 13: use same epsilon as classify_trigger_status to keep the
    # consecutive-day counter consistent with the breach classification.
    if utilization >= (100.0 + _BREACH_EPSILON):
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
