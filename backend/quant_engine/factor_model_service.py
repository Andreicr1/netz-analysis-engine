"""PCA-based factor model decomposition.

Extracts latent factors from a fund returns matrix via PCA,
optionally labels them by correlation with macro proxy series,
and projects portfolio weights into factor space.

Pure sync. Zero I/O. Config via parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock
from app.shared.models import MacroData

logger = structlog.get_logger()

# Constants
TRADING_DAYS_PER_YEAR = 252


async def build_fundamental_factor_returns(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Pull the 8 factor proxies from benchmark_nav + macro_data.

    Returns aligned daily returns DataFrame indexed by date.
    Forward-fill limit 3 days (matches fund return policy).
    """
    # 1. Fetch benchmark_nav proxies (SPY, IEF, HYG, IWM, IWD, na_equity_large, etc.)
    # We join with allocation_blocks to filter by benchmark_ticker
    OAS_TICKERS = ["BAMLH0A0HYM2", "BAMLHEOPHYM2"]
    benchmark_stmt = (
        select(
            BenchmarkNav.nav_date,
            AllocationBlock.benchmark_ticker,
            BenchmarkNav.return_1d,
        )
        .join(AllocationBlock, BenchmarkNav.block_id == AllocationBlock.block_id)
        .where(BenchmarkNav.nav_date >= start_date)
        .where(BenchmarkNav.nav_date <= end_date)
        .where(AllocationBlock.benchmark_ticker.in_(["SPY", "IEF", "HYG", "IWM", "IWD", "IWF", "EFA"] + OAS_TICKERS))
    )
    benchmark_res = await db.execute(benchmark_stmt)
    benchmark_rows = benchmark_res.all()

    # Defensive check for T6
    for row in benchmark_rows:
        # Support both Row (attribute access) and tuple (index access) for mocking compatibility
        ticker = getattr(row, "benchmark_ticker", row[1])
        if ticker in OAS_TICKERS:
            raise ValueError(f"OAS level is not a total return. Refusing to use {ticker} as credit factor.")

    # Convert to DataFrame
    if benchmark_rows:
        bench_df = pd.DataFrame(
            [(getattr(r, "nav_date", r[0]), getattr(r, "benchmark_ticker", r[1]), getattr(r, "return_1d", r[2])) for r in benchmark_rows],
            columns=["nav_date", "ticker", "return_1d"]
        )
        bench_pivot = bench_df.pivot(index="nav_date", columns="ticker", values="return_1d")
    else:
        bench_pivot = pd.DataFrame()

    # 2. Fetch macro_data proxies (DTWEXBGS, DCOILWTICO)
    macro_stmt = (
        select(MacroData.obs_date, MacroData.series_id, MacroData.value)
        .where(MacroData.obs_date >= start_date)
        .where(MacroData.obs_date <= end_date)
        .where(MacroData.series_id.in_(["DTWEXBGS", "DCOILWTICO"]))
    )
    macro_res = await db.execute(macro_stmt)
    macro_rows = macro_res.all()

    if macro_rows:
        macro_df = pd.DataFrame(
            [(getattr(r, "obs_date", r[0]), getattr(r, "series_id", r[1]), getattr(r, "value", r[2])) for r in macro_rows],
            columns=["obs_date", "series_id", "value"]
        )
        # Macro data is usually levels, we need returns (log returns preferred)
        macro_pivot = macro_df.pivot(index="obs_date", columns="series_id", values="value")
        macro_returns = np.log(macro_pivot / macro_pivot.shift(1))
    else:
        macro_returns = pd.DataFrame()

    # 3. Align and compute composite factors
    # All daily returns, forward-fill 3 days
    combined = pd.concat([bench_pivot, macro_returns], axis=1)
    combined.index = pd.to_datetime(combined.index)
    combined = combined.ffill(limit=3).dropna(how="all")

    # Define factors according to K=8 set
    factors = pd.DataFrame(index=combined.index)
    skipped: list[dict[str, str]] = []

    # 1. US equity beta (SPY)
    if "SPY" in combined.columns:
        factors["equity_us"] = combined["SPY"]
    else:
        skipped.append({"name": "equity_us", "reason": "SPY absent from benchmark_nav"})

    # 2. Duration (IEF)
    if "IEF" in combined.columns:
        factors["duration"] = combined["IEF"]
    else:
        skipped.append({"name": "duration", "reason": "IEF absent from benchmark_nav"})

    # 3. Credit spread (HYG - IEF)
    if "HYG" in combined.columns and "IEF" in combined.columns:
        factors["credit"] = combined["HYG"] - combined["IEF"]
    else:
        skipped.append({"name": "credit", "reason": "HYG or IEF absent from benchmark_nav"})

    # 4. USD strength (DTWEXBGS)
    if "DTWEXBGS" in combined.columns:
        factors["usd"] = combined["DTWEXBGS"]
    else:
        skipped.append({"name": "usd", "reason": "DTWEXBGS absent from macro_data"})

    # 5. Commodity (DCOILWTICO)
    if "DCOILWTICO" in combined.columns:
        factors["commodity"] = combined["DCOILWTICO"]
    else:
        skipped.append({"name": "commodity", "reason": "DCOILWTICO absent from macro_data"})

    # 6. Size (IWM - SPY)
    if "IWM" in combined.columns and "SPY" in combined.columns:
        factors["size"] = combined["IWM"] - combined["SPY"]
    else:
        skipped.append({"name": "size", "reason": "IWM or SPY absent from benchmark_nav"})

    # 7. Value (IWD - IWF)
    if "IWD" in combined.columns and "IWF" in combined.columns:
        factors["value"] = combined["IWD"] - combined["IWF"]
    else:
        reason = "IWF absent from benchmark_nav" if "IWF" not in combined.columns else "IWD absent"
        skipped.append({"name": "value", "reason": f"Value factor skipped: {reason}"})

    # 8. International (EFA - SPY)
    if "EFA" in combined.columns and "SPY" in combined.columns:
        factors["international"] = combined["EFA"] - combined["SPY"]
    else:
        reason = "EFA absent from benchmark_nav" if "EFA" not in combined.columns else "SPY absent"
        skipped.append({"name": "international", "reason": f"International factor skipped: {reason}"})

    # Log skipped factors
    for s in skipped:
        logger.warning("factor_skipped", name=s["name"], reason=s["reason"], k_effective=len(factors.columns))

    # Store skipped in metadata attribute for later retrieval
    factors.attrs["skipped"] = skipped

    return factors.dropna()


@dataclass(frozen=True)
class FactorModelResult:
    """Result of PCA factor decomposition."""

    factor_returns: np.ndarray  # type: ignore[type-arg]
    factor_loadings: np.ndarray  # type: ignore[type-arg]
    factor_labels: list[str]  # interpreted labels (e.g. "market", "volatility")
    portfolio_factor_exposures: dict[str, float]  # {label: exposure}
    r_squared: float  # fraction of variance explained by K factors
    residual_returns: np.ndarray  # type: ignore[type-arg]


@dataclass(frozen=True)
class FundamentalFactorFit:
    """Result of fundamental factor model fitting."""

    loadings: np.ndarray  # type: ignore[type-arg]
    factor_cov: np.ndarray  # type: ignore[type-arg]
    residual_variance: np.ndarray  # type: ignore[type-arg]
    factor_names: list[str]
    residual_series: np.ndarray  # type: ignore[type-arg]
    r_squared_per_fund: np.ndarray  # type: ignore[type-arg]
    factors_skipped: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class PCADiagnostic:
    """Diagnostic PCA results for residuals."""

    explained_variance_ratio: np.ndarray  # type: ignore[type-arg]
    cumulative_variance: float
    top_loadings: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class FactorContributionResult:
# ... (rest of the file)
    """Factor contribution to portfolio risk/return — eVestment p.46."""

    systematic_risk_pct: float  # % of total variance from factors
    specific_risk_pct: float  # % of total variance idiosyncratic
    factor_contributions: list[dict[str, object]]  # [{factor_label, pct_contribution}]
    r_squared: float  # overall model fit


def fit_fundamental_loadings(
    fund_returns_matrix: np.ndarray,  # type: ignore[type-arg]
    factor_returns: np.ndarray,  # type: ignore[type-arg]
    ewma_lambda: float = 0.97,
    factor_names: list[str] | None = None,
) -> FundamentalFactorFit:
    """Per-fund OLS regression on 5Y daily with EWMA weights.

    Parameters
    ----------
    fund_returns_matrix : np.ndarray
        (T x N) daily returns of N funds.
    factor_returns : np.ndarray
        (T x K) daily returns of K factors.
    ewma_lambda : float
        EWMA decay factor.
    factor_names : list[str] | None
        Optional list of factor labels.

    Returns
    -------
    FundamentalFactorFit
        Fitted factor model components.
    """
    T, N = fund_returns_matrix.shape
    K = factor_returns.shape[1]

    # EWMA weights: lambda^(T-t)
    weights = ewma_lambda ** np.arange(T - 1, -1, -1)
    # Square root of weights for OLS normalization (W @ Y = W @ X @ B)
    w_sqrt = np.sqrt(weights).reshape(-1, 1)

    # Weighted inputs
    X_w = factor_returns * w_sqrt
    Y_w = fund_returns_matrix * w_sqrt

    # Fit loadings B: (N x K)
    # Using np.linalg.lstsq for weighted OLS: X_w @ B = Y_w
    # np.linalg.lstsq returns (x, residuals, rank, s)
    loadings, _, _, _ = np.linalg.lstsq(X_w, Y_w, rcond=None)
    loadings = loadings.T  # (N, K)

    # Factor covariance F: (K x K) annualized
    # Apply Ledoit-Wolf shrinkage to F
    try:
        from sklearn.covariance import LedoitWolf
        lw = LedoitWolf()
        lw.fit(factor_returns)
        factor_cov = lw.covariance_ * TRADING_DAYS_PER_YEAR
    except (ImportError, ValueError):
        logger.warning("ledoit_wolf_failed", reason="sklearn absent or value error, using sample cov")
        factor_cov = np.cov(factor_returns, rowvar=False) * TRADING_DAYS_PER_YEAR

    # Residuals: D = Var(Y - X @ B)
    # E = Y - X @ B
    residual_series = fund_returns_matrix - (factor_returns @ loadings.T)
    # Variance per fund (diagonal of D)
    # We use sample variance (ddof=1)
    residual_variance = np.var(residual_series, axis=0, ddof=1) * TRADING_DAYS_PER_YEAR

    # R-squared per fund
    total_var = np.var(fund_returns_matrix, axis=0, ddof=1)
    r_squared_per_fund = 1.0 - (residual_variance / (total_var * TRADING_DAYS_PER_YEAR))
    # Clip R-squared to [0, 1]
    r_squared_per_fund = np.clip(r_squared_per_fund, 0.0, 1.0)

    # Recover factor names from DataFrame columns if possible
    if factor_names is None:
        factor_names = []
        if isinstance(factor_returns, pd.DataFrame):
            factor_names = factor_returns.columns.tolist()

    return FundamentalFactorFit(
        loadings=loadings,
        factor_cov=factor_cov,
        residual_variance=residual_variance,
        factor_names=factor_names,
        residual_series=residual_series,
        r_squared_per_fund=r_squared_per_fund,
    )


def assemble_factor_covariance(fit: FundamentalFactorFit) -> np.ndarray:  # type: ignore[type-arg]
    """Returns Σ = B · F · B' + diag(D).

    Applies PSD enforcement (eigenvalue clamp).
    """
    B = fit.loadings
    F = fit.factor_cov
    D_diag = fit.residual_variance

    # Sigma = B @ F @ B.T + Diag(D)
    sigma = (B @ F @ B.T) + np.diag(D_diag)

    # Symmetry enforcement
    sigma = (sigma + sigma.T) / 2

    # PSD enforcement (eigenvalue clamp)
    # Eigenvalue clamp at max(1e-10, 1e-8 * trace(Σ)/N)
    N = sigma.shape[0]
    trace_sig = np.trace(sigma)
    clamp_val = max(1e-10, 1e-8 * trace_sig / N)

    eigvals, eigvecs = np.linalg.eigh(sigma)
    if eigvals.min() < clamp_val:
        eigvals = np.maximum(eigvals, clamp_val)
        sigma = eigvecs @ np.diag(eigvals) @ eigvecs.T

    return sigma


def compute_residual_pca(residual_series: np.ndarray, n_components: int = 3) -> PCADiagnostic:  # type: ignore[type-arg]
    """Compute PCA on residuals for diagnostic purposes.

    Diagnostic only — never feeds back into covariance estimation.
    """
    T, N = residual_series.shape
    n_comp = min(n_components, T - 1, N)

    # Demean residuals
    centered = residual_series - residual_series.mean(axis=0)

    # SVD
    _, S, Vt = np.linalg.svd(centered, full_matrices=False)

    explained_variance = S**2 / (T - 1)
    total_var = explained_variance.sum()
    explained_variance_ratio = explained_variance[:n_comp] / total_var if total_var > 0 else np.zeros(n_comp)

    # Top loadings for first 3 components
    top_loadings = []
    for k in range(n_comp):
        loading_k = Vt[k]
        # Get indices of top 5 contributors to this component
        top_idx = np.argsort(np.abs(loading_k))[-5:][::-1]
        top_loadings.append({
            "component": k + 1,
            "explained_variance_ratio": float(explained_variance_ratio[k]),
            "top_contributors": [
                {"fund_index": int(i), "weight": float(loading_k[i])}
                for i in top_idx
            ]
        })

    return PCADiagnostic(
        explained_variance_ratio=explained_variance_ratio,
        cumulative_variance=float(np.sum(explained_variance_ratio)),
        top_loadings=top_loadings,
    )


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
