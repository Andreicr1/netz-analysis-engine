"""Fundamental factor model — returns, loadings, covariance assembly.

Pure sync except for ``build_fundamental_factor_returns`` which reads daily
benchmark returns and macro levels from the database. Config via parameter.

PCA residual diagnostics live in :mod:`backend.quant_engine.factor_model_pca`
so that ``assemble_factor_covariance`` cannot accidentally accept a
``PCADiagnostic`` at the type level (see PR-A3 Gate #5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock
from app.shared.models import MacroData

logger = structlog.get_logger()

# Constants
TRADING_DAYS_PER_YEAR = 252
_FACTOR_FFILL_LIMIT = 2  # forward-fill gaps up to 2 business days before dropping


async def build_fundamental_factor_returns(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Pull the 8 factor proxies from benchmark_nav + macro_data.

    Returns aligned daily returns DataFrame indexed by date. Gaps ≤ 2 business
    days are forward-filled; any date with remaining NaN is dropped and the
    dropped date range is recorded via an ``factor_data_gap`` audit event
    (PR-A3 Section A §12).

    Skipped factors (missing underlying series) are recorded via
    ``factor_skipped`` audit events (PR-A3 Section A §1). Callers can still
    read the plain ``factors.attrs["skipped"]`` for inline logging.
    """
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
        ticker = getattr(row, "benchmark_ticker", row[1])
        if ticker in OAS_TICKERS:
            raise ValueError(f"OAS level is not a total return. Refusing to use {ticker} as credit factor.")

    if benchmark_rows:
        bench_df = pd.DataFrame(
            [
                (
                    getattr(r, "nav_date", r[0]),
                    getattr(r, "benchmark_ticker", r[1]),
                    getattr(r, "return_1d", r[2]),
                )
                for r in benchmark_rows
            ],
            columns=["nav_date", "ticker", "return_1d"],
        )
        bench_pivot = bench_df.pivot(index="nav_date", columns="ticker", values="return_1d")
    else:
        bench_pivot = pd.DataFrame()

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
            [
                (
                    getattr(r, "obs_date", r[0]),
                    getattr(r, "series_id", r[1]),
                    getattr(r, "value", r[2]),
                )
                for r in macro_rows
            ],
            columns=["obs_date", "series_id", "value"],
        )
        macro_pivot = macro_df.pivot(index="obs_date", columns="series_id", values="value")
        macro_returns = np.log(macro_pivot / macro_pivot.shift(1))
    else:
        macro_returns = pd.DataFrame()

    combined = pd.concat([bench_pivot, macro_returns], axis=1)
    combined.index = pd.to_datetime(combined.index)
    combined = combined.ffill(limit=3).dropna(how="all")

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

    # A.1 — audit each skipped factor (was logger.warning only)
    for s in skipped:
        logger.warning(
            "factor_skipped",
            name=s["name"],
            reason=s["reason"],
            k_effective=len(factors.columns),
        )
        try:
            await write_audit_event(
                db,
                action="factor_skipped",
                entity_type="factor_model",
                entity_id="global_factor_returns",
                after={
                    "factor": s["name"],
                    "reason": s["reason"],
                    "k_effective": len(factors.columns),
                    "lookback_start": start_date.isoformat(),
                    "lookback_end": end_date.isoformat(),
                },
            )
        except Exception as audit_err:
            # Audit failure must not break estimation — log and continue
            logger.warning(
                "factor_skipped_audit_failed",
                factor=s["name"],
                err=str(audit_err),
            )

    factors.attrs["skipped"] = skipped

    # A.12 — forward-fill ≤ 2 days before dropping, audit the dropped range
    filled = factors.ffill(limit=_FACTOR_FFILL_LIMIT)
    dropped_mask = filled.isna().any(axis=1)
    dropped_dates = filled.index[dropped_mask]
    cleaned = filled.dropna()

    if len(dropped_dates) > 0:
        first_drop = dropped_dates.min().date().isoformat()
        last_drop = dropped_dates.max().date().isoformat()
        logger.warning(
            "factor_data_gap",
            dropped_count=int(len(dropped_dates)),
            first=first_drop,
            last=last_drop,
        )
        try:
            await write_audit_event(
                db,
                action="factor_data_gap",
                entity_type="factor_model",
                entity_id="global_factor_returns",
                after={
                    "dropped_count": int(len(dropped_dates)),
                    "first_dropped": first_drop,
                    "last_dropped": last_drop,
                    "ffill_limit_days": _FACTOR_FFILL_LIMIT,
                },
            )
        except Exception as audit_err:
            logger.warning("factor_data_gap_audit_failed", err=str(audit_err))

    cleaned.attrs["skipped"] = skipped
    return cleaned


@dataclass(frozen=True)
class FactorModelResult:
    """Result of PCA factor decomposition."""

    factor_returns: npt.NDArray[np.float64]
    factor_loadings: npt.NDArray[np.float64]
    factor_labels: list[str]  # interpreted labels (e.g. "market", "volatility")
    portfolio_factor_exposures: dict[str, float]  # {label: exposure}
    r_squared: float  # fraction of variance explained by K factors
    residual_returns: npt.NDArray[np.float64]


@dataclass(frozen=True)
class FundamentalFactorFit:
    """Result of fundamental factor model fitting."""

    loadings: npt.NDArray[np.float64]
    factor_cov: npt.NDArray[np.float64]
    residual_variance: npt.NDArray[np.float64]
    factor_names: list[str]
    residual_series: npt.NDArray[np.float64]
    r_squared_per_fund: npt.NDArray[np.float64]
    shrinkage_lambda: float | None = None
    factors_skipped: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FactorContributionResult:
    """Factor contribution to portfolio risk/return — eVestment p.46."""

    systematic_risk_pct: float  # % of total variance from factors
    specific_risk_pct: float  # % of total variance idiosyncratic
    factor_contributions: list[dict[str, object]]  # [{factor_label, pct_contribution}]
    r_squared: float  # overall model fit


def fit_fundamental_loadings(
    fund_returns_matrix: npt.NDArray[np.float64],
    factor_returns: npt.NDArray[np.float64],
    factor_names: list[str],
    ewma_lambda: float = 0.97,
) -> FundamentalFactorFit:
    """Per-fund weighted OLS on 5Y daily returns with EWMA weights.

    A.6 — ``factor_cov`` is computed on EWMA-weighted factor returns before
    Ledoit-Wolf shrinkage (weights: ``λ^(T-t)`` with ``λ = ewma_lambda``).
    A.9 — ``factor_names`` is required (no default). Column names are
    intrinsic to the factor matrix; callers must pass them explicitly.
    A.10 — ``r_squared_per_fund`` is guarded against zero-variance series.
    """
    T, N = fund_returns_matrix.shape
    K = factor_returns.shape[1]
    if len(factor_names) != K:
        raise ValueError(
            f"factor_names length {len(factor_names)} != factor_returns columns {K}"
        )

    # EWMA weights: lambda^(T-t)
    weights = ewma_lambda ** np.arange(T - 1, -1, -1)
    w_sqrt = np.sqrt(weights).reshape(-1, 1)

    # Weighted inputs for loadings regression
    X_w = factor_returns * w_sqrt
    Y_w = fund_returns_matrix * w_sqrt

    # Fit loadings B: (N x K) — weighted OLS via np.linalg.lstsq
    loadings, _, _, _ = np.linalg.lstsq(X_w, Y_w, rcond=None)
    loadings = loadings.T  # (N, K)

    # A.6 — Factor covariance on EWMA-weighted factor returns, then LW shrinkage.
    # Multiplying by w_sqrt is equivalent to weighting each observation by the
    # square root of the EWMA weight; the empirical covariance of the weighted
    # sample is the EWMA covariance up to a normalization constant that
    # Ledoit-Wolf absorbs into its shrinkage estimator.
    shrinkage_lambda: float | None = None
    try:
        from sklearn.covariance import LedoitWolf

        lw = LedoitWolf()
        lw.fit(factor_returns * w_sqrt)
        factor_cov = np.asarray(lw.covariance_, dtype=np.float64) * TRADING_DAYS_PER_YEAR
        shrinkage_lambda = float(lw.shrinkage_)
    except (ImportError, ValueError):
        logger.warning(
            "ledoit_wolf_failed",
            reason="sklearn absent or value error, using EWMA sample cov",
        )
        weighted = factor_returns * w_sqrt
        factor_cov = np.cov(weighted, rowvar=False) * TRADING_DAYS_PER_YEAR

    # Residuals using unweighted fit (for unbiased residual variance estimate)
    residual_series = fund_returns_matrix - (factor_returns @ loadings.T)
    residual_variance = np.var(residual_series, axis=0, ddof=1) * TRADING_DAYS_PER_YEAR

    # A.10 — guard against zero-variance funds (constant returns)
    total_var = np.var(fund_returns_matrix, axis=0, ddof=1)
    r_squared_per_fund: npt.NDArray[np.float64] = np.zeros(N, dtype=np.float64)
    nonzero = total_var > 1e-16
    if nonzero.any():
        r_squared_per_fund[nonzero] = 1.0 - (
            residual_variance[nonzero] / (total_var[nonzero] * TRADING_DAYS_PER_YEAR)
        )
    np.clip(r_squared_per_fund, 0.0, 1.0, out=r_squared_per_fund)

    return FundamentalFactorFit(
        loadings=np.asarray(loadings, dtype=np.float64),
        factor_cov=np.asarray(factor_cov, dtype=np.float64),
        residual_variance=np.asarray(residual_variance, dtype=np.float64),
        factor_names=list(factor_names),
        residual_series=np.asarray(residual_series, dtype=np.float64),
        r_squared_per_fund=r_squared_per_fund,
        shrinkage_lambda=shrinkage_lambda,
    )


def assemble_factor_covariance(fit: FundamentalFactorFit) -> npt.NDArray[np.float64]:
    """Returns Σ = B · F · B' + diag(D) with PSD enforcement.

    Accepts only ``FundamentalFactorFit`` — never ``PCADiagnostic`` (the
    residual diagnostic lives in ``factor_model_pca`` and has no bearing
    on covariance assembly). Enforced at the type level; see
    ``tests/quant_engine/test_assemble_factor_covariance_types.py``.
    """
    B = fit.loadings
    F = fit.factor_cov
    D_diag = fit.residual_variance

    sigma = (B @ F @ B.T) + np.diag(D_diag)
    sigma = (sigma + sigma.T) / 2

    N = sigma.shape[0]
    trace_sig = np.trace(sigma)
    clamp_val = max(1e-10, 1e-8 * trace_sig / N)

    eigvals, eigvecs = np.linalg.eigh(sigma)
    if eigvals.min() < clamp_val:
        eigvals = np.maximum(eigvals, clamp_val)
        sigma = eigvecs @ np.diag(eigvals) @ eigvecs.T

    return np.asarray(sigma, dtype=np.float64)


def decompose_factors(
    returns_matrix: npt.NDArray[np.float64],
    macro_proxies: dict[str, npt.NDArray[np.float64]] | None,
    portfolio_weights: npt.NDArray[np.float64],
    n_factors: int = 3,
) -> FactorModelResult:
    """Decompose fund returns into PCA factors and project portfolio weights."""
    T, N = returns_matrix.shape

    max_components = min(T - 1, N)
    if n_factors > max_components:
        logger.warning(
            "n_factors_capped",
            requested=n_factors,
            max_allowed=max_components,
            reason="more factors than min(T-1, N)",
        )
        n_factors = max(1, max_components)

    mean_returns = returns_matrix.mean(axis=0)
    centered = returns_matrix - mean_returns

    _, S, Vt = np.linalg.svd(centered, full_matrices=False)

    factor_loadings = Vt[:n_factors].T  # (N x K)
    factor_returns = centered @ factor_loadings  # (T x K)

    total_var = float(np.sum(S**2))
    explained_var = float(np.sum(S[:n_factors] ** 2))
    r_squared = explained_var / total_var if total_var > 0 else 0.0

    factor_labels = _label_factors(factor_returns, macro_proxies, n_factors)

    exposures = portfolio_weights @ factor_loadings
    portfolio_factor_exposures = {
        label: round(float(exposures[k]), 6) for k, label in enumerate(factor_labels)
    }

    portfolio_returns = returns_matrix @ portfolio_weights
    factor_component = factor_returns @ exposures
    residual_returns = portfolio_returns - factor_component

    return FactorModelResult(
        factor_returns=np.asarray(factor_returns, dtype=np.float64),
        factor_loadings=np.asarray(factor_loadings, dtype=np.float64),
        factor_labels=factor_labels,
        portfolio_factor_exposures=portfolio_factor_exposures,
        r_squared=round(r_squared, 6),
        residual_returns=np.asarray(residual_returns, dtype=np.float64),
    )


def _label_factors(
    factor_returns: npt.NDArray[np.float64],
    macro_proxies: dict[str, npt.NDArray[np.float64]] | None,
    n_factors: int,
) -> list[str]:
    """Assign interpretive labels to PCA factors via macro proxy correlations."""
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

            min_len = min(len(factor_k), len(proxy_series))
            if min_len < 20:
                continue

            f_slice = factor_k[-min_len:]
            p_slice = proxy_series[-min_len:]

            corr = _safe_correlation(f_slice, p_slice)
            if abs(corr) > abs(best_corr) and abs(corr) > 0.3:
                best_corr = corr
                best_label = proxy_name
                if corr < 0:
                    best_label = f"{proxy_name}_inv"

        if best_label != default_labels[k]:
            used_proxies.add(best_label.replace("_inv", ""))
        labels.append(best_label)

    return labels


def _safe_correlation(
    a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]
) -> float:
    """Compute Pearson correlation with zero-variance guard."""
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def compute_factor_contributions(
    factor_result: FactorModelResult,
) -> FactorContributionResult:
    """Decompose portfolio variance into factor (systematic) vs specific."""
    factor_returns = factor_result.factor_returns
    residual = factor_result.residual_returns
    labels = factor_result.factor_labels

    exposures = np.array(
        [factor_result.portfolio_factor_exposures[label] for label in labels]
    )

    factor_vars = np.array(
        [
            float(np.var(factor_returns[:, k], ddof=1)) * exposures[k] ** 2
            for k in range(len(labels))
        ]
    )

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

    factor_contributions: list[dict[str, object]] = [
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
