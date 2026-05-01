"""Fundamental factor model — returns, loadings, covariance assembly.

Pure sync except for ``build_fundamental_factor_returns`` which reads daily
benchmark NAV levels and macro levels from the database.  Config via parameter.

Return convention: simple returns throughout (pct_change on price levels).
Both benchmark and macro returns are computed from levels, ensuring a single
consistent convention across the factor panel (PR-Q15 Fix 6).

PCA residual diagnostics live in :mod:`backend.quant_engine.factor_model_pca`
so that ``assemble_factor_covariance`` cannot accidentally accept a
``PCADiagnostic`` at the type level (see PR-A3 Gate #5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.shared.models import MacroData

# benchmark_nav + allocation_blocks are global tables (no RLS, shared across all
# tenants — see CLAUDE.md "Global tables").  We query them via raw SQL instead
# of importing the wealth-domain ORM models, which would breach the
# import-linter contract "Vertical-agnostic quant services must not import
# wealth domain models" (pyproject.toml).

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

    Returns aligned daily simple-return DataFrame indexed by date.

    PR-Q15 Fix 1: forward-fills NAV *levels* (not returns) before computing
    returns via ``pct_change()``.  A holiday-gap carries the price forward,
    producing a 0% return for the closed day, whereas filling returns would
    repeat Friday's % change on Monday (compounding bug).

    PR-Q15 Fix 5: spread factors (credit, size, value, international) are
    masked to NaN on dates where either leg's level was forward-filled, so
    a stale leg cannot distort the spread signal.

    PR-Q15 Fix 6: macro returns use ``pct_change()`` (simple), not
    ``np.log()``, matching the benchmark convention.

    PR-Q15 Fix 7: final ``dropna(how='all')`` (not ``dropna()``) preserves
    early history for factors that exist while others do not yet.
    """
    OAS_TICKERS = ["BAMLH0A0HYM2", "BAMLHEOPHYM2"]

    # ── 1. Benchmark NAV LEVELS (PR-Q15 Fix 1: levels, not return_1d) ────
    # Raw SQL keeps quant_engine independent of app.domains.wealth ORM models
    # (import-linter contract).  benchmark_nav + allocation_blocks are global
    # (no RLS) so the lack of ORM-mediated tenancy filters is intentional.
    benchmark_stmt = text(
        """
        SELECT bn.nav_date, ab.benchmark_ticker, bn.nav
        FROM benchmark_nav AS bn
        JOIN allocation_blocks AS ab ON bn.block_id = ab.block_id
        WHERE bn.nav_date >= :start_date
          AND bn.nav_date <= :end_date
          AND ab.benchmark_ticker IN :tickers
        """
    ).bindparams(bindparam("tickers", expanding=True))
    benchmark_res = await db.execute(
        benchmark_stmt,
        {
            "start_date": start_date,
            "end_date": end_date,
            "tickers": ["SPY", "IEF", "HYG", "IWM", "IWD", "IWF", "EFA"] + OAS_TICKERS,
        },
    )
    benchmark_rows = benchmark_res.all()

    # Defensive filter (PR-Q35 F06): OAS levels are not total returns. Previously
    # raised ValueError, taking down the entire factor model fit. Per charter §3
    # (degraded > crash), filter OAS rows defensively + record for the skipped
    # accumulator so consumers see the degradation via FundamentalFactorFit.
    # Reference: Wave 6 Session 03 F06, audit-validation-session03.md.
    _oas_filtered: list[str] = []
    for row in benchmark_rows:
        ticker = getattr(row, "benchmark_ticker", row[1])
        if ticker in OAS_TICKERS:
            _oas_filtered.append(ticker)

    if _oas_filtered:
        logger.warning(
            "factor_returns_oas_level_filtered",
            oas_tickers=sorted(set(_oas_filtered)),
            rows_dropped=len(_oas_filtered),
            reason="OAS levels are not total returns; filtered defensively (PR-Q35 F06)",
        )
        benchmark_rows = [
            row for row in benchmark_rows
            if getattr(row, "benchmark_ticker", row[1]) not in OAS_TICKERS
        ]

    if benchmark_rows:
        bench_df = pd.DataFrame(
            [
                (
                    getattr(r, "nav_date", r[0]),
                    getattr(r, "benchmark_ticker", r[1]),
                    float(getattr(r, "nav", r[2]))
                    if getattr(r, "nav", r[2]) is not None
                    else None,
                )
                for r in benchmark_rows
            ],
            columns=["nav_date", "ticker", "nav"],
        )
        bench_df["nav"] = bench_df["nav"].astype("float64")

        # PR-A15 dedup safeguard.  Use first() for NAV levels: duplicate
        # (nav_date, ticker) rows from legacy block aliases are identical,
        # so first() == mean().  If genuinely different blocks share a
        # ticker, first() picks one consistently (mean() would average
        # different price levels, producing distorted pct_change).
        _raw_rows = len(bench_df)
        bench_df = (
            bench_df
            .groupby(["nav_date", "ticker"], as_index=False)["nav"]
            .first()
        )
        if len(bench_df) != _raw_rows:
            logger.warning(
                "factor_returns_input_duplicates_deduped",
                source="benchmark_nav",
                raw_rows=_raw_rows,
                deduped_rows=len(bench_df),
                dropped=_raw_rows - len(bench_df),
            )

        bench_levels = bench_df.pivot(
            index="nav_date", columns="ticker", values="nav",
        )

        # PR-Q15 Fix 5: record which dates have authoritative (non-filled)
        # level data for each ticker before filling.
        authoritative_bench = bench_levels.notna()

        # PR-Q15 Fix 1: forward-fill LEVELS (carrying last-known price
        # across holidays/gaps — semantically correct: price didn't change).
        bench_levels = bench_levels.ffill(limit=_FACTOR_FFILL_LIMIT)

        # Compute simple returns from filled levels.
        # PR-Q92: fill_method=None (pad default deprecated in pandas 2.x).
        # Levels are already ffill-ed above with limit=_FACTOR_FFILL_LIMIT;
        # pct_change should not fill again.
        bench_returns = bench_levels.pct_change(fill_method=None)
    else:
        bench_returns = pd.DataFrame()
        authoritative_bench = pd.DataFrame()

    # ── 2. Macro LEVELS → simple returns (PR-Q15 Fix 6) ──────────────────
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
                    float(getattr(r, "value", r[2]))
                    if getattr(r, "value", r[2]) is not None
                    else None,
                )
                for r in macro_rows
            ],
            columns=["obs_date", "series_id", "value"],
        )
        macro_df["value"] = macro_df["value"].astype("float64")

        # PR-A15 dedup safeguard.
        _raw_macro_rows = len(macro_df)
        macro_df = (
            macro_df
            .groupby(["obs_date", "series_id"], as_index=False)["value"]
            .mean()
        )
        if len(macro_df) != _raw_macro_rows:
            logger.warning(
                "factor_returns_input_duplicates_deduped",
                source="macro_data",
                raw_rows=_raw_macro_rows,
                deduped_rows=len(macro_df),
                dropped=_raw_macro_rows - len(macro_df),
            )

        macro_levels = macro_df.pivot(
            index="obs_date", columns="series_id", values="value",
        )
        # PR-Q15 Fix 1: forward-fill macro LEVELS before computing returns.
        macro_levels = macro_levels.ffill(limit=_FACTOR_FFILL_LIMIT)
        # PR-Q15 Fix 6: simple returns (pct_change), not log returns.
        # PR-Q92: fill_method=None (pad default deprecated in pandas 2.x).
        # Levels are already ffill-ed above, so we don't want pct_change
        # to fill again — pass None explicitly to silence the warning.
        macro_returns = macro_levels.pct_change(fill_method=None)
    else:
        macro_returns = pd.DataFrame()

    # ── 3. Combine benchmark + macro returns ──────────────────────────────
    # PR-Q15 Fix 4 (subsumed by Fix 1): no ffill on combined returns.
    # Level-side ffill already handled market closures.
    combined = pd.concat([bench_returns, macro_returns], axis=1)
    combined.index = pd.to_datetime(combined.index)
    combined = combined.dropna(how="all")

    # Align authoritative mask to combined index for spread factor masking.
    if not authoritative_bench.empty:
        auth = authoritative_bench.copy()
        auth.index = pd.to_datetime(auth.index)
        auth = auth.reindex(combined.index, fill_value=False)
    else:
        auth = pd.DataFrame(index=combined.index)

    # ── 4. Build factor series ────────────────────────────────────────────
    factors = pd.DataFrame(index=combined.index)
    skipped: list[dict[str, str]] = []

    # PR-Q35 F06: record OAS-filtered tickers for downstream degraded propagation.
    # These appear in factors.attrs["skipped"] at line 327, which feeds into
    # FundamentalFactorFit.factors_skipped via the caller chain.
    if _oas_filtered:
        for ticker in sorted(set(_oas_filtered)):
            skipped.append({
                "name": f"oas_{ticker.lower()}",
                "reason": "OAS level is not a total return; filtered defensively (PR-Q35 F06)",
            })

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

    # 3. Credit spread (HYG - IEF) — PR-Q15 Fix 5: authoritative-only
    if "HYG" in combined.columns and "IEF" in combined.columns:
        valid_credit = (
            auth.get("HYG", pd.Series(False, index=combined.index))
            & auth.get("IEF", pd.Series(False, index=combined.index))
        )
        factors["credit"] = (
            (combined["HYG"] - combined["IEF"]).where(valid_credit, np.nan)
        )
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

    # 6. Size (IWM - SPY) — PR-Q15 Fix 5: authoritative-only
    if "IWM" in combined.columns and "SPY" in combined.columns:
        valid_size = (
            auth.get("IWM", pd.Series(False, index=combined.index))
            & auth.get("SPY", pd.Series(False, index=combined.index))
        )
        factors["size"] = (
            (combined["IWM"] - combined["SPY"]).where(valid_size, np.nan)
        )
    else:
        skipped.append({"name": "size", "reason": "IWM or SPY absent from benchmark_nav"})

    # 7. Value (IWD - IWF) — PR-Q15 Fix 5: authoritative-only
    if "IWD" in combined.columns and "IWF" in combined.columns:
        valid_value = (
            auth.get("IWD", pd.Series(False, index=combined.index))
            & auth.get("IWF", pd.Series(False, index=combined.index))
        )
        factors["value"] = (
            (combined["IWD"] - combined["IWF"]).where(valid_value, np.nan)
        )
    else:
        reason = (
            "IWF absent from benchmark_nav"
            if "IWF" not in combined.columns
            else "IWD absent"
        )
        skipped.append({"name": "value", "reason": f"Value factor skipped: {reason}"})

    # 8. International (EFA - SPY) — PR-Q15 Fix 5: authoritative-only
    if "EFA" in combined.columns and "SPY" in combined.columns:
        valid_intl = (
            auth.get("EFA", pd.Series(False, index=combined.index))
            & auth.get("SPY", pd.Series(False, index=combined.index))
        )
        factors["international"] = (
            (combined["EFA"] - combined["SPY"]).where(valid_intl, np.nan)
        )
    else:
        reason = (
            "EFA absent from benchmark_nav"
            if "EFA" not in combined.columns
            else "SPY absent"
        )
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
                allow_global=True,
            )
        except Exception as audit_err:
            # Audit failure must not break estimation — log and continue
            logger.warning(
                "factor_skipped_audit_failed",
                factor=s["name"],
                err=str(audit_err),
            )

    factors.attrs["skipped"] = skipped

    # ── 5. Forward-fill factor gaps, audit, return ────────────────────────
    filled = factors.ffill(limit=_FACTOR_FFILL_LIMIT)
    dropped_mask = filled.isna().any(axis=1)
    dropped_dates = filled.index[dropped_mask]

    # PR-Q15 Fix 7: dropna(how="all") preserves dates where at least one
    # factor has data.  fit_fundamental_loadings handles per-row NaN.
    cleaned = filled.dropna(how="all")

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
                allow_global=True,
            )
        except Exception as audit_err:
            logger.warning("factor_data_gap_audit_failed", err=str(audit_err))

    # Log partial-history factors for observability.
    if not cleaned.empty:
        factor_first_obs = {}
        for col in cleaned.columns:
            first_valid = cleaned[col].first_valid_index()
            if first_valid is not None:
                factor_first_obs[col] = str(first_valid)
        if factor_first_obs:
            logger.info(
                "factor_panel_first_observations",
                factor_first_obs=factor_first_obs,
                panel_start=str(cleaned.index[0]),
                panel_end=str(cleaned.index[-1]),
            )

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
    # PR-Q29: top-level degraded signal for silent-corruption prevention
    degraded: bool = False
    degraded_reason: str | None = None


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
    alphas_per_fund: npt.NDArray[np.float64] | None = None  # PR-Q15 Fix 3
    # PR-Q29: top-level degraded signal for silent-corruption prevention
    degraded: bool = False
    degraded_reason: str | None = None


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
    factors_skipped: list[dict[str, str]] | None = None,
) -> FundamentalFactorFit:
    """Per-fund weighted OLS on 5Y daily returns with EWMA weights.

    PR-Q15 Fix 3: includes an intercept column so fund alpha does not bias
    factor loadings. ``alphas_per_fund`` is exposed on the returned fit.

    PR-Q15 Fix 2: EWMA covariance is computed directly from normalized
    weights and demeaned factor returns.  Ledoit-Wolf shrinkage intensity
    is derived from the *unweighted* sample (LW's iid assumption), then
    applied to the EWMA covariance via the standard convex combination.

    PR-Q15 Fix 7: rows with NaN in factor_returns or fund_returns_matrix
    are dropped before regression.

    PR-Q15 Fix 8: residual variance uses regression-aware DOF (T - K - 1)
    instead of sample DOF (T - 1).

    PR-Q15 Fix 10: rank deficiency in the design matrix is detected and
    logged (warning, not error).
    """
    T, N = fund_returns_matrix.shape
    K = factor_returns.shape[1]
    if len(factor_names) != K:
        raise ValueError(
            f"factor_names length {len(factor_names)} != factor_returns columns {K}"
        )

    # PR-Q15 Fix 7: drop rows with NaN before regression.
    valid_rows = (
        np.isfinite(factor_returns).all(axis=1)
        & np.isfinite(fund_returns_matrix).all(axis=1)
    )
    n_valid = int(valid_rows.sum())
    if n_valid < K + 2:
        raise ValueError(
            f"Too few valid observations after NaN removal: {n_valid}, need at least {K + 2}"
        )
    if n_valid < T:
        logger.info(
            "factor_loadings_nan_rows_dropped",
            T_original=int(T),
            T_valid=n_valid,
            dropped=int(T - n_valid),
        )
        factor_returns = factor_returns[valid_rows]
        fund_returns_matrix = fund_returns_matrix[valid_rows]
        T = n_valid

    # EWMA weights: lambda^(T-t)
    weights = ewma_lambda ** np.arange(T - 1, -1, -1)
    w_sqrt = np.sqrt(weights).reshape(-1, 1)

    # PR-Q15 Fix 3: add intercept column so alpha doesn't bias factor loadings.
    intercept_col = np.ones((T, 1))
    X_with_intercept = np.hstack([intercept_col, factor_returns])
    X_w = X_with_intercept * w_sqrt
    Y_w = fund_returns_matrix * w_sqrt

    # Fit [alpha; beta]: ((K+1) x N) — weighted OLS via lstsq.
    # PR-Q15 Fix 10: capture rank and singular values for rank-deficiency check.
    beta_with_alpha, _, rank, sv = np.linalg.lstsq(X_w, Y_w, rcond=None)
    expected_rank = X_w.shape[1]
    if rank < expected_rank:
        logger.warning(
            "factor_design_rank_deficient",
            rank=int(rank),
            expected_rank=int(expected_rank),
            smallest_singular=float(sv[-1]) if len(sv) else None,
            condition_number=float(sv[0] / sv[-1]) if len(sv) and sv[-1] > 0 else None,
        )

    # beta_with_alpha shape: (K+1, N).  Row 0 is alpha, rows 1..K are loadings.
    alphas_per_fund = beta_with_alpha[0, :]     # shape (N,)
    loadings = beta_with_alpha[1:, :].T         # shape (N, K)

    # ── PR-Q34 F08: EWMA covariance (LW scaled-identity shrinkage removed) ──
    # Previous LW target (np.trace/K * np.eye(K)) systematically biased factor
    # covariance toward zero cross-correlation. For K≤8 factors and T=1260
    # (5Y daily), EWMA covariance is well-conditioned (T >> K), so shrinkage
    # is unnecessary. Ref: Wave 6 Session 03 F08, audit-validation-session03.md.
    # Cross-ref: correlation_regime_service.py:96-102 documents the same
    # anti-pattern (LW destroys correlation structure).
    shrinkage_lambda: float | None = None  # always None post-Q34 F08
    w_norm = weights / weights.sum()
    weighted_mean = (factor_returns * w_norm[:, None]).sum(axis=0)
    centered_f = factor_returns - weighted_mean
    factor_cov = (
        (centered_f * w_norm[:, None]).T @ centered_f
    ) * TRADING_DAYS_PER_YEAR

    # Residuals accounting for intercept (PR-Q15 Fix 3).
    X_unweighted = np.hstack([np.ones((T, 1)), factor_returns])
    predicted = X_unweighted @ beta_with_alpha
    residual_series = fund_returns_matrix - predicted

    # PR-Q34 F07: weighted SSE matching EWMA WLS regression (line 491).
    # Unweighted SSE inflates residuals where β was optimized to fit recent
    # data (EWMA-driven β shift produces large old-period residuals that the
    # WLS regression intentionally down-weighted). For 5Y daily with λ=0.97
    # and a recent β shift, unweighted SSE was ~28x the weighted analogue.
    # Ref: Wave 6 Session 03 F07, audit-validation-session03.md.
    dof = max(T - K - 1, 1)  # PR-Q15 Fix 8 preserved
    weighted_sse = np.sum(w_norm[:, None] * (residual_series ** 2), axis=0) * T
    residual_variance = (weighted_sse / dof) * TRADING_DAYS_PER_YEAR

    # A.10 — guard against zero-variance funds (constant returns)
    total_var = np.var(fund_returns_matrix, axis=0, ddof=1)
    r_squared_per_fund: npt.NDArray[np.float64] = np.zeros(N, dtype=np.float64)
    nonzero = total_var > 1e-16
    if nonzero.any():
        r_squared_per_fund[nonzero] = 1.0 - (
            residual_variance[nonzero] / (total_var[nonzero] * TRADING_DAYS_PER_YEAR)
        )
    np.clip(r_squared_per_fund, 0.0, 1.0, out=r_squared_per_fund)

    # PR-Q29: propagate degraded signal when factors were skipped
    skipped = factors_skipped or []
    _degraded = bool(skipped)
    _degraded_reason = (
        f"factor_model_partial_fit: missing {len(skipped)} factor(s): "
        + ", ".join(s.get("name", "<unknown>") for s in skipped)
    ) if _degraded else None

    return FundamentalFactorFit(
        loadings=np.asarray(loadings, dtype=np.float64),
        factor_cov=np.asarray(factor_cov, dtype=np.float64),
        residual_variance=np.asarray(residual_variance, dtype=np.float64),
        factor_names=list(factor_names),
        residual_series=np.asarray(residual_series, dtype=np.float64),
        r_squared_per_fund=r_squared_per_fund,
        shrinkage_lambda=shrinkage_lambda,
        factors_skipped=skipped,
        alphas_per_fund=np.asarray(alphas_per_fund, dtype=np.float64),
        degraded=_degraded,
        degraded_reason=_degraded_reason,
    )


def assemble_factor_covariance(
    fit: FundamentalFactorFit,
    *,
    kappa_target: float = 1e4,
) -> npt.NDArray[np.float64]:
    """Returns Σ = B · F · B' + diag(D) with PSD + conditioning enforcement.

    Accepts only ``FundamentalFactorFit`` — never ``PCADiagnostic`` (the
    residual diagnostic lives in ``factor_model_pca`` and has no bearing
    on covariance assembly). Enforced at the type level; see
    ``tests/quant_engine/test_assemble_factor_covariance_types.py``.

    PR-Q124: eigenvalue floor is now ``max_eigval / kappa_target`` so the
    assembled matrix stays within the recoverable conditioning band.  The
    previous floor (``1e-8 * trace / N``) was orders of magnitude too small
    for N >> K factor models (159 funds, 8 factors) where many eigenvalues
    derive solely from residual variance — pathological κ > 1e6 made the
    optimizer cascade unreachable even when the underlying estimates were
    reasonable (κ ~48 K on an adjacent run).
    """
    B = fit.loadings
    F = fit.factor_cov
    D_diag = fit.residual_variance

    sigma = (B @ F @ B.T) + np.diag(D_diag)
    sigma = (sigma + sigma.T) / 2

    eigvals, eigvecs = np.linalg.eigh(sigma)
    max_eigval = float(eigvals.max())
    clamp_val = max(1e-10, max_eigval / kappa_target)

    if eigvals.min() < clamp_val:
        kappa_before = max_eigval / max(float(eigvals.min()), 1e-16)
        eigvals = np.maximum(eigvals, clamp_val)
        sigma = eigvecs @ np.diag(eigvals) @ eigvecs.T
        kappa_after = max_eigval / float(eigvals.min())
        logger.info(
            "factor_covariance_eigenvalue_regularized",
            n_funds=sigma.shape[0],
            kappa_before=round(kappa_before, 1),
            kappa_after=round(kappa_after, 1),
            kappa_target=kappa_target,
            eigenvalue_floor=float(clamp_val),
        )

    return np.asarray(sigma, dtype=np.float64)


def compute_factor_conditioning_meta(
    fit: FundamentalFactorFit,
    *,
    kappa_target: float = 1e4,
) -> dict[str, Any]:
    """Return conditioning metadata for the factor covariance assembly.

    PR-Q146 (C-09): mirrors the eigenvalue regularization logic in
    ``assemble_factor_covariance`` but only computes the metadata dict
    (no matrix reconstruction).  Called by the executor path to persist
    conditioning diagnostics into ``run.statistical_inputs``.
    """
    B = fit.loadings
    F = fit.factor_cov
    D_diag = fit.residual_variance

    sigma = (B @ F @ B.T) + np.diag(D_diag)
    sigma = (sigma + sigma.T) / 2

    eigvals = np.linalg.eigvalsh(sigma)
    max_eigval = float(eigvals.max())
    clamp_val = max(1e-10, max_eigval / kappa_target)

    n_clamped = int((eigvals < clamp_val).sum())
    kappa_before = max_eigval / max(float(eigvals.min()), 1e-16)
    if n_clamped > 0:
        clamped_eigvals = np.maximum(eigvals, clamp_val)
        kappa_after = max_eigval / float(clamped_eigvals.min())
    else:
        kappa_after = kappa_before

    return {
        "kappa_before": round(kappa_before, 1),
        "kappa_after": round(kappa_after, 1),
        "eigenvalue_floor": float(clamp_val),
        "n_clamped": n_clamped,
    }


def decompose_factors(
    returns_matrix: npt.NDArray[np.float64],
    macro_proxies: dict[str, npt.NDArray[np.float64] | pd.Series] | None,
    portfolio_weights: npt.NDArray[np.float64],
    n_factors: int = 3,
    dates: pd.DatetimeIndex | None = None,
) -> FactorModelResult:
    """Decompose fund returns into PCA factors and project portfolio weights.

    PR-Q15 Fix 12: raises ``ValueError`` if T < 3 (not enough observations
    for meaningful PCA).

    PR-Q15 Fix 13: enforces deterministic sign convention on PCA loadings
    (largest-absolute-magnitude loading per component is positive).

    PR-Q15 Fix 11: residual is computed from *centered* portfolio returns
    so it is mean-zero by construction (pure idiosyncratic shocks).

    Parameters
    ----------
    dates : pd.DatetimeIndex, optional
        Date index for ``returns_matrix`` rows.  When provided together
        with date-indexed ``pd.Series`` in *macro_proxies*, factor–proxy
        correlation uses date-aligned inner join (PR-Q15 Fix 14).
    """
    T, N = returns_matrix.shape

    # PR-Q15 Fix 12: guard against degenerate panels.
    if T < 3 or N < 1:
        raise ValueError(
            f"PCA requires at least 3 observations and 1 fund; got T={T}, N={N}"
        )

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

    # PR-Q15 Fix 13: enforce deterministic sign convention — for each
    # component, flip so the largest-absolute-magnitude loading is positive.
    for k in range(min(n_factors, Vt.shape[0])):
        largest_abs_idx = int(np.argmax(np.abs(Vt[k])))
        if Vt[k, largest_abs_idx] < 0:
            Vt[k] = -Vt[k]

    factor_loadings = Vt[:n_factors].T  # (N x K)
    factor_returns = centered @ factor_loadings  # (T x K)

    total_var = float(np.sum(S**2))
    explained_var = float(np.sum(S[:n_factors] ** 2))
    r_squared = explained_var / total_var if total_var > 0 else 0.0

    factor_labels = _label_factors(
        factor_returns, macro_proxies, n_factors, factor_index=dates,
    )

    exposures = portfolio_weights @ factor_loadings
    portfolio_factor_exposures = {
        label: round(float(exposures[k]), 6) for k, label in enumerate(factor_labels)
    }

    # PR-Q15 Fix 11: use CENTERED portfolio returns for the residual so
    # it is mean-zero by construction (the factor component is already
    # mean-zero because factor_returns are derived from centered data).
    centered_portfolio_returns = centered @ portfolio_weights
    factor_component = factor_returns @ exposures
    residual_returns = centered_portfolio_returns - factor_component

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
    macro_proxies: dict[str, npt.NDArray[np.float64] | pd.Series] | None,
    n_factors: int,
    *,
    factor_index: pd.DatetimeIndex | None = None,
) -> list[str]:
    """Assign interpretive labels to PCA factors via macro proxy correlations.

    PR-Q15 Fix 14: when *factor_index* is provided and a proxy is a
    ``pd.Series`` with a date index, correlation is computed on the
    date-aligned inner join (not length-aligned tail slicing).
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

            # PR-Q15 Fix 14: date-aligned correlation when dates available.
            if (
                factor_index is not None
                and isinstance(proxy_series, pd.Series)
                and hasattr(proxy_series.index, 'dtype')
            ):
                f_series = pd.Series(factor_k, index=factor_index)
                f_aligned, p_aligned = f_series.align(proxy_series, join="inner")
                if len(f_aligned) < 20:
                    continue
                corr = _safe_correlation(f_aligned.values, p_aligned.values)
            else:
                # Legacy length-aligned path for ndarray proxies.
                min_len = min(len(factor_k), len(proxy_series))
                if min_len < 20:
                    continue
                f_slice = factor_k[-min_len:]
                p_slice = (
                    proxy_series.values[-min_len:]
                    if isinstance(proxy_series, pd.Series)
                    else proxy_series[-min_len:]
                )
                corr = _safe_correlation(f_slice, p_slice)

            # PR-Q15 Fix 9: _safe_correlation may return NaN — guard here.
            if not np.isfinite(corr):
                continue
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
    """Compute Pearson correlation with NaN/zero-variance guards.

    PR-Q15 Fix 9: returns ``NaN`` when correlation is undefined (zero
    variance, all NaN, fewer than 2 finite paired observations).
    Callers must check ``np.isfinite()`` before using the result.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    valid = np.isfinite(a) & np.isfinite(b)
    if valid.sum() < 2:
        return float("nan")
    a_v, b_v = a[valid], b[valid]
    if np.std(a_v) < 1e-12 or np.std(b_v) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a_v, b_v)[0, 1])


def compute_factor_contributions(
    factor_result: FactorModelResult,
) -> FactorContributionResult:
    """Decompose portfolio variance into factor (systematic) vs specific.

    PR-Q15 Fix 15: uses full factor covariance (quadratic form) instead of
    diagonal-only approximation.  Per-factor contributions via Euler
    decomposition: contribution_k = exposure_k * (Σ_F · e)_k.

    PR-Q15 Fix 16: R² is portfolio-specific (systematic_var / total_var),
    not the panel-level eigenvalue ratio.
    """
    factor_returns = factor_result.factor_returns
    residual = factor_result.residual_returns
    labels = factor_result.factor_labels

    exposures = np.array(
        [factor_result.portfolio_factor_exposures[label] for label in labels]
    )

    # PR-Q15 Fix 15: full quadratic form via factor covariance.
    factor_cov = np.cov(factor_returns, rowvar=False, ddof=1)
    # Handle single-factor edge case (np.cov returns scalar)
    if factor_cov.ndim == 0:
        factor_cov = factor_cov.reshape(1, 1)

    systematic_var = float(exposures @ factor_cov @ exposures)
    specific_var = float(np.var(residual, ddof=1))
    total_var = systematic_var + specific_var

    if total_var < 1e-16:
        return FactorContributionResult(
            systematic_risk_pct=0.0,
            specific_risk_pct=0.0,
            factor_contributions=[],
            r_squared=0.0,
        )

    # Per-factor marginal contribution via Euler decomposition:
    # contribution_k = exposure_k * (factor_cov @ exposures)_k
    # Sum equals systematic_var by construction.
    factor_marginals = exposures * (factor_cov @ exposures)

    factor_contributions: list[dict[str, object]] = [
        {
            "factor_label": labels[k],
            "pct_contribution": round(float(factor_marginals[k] / total_var * 100), 2),
        }
        for k in range(len(labels))
    ]

    return FactorContributionResult(
        systematic_risk_pct=round(systematic_var / total_var * 100, 2),
        specific_risk_pct=round(specific_var / total_var * 100, 2),
        factor_contributions=factor_contributions,
        # PR-Q15 Fix 16: portfolio-specific R² from the variance decomposition.
        r_squared=round(systematic_var / total_var, 6) if total_var > 0 else 0.0,
    )
