"""PCA-based factor model decomposition.

Extracts latent factors from a fund returns matrix via PCA,
optionally labels them by correlation with macro proxy series,
and projects portfolio weights into factor space.

Pure sync. Zero I/O. Config via parameter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class FactorModelResult:
    """Result of PCA factor decomposition."""

    factor_returns: np.ndarray  # (T x K) — K extracted factor return series
    factor_loadings: np.ndarray  # (N x K) — each fund's exposure to factors
    factor_labels: list[str]  # interpreted labels (e.g. "market", "volatility")
    portfolio_factor_exposures: dict[str, float]  # {label: exposure}
    r_squared: float  # fraction of variance explained by K factors
    residual_returns: np.ndarray  # (T,) portfolio idiosyncratic component


@dataclass(frozen=True, slots=True)
class FactorContributionResult:
    """Factor contribution to portfolio risk/return — eVestment p.46."""

    systematic_risk_pct: float  # % of total variance from factors
    specific_risk_pct: float  # % of total variance idiosyncratic
    factor_contributions: list[dict]  # [{factor_label, pct_contribution}]
    r_squared: float  # overall model fit


def decompose_factors(
    returns_matrix: np.ndarray,
    macro_proxies: dict[str, np.ndarray] | None,
    portfolio_weights: np.ndarray,
    n_factors: int = 3,
) -> FactorModelResult:
    """Decompose fund returns into PCA factors and project portfolio weights.

    Parameters
    ----------
    returns_matrix : np.ndarray
        (T x N) daily returns of N funds over T observations.
    macro_proxies : dict[str, np.ndarray] | None
        Optional mapping of macro label -> (T,) series for factor labelling.
        E.g. {"VIX": vix_array, "DGS10": rates_array}.
    portfolio_weights : np.ndarray
        (N,) current portfolio weights.
    n_factors : int
        Number of PCA components to extract.

    Returns
    -------
    FactorModelResult
        Factor decomposition with exposures and R².

    """
    T, N = returns_matrix.shape

    # Guard: n_factors cannot exceed min(T-1, N)
    max_components = min(T - 1, N)
    if n_factors > max_components:
        logger.warning(
            "n_factors_capped",
            requested=n_factors,
            max_allowed=max_components,
            reason="more factors than min(T-1, N)",
        )
        n_factors = max(1, max_components)

    # Demean
    mean_returns = returns_matrix.mean(axis=0)
    centered = returns_matrix - mean_returns

    # SVD-based PCA (more numerically stable than eigendecomposition)
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)

    # Factor loadings: (N x K) — first K right singular vectors scaled by singular values
    factor_loadings = Vt[:n_factors].T  # (N x K)

    # Factor returns: (T x K) — projection of centered returns onto factor space
    factor_returns = centered @ factor_loadings  # (T x K)

    # Variance explained
    total_var = float(np.sum(S**2))
    explained_var = float(np.sum(S[:n_factors] ** 2))
    r_squared = explained_var / total_var if total_var > 0 else 0.0

    # Label factors by correlation with macro proxies
    factor_labels = _label_factors(factor_returns, macro_proxies, n_factors)

    # Portfolio factor exposures: w^T @ loadings
    exposures = portfolio_weights @ factor_loadings  # (K,)
    portfolio_factor_exposures = {
        label: round(float(exposures[k]), 6) for k, label in enumerate(factor_labels)
    }

    # Residual: portfolio return minus factor-explained component
    portfolio_returns = returns_matrix @ portfolio_weights  # (T,)
    factor_component = factor_returns @ exposures  # (T,)
    residual_returns = portfolio_returns - factor_component

    return FactorModelResult(
        factor_returns=factor_returns,
        factor_loadings=factor_loadings,
        factor_labels=factor_labels,
        portfolio_factor_exposures=portfolio_factor_exposures,
        r_squared=round(r_squared, 6),
        residual_returns=residual_returns,
    )


def _label_factors(
    factor_returns: np.ndarray,
    macro_proxies: dict[str, np.ndarray] | None,
    n_factors: int,
) -> list[str]:
    """Assign interpretive labels to PCA factors by correlating with macro proxies.

    Falls back to generic "factor_1", "factor_2" etc. if no proxies available.
    """
    default_labels = [f"factor_{k + 1}" for k in range(n_factors)]

    if not macro_proxies:
        return default_labels

    labels: list[str] = []
    used_proxies: set[str] = set()

    for k in range(n_factors):
        factor_k = factor_returns[:, k]
        best_label = default_labels[k]
        best_corr = 0.0

        for proxy_name, proxy_series in macro_proxies.items():
            if proxy_name in used_proxies:
                continue

            # Align lengths
            min_len = min(len(factor_k), len(proxy_series))
            if min_len < 20:
                continue

            f_slice = factor_k[-min_len:]
            p_slice = proxy_series[-min_len:]

            # Compute absolute correlation
            corr = _safe_correlation(f_slice, p_slice)
            if abs(corr) > abs(best_corr) and abs(corr) > 0.3:
                best_corr = corr
                best_label = proxy_name
                # Include sign for interpretability
                if corr < 0:
                    best_label = f"{proxy_name}_inv"

        if best_label != default_labels[k]:
            used_proxies.add(best_label.replace("_inv", ""))
        labels.append(best_label)

    return labels


def _safe_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Compute Pearson correlation with zero-variance guard."""
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def compute_factor_contributions(
    factor_result: FactorModelResult,
) -> FactorContributionResult:
    """Decompose portfolio variance into factor (systematic) vs specific.

    Uses the existing PCA decomposition to compute each factor's
    percentage contribution to total portfolio variance.
    """
    factor_returns = factor_result.factor_returns  # (T, K)
    residual = factor_result.residual_returns  # (T,)
    labels = factor_result.factor_labels

    # Variance of factor-explained component per factor
    # Each factor's contribution = var(exposure_k * factor_k)
    exposures = np.array([
        factor_result.portfolio_factor_exposures[label]
        for label in labels
    ])

    factor_vars = np.array([
        float(np.var(factor_returns[:, k], ddof=1)) * exposures[k] ** 2
        for k in range(len(labels))
    ])

    systematic_var = float(np.sum(factor_vars))
    specific_var = float(np.var(residual, ddof=1))
    total_var = systematic_var + specific_var

    if total_var < 1e-16:
        return FactorContributionResult(
            systematic_risk_pct=0.0,
            specific_risk_pct=0.0,
            factor_contributions=[],
            r_squared=0.0,
        )

    factor_contributions = [
        {
            "factor_label": labels[k],
            "pct_contribution": round(float(factor_vars[k] / total_var * 100), 2),
        }
        for k in range(len(labels))
    ]

    return FactorContributionResult(
        systematic_risk_pct=round(systematic_var / total_var * 100, 2),
        specific_risk_pct=round(specific_var / total_var * 100, 2),
        factor_contributions=factor_contributions,
        r_squared=factor_result.r_squared,
    )
