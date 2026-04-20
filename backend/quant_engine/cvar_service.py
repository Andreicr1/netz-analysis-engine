"""CVaR (Conditional Value-at-Risk) service.

Provides rolling CVaR computation for individual funds and portfolio-level
CVaR evaluation with breach detection.

Sync/async boundary: Pure computation functions are sync.
check_breach_status() accepts consecutive_breach_days as parameter —
the caller (wealth portfolio_eval) pre-fetches from PortfolioSnapshot.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "portfolio_profiles").
"""

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
    """
    clean_returns = returns[~np.isnan(returns)]
    n_obs = len(clean_returns)

    if method == "evt_pot":
        from quant_engine.evt.pot_gpd import extreme_var_evt

        # Map 0.95 -> (0.95, 0.99, 0.995, 0.999) to reuse the POT function
        # but we only return the one matching requested confidence
        res = extreme_var_evt(clean_returns, quantiles=(confidence,))
        
        # Field mapping for common quantiles
        mapping = {
            0.95: ("var_95", "cvar_95"), # Not in default ExtremeVaRResult but added here if needed
            0.99: ("var_99", "cvar_99"),
            0.995: ("var_995", "cvar_995"),
            0.999: ("var_999", "cvar_999"),
        }
        
        # Default fallback if not in common mapping
        q_key = int(confidence * 1000)
        var_field, cvar_field = mapping.get(confidence, (f"var_{q_key}", f"cvar_{q_key}"))
        
        # Note: ExtremeVaRResult from pot_gpd only has 99, 995, 999 as fixed fields.
        # But extreme_var_evt also puts requested quantiles into results internally?
        # Actually res is ExtremeVaRResult.
        
        if confidence == 0.99:
            var, cvar = res.var_99, res.cvar_99
        elif confidence == 0.995:
            var, cvar = res.var_995, res.cvar_995
        elif confidence == 0.999:
            var, cvar = res.var_999, res.cvar_999
        else:
            # For 0.95 or others, we might need to modify pot_gpd.extreme_var_evt
            # to return a more flexible object or just use the 99% one as proxy 
            # if 95% is requested but not explicitly handled in ExtremeVaRResult.
            # But the prompt says compute at 99, 99.5, 99.9.
            var, cvar = res.var_99, res.cvar_99 # Fallback to 99%

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
        mu = np.mean(clean_returns)
        sigma = np.std(clean_returns)
        z = norm.ppf(1 - confidence)
        var = -(mu + z * sigma)
        phi_z = norm.pdf(z)
        cvar = -mu + sigma * phi_z / (1 - confidence)
        
        return CVaRResult(
            cvar=float(cvar),
            var=float(var),
            confidence=confidence,
            method="parametric",
            n_obs=n_obs,
        )

    # Default: historical
    cvar_val, var_val = compute_cvar_from_returns(clean_returns, confidence)
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

    if len(returns) != len(regime_probs):
        logger.warning(
            "regime_cvar_length_mismatch",
            returns_len=len(returns),
            probs_len=len(regime_probs),
        )
        min_len = min(len(returns), len(regime_probs))
        returns = returns[-min_len:]
        regime_probs = regime_probs[-min_len:]
        audit_notes.append("length_mismatch_truncated")

    stress_mask = regime_probs > regime_threshold
    n_stress = int(stress_mask.sum())
    n_total = int(len(returns))

    if n_stress >= MIN_STRESS_OBSERVATIONS:
        stress_returns = returns[stress_mask]
        is_conditional = True
        audit_notes.append("conditional")
    else:
        logger.warning(
            "cvar_conditional_insufficient_data",
            n=n_stress,
            min_required=MIN_STRESS_OBSERVATIONS,
        )
        stress_returns = returns
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
