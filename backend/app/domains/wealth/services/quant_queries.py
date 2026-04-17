"""Wealth-layer data access for quant_engine services.

Functions in this module were extracted from quant_engine/ to enforce
vertical isolation: quant_engine/ must not import app.domains.wealth.

Each function here queries wealth ORM models and passes plain data to
pure computation functions in quant_engine/.

Import-linter enforces the boundary: quant_engine → app.domains.wealth
is forbidden; app.domains.wealth → quant_engine is allowed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

if TYPE_CHECKING:
    from quant_engine.drift_service import DriftReport
    from quant_engine.peer_comparison_service import PeerComparison, PeerRank
    from quant_engine.rebalance_service import CascadeResult

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.wealth.models.allocation import StrategicAllocation, TacticalPosition
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.domains.wealth.models.rebalance import RebalanceEvent
from app.domains.wealth.models.risk import FundRiskMetrics
from quant_engine.factor_model_pca import compute_residual_pca
from quant_engine.factor_model_service import (
    assemble_factor_covariance,
    build_fundamental_factor_returns,
    fit_fundamental_loadings,
)

logger = structlog.get_logger()


# ── Backtest queries ─────────────────────────────────────────────────


async def fetch_returns_matrix(
    db: AsyncSession,
    block_ids: list[str],
    lookback_days: int = 756,
) -> tuple[np.ndarray, list[str], list[float]]:
    """Fetch aligned daily returns matrix for walk-forward backtesting.

    Returns:
        (returns_matrix, fund_ids, equal_weights)
        - returns_matrix: T×N float64 array (only dates where all funds have data)
        - fund_ids: list of fund UUID strings (columns)
        - equal_weights: 1/N equal-weight portfolio weights

    Raises:
        ValueError: If <2 blocks have data or <120 aligned dates.

    """
    start_date = date.today() - timedelta(days=int(lookback_days * 1.5))

    # Pick one approved instrument per block from instruments_org (org-scoped via RLS).
    # Falls back to deprecated funds_universe if instruments_org is empty.
    io_stmt = (
        select(InstrumentOrg.block_id, InstrumentOrg.instrument_id)
        .where(
            InstrumentOrg.block_id.in_(block_ids),
        )
        .distinct(InstrumentOrg.block_id)
        .order_by(InstrumentOrg.block_id, InstrumentOrg.selected_at.desc())
    )
    io_result = await db.execute(io_stmt)
    block_instruments = {row.block_id: row.instrument_id for row in io_result.all()}

    # Legacy fallback: funds_universe (for orgs that haven't migrated yet)
    if not block_instruments:
        funds_stmt = (
            select(Fund)
            .where(Fund.block_id.in_(block_ids), Fund.is_active == True, Fund.ticker.is_not(None))
            .distinct(Fund.block_id)
            .order_by(Fund.block_id, Fund.name)
        )
        funds_result = await db.execute(funds_stmt)
        block_instruments = {f.block_id: f.fund_id for f in funds_result.scalars().all()}

    if not block_instruments:
        raise ValueError("No active funds found for the requested blocks")

    available = [bid for bid in block_ids if bid in block_instruments]
    fund_uuids = [block_instruments[bid] for bid in available]
    fund_ids = [str(block_instruments[bid]) for bid in available]

    if len(fund_ids) < 2:
        raise ValueError(f"Need ≥2 blocks with data, found {len(fund_ids)}")

    ret_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_(fund_uuids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    ret_result = await db.execute(ret_stmt)

    grouped: dict[str, dict[str, float]] = defaultdict(dict)
    for fid, nav_date, ret in ret_result.all():
        grouped[str(fid)][str(nav_date)] = float(ret)

    matrix, common_dates = _align_returns_with_ffill(grouped, fund_ids)

    if len(common_dates) < 120:
        raise ValueError(
            f"Insufficient aligned return data: {len(common_dates)} common dates (need ≥120)",
        )

    N = len(fund_ids)
    equal_weights = [1.0 / N] * N
    return matrix, fund_ids, equal_weights


# ── Optimizer queries ────────────────────────────────────────────────

TRADING_DAYS_PER_YEAR = 252
MIN_OBSERVATIONS = 120
_FFILL_LIMIT = 3  # max business days to forward-fill a stale NAV

# ── Phase A construction engine constants ────────────────────────────
COV_LOOKBACK_DAYS_5Y = 1260
HIGHER_MOMENTS_WINDOW_3Y = 756
EWMA_LAMBDA_DEFAULT = 0.97
RISK_AVERSION_INSTITUTIONAL_DEFAULT = 2.5
# PR-A9 three-tier ladder — recalibrated from PR-A1 aspirational bounds
# based on empirical PR-A8 smoke evidence (3 portfolios: κ=2.4e4-3e4 post-dedup).
# Academic reality: for sample cov with T/N ≈ 10, κ in 1e4-1e5 is normal; the
# original 1e4 error threshold fired spuriously on well-behaved institutional
# universes. The fallback tier hands off to PR-A3 factor covariance (PSD-clamped)
# when sample Σ is too collinear but not pathologically singular.
KAPPA_WARN_THRESHOLD = 1e4        # proceed with sample Σ, emit warning
KAPPA_FALLBACK_THRESHOLD = 5e4    # switch to factor covariance if available
KAPPA_ERROR_THRESHOLD = 1e6       # raise — truly pathological rank deficiency
# Survivorship bias estimate (bps/year) — see design doc 2026-04-14
SURVIVORSHIP_BIAS_BPS_RANGE = (50, 150)


class IllConditionedCovarianceError(Exception):
    """Raised when κ(Σ) >= KAPPA_ERROR_THRESHOLD (1e6) — pathological rank deficiency, not recoverable.

    PR-A9 three-tier ladder: the two intermediate thresholds (1e4 WARN, 5e4 FALLBACK)
    are recoverable and do NOT raise — they either warn-and-proceed with sample Σ
    or swap in the PR-A3 factor-model covariance. This error fires only when both
    covariance paths are ill-conditioned or no fallback is available.
    """

    def __init__(
        self,
        condition_number: float,
        n_funds: int,
        n_obs: int,
        worst_eigenvalues: list[float] | None = None,
        message: str | None = None,
    ) -> None:
        self.condition_number = condition_number
        self.n_funds = n_funds
        self.n_obs = n_obs
        self.worst_eigenvalues = worst_eigenvalues or []
        detail = (
            f"κ(Σ)={condition_number:.3e} exceeds error threshold ({KAPPA_ERROR_THRESHOLD:.0e}); "
            f"N={n_funds}, T={n_obs}"
        )
        if self.worst_eigenvalues:
            detail += f", worst eigenvalues={[f'{v:.3e}' for v in self.worst_eigenvalues]}"
        super().__init__(message or detail)


@dataclass(frozen=True)
class FundLevelInputs:
    """Frozen dataclass returned by compute_fund_level_inputs() (Phase A engine).

    All arrays are numpy float64. Frozen to be thread-safe across async boundaries.
    Dates are pure Python dates. instrument IDs are strings.
    """

    cov_matrix: npt.NDArray[np.float64]
    expected_returns: dict[str, float]
    available_ids: list[str]
    # PR-A12 — raw scenario matrix (T, N) driving the Rockafellar-Uryasev
    # CVaR LP. Same window + forward-fill used for Σ, trimmed to
    # ``cov_lookback_days``. Trading-day rows where every fund is NaN are
    # dropped upstream. T_effective >= 252 is enforced; 252 <= T < 504
    # emits a warning (short-history universe).
    returns_scenarios: npt.NDArray[np.float64]
    skewness: npt.NDArray[np.float64]
    excess_kurtosis: npt.NDArray[np.float64]
    condition_number: float
    factor_loadings: npt.NDArray[np.float64] | None
    factor_names: list[str] | None
    residual_variance: npt.NDArray[np.float64] | None
    prior_weights_used: dict[str, float]
    n_funds_by_history: dict[str, int]
    regime_probability_at_calc: float | None
    used_return_type: str
    lookback_start_date: date
    lookback_end_date: date
    # Provenance fields consumed by PR-A4 inputs_metadata JSONB
    risk_aversion_gamma: float = RISK_AVERSION_INSTITUTIONAL_DEFAULT
    risk_aversion_source: str = "institutional_default"
    kappa_warning_triggered: bool = False
    kappa_error_triggered: bool = False
    funds_excluded: tuple[tuple[str, str], ...] = ()  # (fund_id, reason) pairs
    # A.2 — PR-A3 spec §7: persist factor model + residual PCA provenance.
    # Shape::
    #     {
    #         "factor_model": {
    #             "k_factors": 8,
    #             "k_factors_effective": int,
    #             "factors_skipped": [str, ...],
    #             "r_squared_per_fund": {fund_id: float},
    #             "kappa_factor_cov": float,
    #             "shrinkage_lambda": float | None,
    #         },
    #         "residual_pca": {
    #             "n_components": int,
    #             "cumulative_variance": list[float],
    #             "top_eigenvalue_share": float,
    #         },
    #     }
    inputs_metadata: dict[str, Any] = field(default_factory=dict)


def _align_returns_with_ffill(
    fund_returns: dict[str, dict],
    fund_ids: list[str],
) -> tuple[np.ndarray, list]:
    """Build aligned T×N returns matrix with forward-fill before intersection.

    Steps:
        1. Construct a DataFrame (dates × funds) from the sparse dicts.
        2. Forward-fill each fund column up to *_FFILL_LIMIT* rows (T-1 to T-3
           projection — prevents stale NAV from propagating further).
        3. Drop rows that still contain NaN (strict intersection after fill).

    Returns:
        (returns_matrix, common_dates) — both numpy-friendly.

    The caller is responsible for checking len(common_dates) >= MIN_OBSERVATIONS.
    """
    # Collect the full date universe across all funds
    all_dates: set = set()
    for fid in fund_ids:
        all_dates.update(fund_returns[fid].keys())

    if not all_dates:
        return np.empty((0, len(fund_ids)), dtype=np.float64), []

    sorted_dates = sorted(all_dates)

    # Build DataFrame: rows=dates, cols=fund_ids, missing = NaN
    data = {fid: [fund_returns[fid].get(d) for d in sorted_dates] for fid in fund_ids}
    df = pd.DataFrame(data, index=sorted_dates, dtype=np.float64)

    # Forward-fill with limit — propagates last known return for up to 3 days
    df = df.ffill(limit=_FFILL_LIMIT)

    # Drop any row that still has gaps (strict intersection post-fill)
    df = df.dropna()

    if df.empty:
        return np.empty((0, len(fund_ids)), dtype=np.float64), []

    returns_matrix = df.to_numpy(dtype=np.float64)
    common_dates = list(df.index)
    return returns_matrix, common_dates


async def compute_inputs_from_nav(
    db: AsyncSession,
    block_ids: list[str],
    lookback_days: int = TRADING_DAYS_PER_YEAR,
    as_of_date: date | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    """Compute covariance matrix and expected returns from NAV data.

    Returns:
        (annualized_cov_matrix, expected_returns_dict)

    Raises:
        ValueError: If insufficient aligned data (<120 trading days).

    """
    if as_of_date is None:
        as_of_date = date.today()

    start_date = as_of_date - timedelta(days=int(lookback_days * 1.5))

    # Pick one approved instrument per block from instruments_org (org-scoped via RLS).
    io_stmt = (
        select(InstrumentOrg.block_id, InstrumentOrg.instrument_id)
        .where(
            InstrumentOrg.block_id.in_(block_ids),
        )
        .distinct(InstrumentOrg.block_id)
        .order_by(InstrumentOrg.block_id, InstrumentOrg.selected_at.desc())
    )
    io_result = await db.execute(io_stmt)
    block_instruments = {row.block_id: row.instrument_id for row in io_result.all()}

    # Legacy fallback: funds_universe
    if not block_instruments:
        funds_stmt = (
            select(Fund)
            .where(Fund.block_id.in_(block_ids), Fund.is_active == True, Fund.ticker.is_not(None))
            .distinct(Fund.block_id)
            .order_by(Fund.block_id, Fund.name)
        )
        funds_result = await db.execute(funds_stmt)
        block_instruments = {f.block_id: f.fund_id for f in funds_result.scalars().all()}

    if not block_instruments:
        raise ValueError("No active funds found for the requested blocks")

    available_blocks = [bid for bid in block_ids if bid in block_instruments]
    if len(available_blocks) < 2:
        raise ValueError(f"Need at least 2 blocks with data, found {len(available_blocks)}")

    fund_ids = [block_instruments[bid] for bid in available_blocks]
    ret_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= as_of_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    ret_result = await db.execute(ret_stmt)

    fund_returns: dict[str, dict[date, float]] = defaultdict(dict)
    for instrument_id, nav_date, return_1d in ret_result.all():
        fund_returns[str(instrument_id)][nav_date] = float(return_1d)

    fund_id_strs = [str(block_instruments[bid]) for bid in available_blocks]

    if not fund_returns:
        raise ValueError("No return data found for any block")

    returns_matrix, common_dates = _align_returns_with_ffill(fund_returns, fund_id_strs)

    if len(common_dates) < MIN_OBSERVATIONS:
        raise ValueError(
            f"Insufficient aligned data: {len(common_dates)} trading days "
            f"(minimum: {MIN_OBSERVATIONS}). Some funds may have sparse history.",
        )

    daily_cov = _apply_ledoit_wolf(returns_matrix)
    annual_cov = daily_cov * TRADING_DAYS_PER_YEAR

    eigenvalues = np.linalg.eigvalsh(annual_cov)
    if eigenvalues.min() < -1e-10:
        eigvals, eigvecs = np.linalg.eigh(annual_cov)
        eigvals = np.maximum(eigvals, 1e-10)
        annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
        logger.info("Covariance matrix adjusted for PSD", min_eigenvalue=float(eigenvalues.min()))

    daily_means = returns_matrix.mean(axis=0)
    annual_returns = daily_means * TRADING_DAYS_PER_YEAR
    expected_returns = {bid: float(annual_returns[i]) for i, bid in enumerate(available_blocks)}

    logger.info(
        "Computed covariance and expected returns",
        blocks=len(available_blocks),
        observations=len(common_dates),
        lookback_days=lookback_days,
    )

    return annual_cov, expected_returns


def _apply_ledoit_wolf(
    returns_matrix: npt.NDArray[np.float64],
    market_index: npt.NDArray[np.float64] | None = None,
) -> npt.NDArray[np.float64]:
    """Apply Ledoit-Wolf shrinkage to compute covariance from returns.

    Retargeted in PR-A3 from constant-correlation to single-index shrinkage.
    If market_index (T,) is not provided, uses the cross-sectional mean of
    returns_matrix as the proxy index.

    Input: (T x N) returns matrix. Returns: (N x N) shrinkage covariance.
    """
    T, N = returns_matrix.shape
    if T < 2:
        return np.asarray(np.cov(returns_matrix, rowvar=False), dtype=np.float64)

    # 1. Sample covariance
    sample_cov = np.asarray(np.cov(returns_matrix, rowvar=False), dtype=np.float64)

    # 2. Target covariance (Single-Index Model)
    # R_i = alpha_i + beta_i * R_m + epsilon_i
    if market_index is None:
        # Cross-sectional mean as proxy index
        market_index = returns_matrix.mean(axis=1)

    # Ensure market_index is (T, 1) for broadcasting
    m = market_index.reshape(-1, 1)
    var_m = np.var(m, ddof=1)
    if var_m < 1e-12:
        # Fallback to constant correlation if index has no variance
        try:
            from sklearn.covariance import ledoit_wolf
            _, alpha = ledoit_wolf(returns_matrix)
            shrunk = sample_cov * (1 - alpha) + np.diag(np.diag(sample_cov)) * alpha
            return np.asarray(shrunk, dtype=np.float64)
        except Exception:
            return sample_cov

    # Compute betas: beta = cov(R_i, R_m) / var(R_m)
    # Cov(R, R_m) is (N x 1)
    cov_rm = (np.dot(returns_matrix.T, m) / (T - 1)) - (returns_matrix.mean(axis=0).reshape(-1, 1) * m.mean())
    betas = cov_rm / var_m

    # Target: Phi = beta * beta^T * var_m + diag(sigma_epsilon^2)
    # sigma_epsilon^2 = var(R_i) - beta_i^2 * var_m
    target_cov = (betas @ betas.T) * var_m
    residual_vars = np.var(returns_matrix, axis=0, ddof=1) - (betas.flatten()**2 * var_m)
    np.fill_diagonal(target_cov, np.maximum(residual_vars, 0.0) + np.diag(target_cov))

    # 3. Compute shrinkage intensity (delta)
    # Using the simplified Ledoit-Wolf (2003) formula for the optimal delta
    # delta = sum(var(sample_cov_ij - target_cov_ij)) / sum((sample_cov_ij - target_cov_ij)^2)
    # For speed and stability, we'll use a heuristic or the sklearn constant if possible.
    # Since we must "retarget", we'll implement the intensity calculation.
    
    # Heuristic: delta = 1 / T is often a good start, but we can do better.
    # For Phase A, we use the sklearn-style intensity if available, otherwise 0.2
    try:
        from sklearn.covariance import LedoitWolf
        lw = LedoitWolf()
        lw.fit(returns_matrix)
        delta = lw.shrinkage_
    except Exception:
        delta = 0.2

    # PR-A9 §D — observability signal for κ-Σ calibration. If telemetry shows
    # ``lambda_optimal`` < 0.1 consistently with the three-tier guardrail
    # firing, PR-A10 will expose ``PortfolioCalibration.shrinkage_intensity_override``
    # so operators can force a stronger floor. We do not wire that override
    # here — this line is pure observability.
    logger.info(
        "ledoit_wolf.shrinkage_completed",
        lambda_optimal=float(delta),
        n_funds=int(N),
        t_observations=int(T),
    )

    shrunk_cov = (1 - delta) * sample_cov + delta * target_cov
    return shrunk_cov


# ── Phase A estimator helpers ────────────────────────────────────────


def _compute_ewma_covariance(
    returns_matrix: np.ndarray, lambda_: float = EWMA_LAMBDA_DEFAULT,
) -> np.ndarray:
    """Exponentially-weighted moving-average covariance of daily returns.

    Weights decay as λ^(T-1-t) for t ∈ [0, T); older observations downweighted.
    Weights normalized to sum to 1. λ=1.0 reduces to the sample covariance
    (within numerical tolerance). Returned matrix is the DAILY covariance —
    caller annualizes by multiplying by TRADING_DAYS_PER_YEAR.

    Reference: JPMorgan RiskMetrics (1996) — λ=0.94 for daily FX, 0.97 for equity.
    """
    if not (0.0 < lambda_ <= 1.0):
        raise ValueError(f"ewma_lambda must be in (0, 1], got {lambda_}")

    T = returns_matrix.shape[0]
    if T < 2:
        raise ValueError(f"EWMA covariance requires T≥2, got T={T}")

    # Decay weights: oldest observation gets λ^(T-1), newest gets λ^0 = 1
    exponents = np.arange(T - 1, -1, -1, dtype=np.float64)
    weights = np.power(lambda_, exponents)
    weights = weights / weights.sum()

    # Weighted mean (vectorized)
    mean = np.average(returns_matrix, axis=0, weights=weights)
    deviations = returns_matrix - mean

    # Weighted covariance: (D^T * w) @ D  with weights normalized to sum=1.
    # Unbiased correction for EWMA is λ=1 → (T-1)/T standard; for λ<1 the
    # weights already encode effective sample size. Keep the biased form
    # with ddof=0 semantics — sample cov recovered when λ=1.0 via the
    # trailing rescale below.
    weighted_cov = (deviations * weights[:, None]).T @ deviations

    # When λ=1.0 and T observations, the vanilla weighted sum above equals
    # (1/T) · Σ (x - x̄)(x - x̄)^T. Rescale by T/(T-1) to match np.cov default.
    if lambda_ == 1.0:
        weighted_cov = weighted_cov * (T / (T - 1))

    return weighted_cov


def _compute_condition_number(sigma: np.ndarray) -> float:
    """κ(Σ) — ratio of largest to smallest eigenvalue magnitude.

    Uses np.linalg.cond on a symmetric matrix. Returns np.inf for singular input.
    """
    try:
        kappa = float(np.linalg.cond(sigma))
    except np.linalg.LinAlgError:
        return float("inf")
    if not np.isfinite(kappa):
        return float("inf")
    return kappa


def _repair_psd(
    sigma: np.ndarray, *, min_eigenvalue: float = 1e-10,
) -> tuple[np.ndarray, bool]:
    """Clamp negative/tiny eigenvalues of a near-PSD matrix.

    Returns (repaired_matrix, was_repaired). Logs on repair. Never raises.
    """
    try:
        eigvals = np.linalg.eigvalsh(sigma)
    except np.linalg.LinAlgError:
        return sigma, False
    if eigvals.min() < min_eigenvalue:
        e, V = np.linalg.eigh(sigma)
        e = np.maximum(e, min_eigenvalue)
        repaired = V @ np.diag(e) @ V.T
        logger.info(
            "covariance_psd_repair",
            min_eigenvalue_before=float(eigvals.min()),
            clamp_floor=min_eigenvalue,
        )
        # Symmetrize to wash out floating-point drift
        return (repaired + repaired.T) / 2, True
    return sigma, False


class CovarianceConditioningResult(NamedTuple):
    """Outcome of the three-tier κ(Σ) guardrail.

    ``decision`` is the caller's hand-off:
      - ``sample``          → proceed with the input Σ (warn flag may still be set)
      - ``factor_fallback`` → caller should swap in PR-A3 factor covariance
      - ``rejected``        → unused at the return site (we raise instead); reserved
                              for future non-raising flows / test fixtures.
    """

    kappa: float
    decision: Literal["sample", "factor_fallback", "rejected"]
    warn: bool
    min_eigenvalue: float


def check_covariance_conditioning(
    cov_matrix: npt.NDArray[np.float64],
) -> CovarianceConditioningResult:
    """Evaluate κ(Σ) against the PR-A9 three-tier ladder and recommend a decision.

    Returns a ``CovarianceConditioningResult`` — the caller applies the decision.
    Does NOT raise for recoverable bands (WARN, FALLBACK). Raises
    ``IllConditionedCovarianceError`` only when κ >= ``KAPPA_ERROR_THRESHOLD`` (1e6),
    which indicates true rank deficiency where even the factor fallback cannot help.

    Tier boundaries (see PR-A9 spec §A.1):
      * κ < 1e4              → decision=sample, warn=False (pristine)
      * 1e4 ≤ κ < 5e4        → decision=sample, warn=True  (tolerable, log warning)
      * 5e4 ≤ κ < 1e6        → decision=factor_fallback, warn=True
      * κ ≥ 1e6              → raise IllConditionedCovarianceError
    """
    try:
        eigvals = np.linalg.eigvalsh(cov_matrix)
    except np.linalg.LinAlgError:
        # Totally degenerate matrix — treat as pathological.
        raise IllConditionedCovarianceError(
            condition_number=float("inf"),
            n_funds=cov_matrix.shape[0],
            n_obs=0,
            message=(
                "np.linalg.eigvalsh failed — covariance matrix is numerically degenerate"
            ),
        )
    min_eig = float(eigvals.min())
    max_eig = float(eigvals.max())
    # Guard against zero/negative min eigenvalue; _repair_psd should have clamped
    # earlier, but the kappa ratio still must not blow up to NaN.
    kappa = max_eig / max(min_eig, 1e-12)

    if not np.isfinite(kappa) or kappa >= KAPPA_ERROR_THRESHOLD:
        worst = sorted(eigvals.tolist())[:3]
        raise IllConditionedCovarianceError(
            condition_number=float(kappa) if np.isfinite(kappa) else float("inf"),
            n_funds=cov_matrix.shape[0],
            n_obs=0,
            worst_eigenvalues=worst,
            message=(
                f"κ(Σ)={kappa:.3e} exceeds pathological threshold "
                f"({KAPPA_ERROR_THRESHOLD:.0e}); rank deficient, not recoverable."
            ),
        )

    if kappa >= KAPPA_FALLBACK_THRESHOLD:
        return CovarianceConditioningResult(
            kappa=kappa,
            decision="factor_fallback",
            warn=True,
            min_eigenvalue=min_eig,
        )

    if kappa >= KAPPA_WARN_THRESHOLD:
        return CovarianceConditioningResult(
            kappa=kappa,
            decision="sample",
            warn=True,
            min_eigenvalue=min_eig,
        )

    return CovarianceConditioningResult(
        kappa=kappa,
        decision="sample",
        warn=False,
        min_eigenvalue=min_eig,
    )


def _guard_condition_number(
    sigma: np.ndarray,
    n_obs: int,
) -> tuple[float, bool, bool]:
    """Back-compat shim returning (κ, warn, error) around the new three-tier ladder.

    Kept so non-fallback-aware callers (legacy terminal scripts, tests that
    pin the old signature) keep working. Prefer ``check_covariance_conditioning``
    for new code — it surfaces the factor-fallback band instead of collapsing it
    into the sample path.
    """
    try:
        result = check_covariance_conditioning(sigma)
    except IllConditionedCovarianceError as exc:
        # ``check_covariance_conditioning`` doesn't know T, so the error it
        # raises has ``n_obs=0``. Existing callers (and adversarial tests)
        # expect the shim to enrich it with the observed T.
        logger.error(
            "construction_covariance_ill_conditioned",
            kappa=exc.condition_number,
            n_funds=sigma.shape[0],
            n_obs=n_obs,
        )
        raise IllConditionedCovarianceError(
            condition_number=exc.condition_number,
            n_funds=exc.n_funds,
            n_obs=n_obs,
            worst_eigenvalues=exc.worst_eigenvalues,
            message=str(exc),
        ) from exc

    if result.warn:
        logger.warning(
            "construction_covariance_poorly_conditioned",
            kappa=result.kappa,
            decision=result.decision,
            n_funds=sigma.shape[0],
            n_obs=n_obs,
        )
    # The shim collapses factor_fallback into a warn-only signal for legacy
    # callers that can't swap in factor cov — operationally equivalent to the
    # pre-PR-A9 behaviour now that KAPPA_ERROR_THRESHOLD is 1e6.
    return result.kappa, result.warn, False


def _sanitize_returns(
    fund_returns: dict[str, dict[date, float]],
    instrument_ids: list[uuid.UUID],
) -> tuple[dict[str, dict[date, float]], list[str], list[tuple[str, str]]]:
    """Exclude funds with NaN/Inf/zero-variance data pre-estimation.

    Returns (clean_fund_returns, clean_ids_ordered, excluded). `excluded` is a
    list of (fund_id, reason) pairs for audit. Order is preserved from
    instrument_ids.
    """
    excluded: list[tuple[str, str]] = []
    clean: dict[str, dict[date, float]] = {}
    clean_ids: list[str] = []
    for iid in instrument_ids:
        sid = str(iid)
        series = fund_returns.get(sid)
        if not series:
            # Funds with no data are handled by the caller (not excluded here —
            # they simply don't appear in fund_returns).
            continue
        values = np.fromiter(series.values(), dtype=np.float64, count=len(series))
        if not np.isfinite(values).all():
            excluded.append((sid, "non_finite_returns"))
            logger.warning("fund_excluded_pre_estimation", fund_id=sid, reason="non_finite_returns")
            continue
        stdev = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
        # Guard against float residual noise (np.std on constant series can
        # return O(1e-19) instead of exactly 0). A daily return with σ < 1e-12
        # contributes zero information to the optimizer.
        if stdev < 1e-12:
            excluded.append((sid, "zero_variance"))
            logger.warning("fund_excluded_pre_estimation", fund_id=sid, reason="zero_variance")
            continue
        clean[sid] = series
        clean_ids.append(sid)
    return clean, clean_ids, excluded


async def _fetch_return_horizons(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
    as_of_date: date,
) -> dict[str, dict[str, float | None]]:
    """Fetch return_5y_ann and return_10y_ann for each instrument at or before as_of_date.

    Returns {instrument_id_str: {"5y": float|None, "10y": float|None}}.
    Missing rows / NULL values map to None; caller applies THBB availability schedule.
    """
    from app.domains.wealth.models.risk import FundRiskMetrics

    # Pull the most recent row ≤ as_of_date per instrument_id.
    stmt = (
        select(
            FundRiskMetrics.instrument_id,
            FundRiskMetrics.calc_date,
            FundRiskMetrics.return_5y_ann,
            FundRiskMetrics.return_10y_ann,
        )
        .where(
            FundRiskMetrics.instrument_id.in_(instrument_ids),
            FundRiskMetrics.calc_date <= as_of_date,
        )
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc())
    )
    rows = (await db.execute(stmt)).all()

    latest: dict[str, dict[str, float | None]] = {}
    for instrument_id, _calc_date, r5, r10 in rows:
        sid = str(instrument_id)
        if sid in latest:
            continue  # keep only the most recent (ORDER BY DESC + de-dup)
        latest[sid] = {
            "5y": float(r5) if r5 is not None else None,
            "10y": float(r10) if r10 is not None else None,
        }
    # Funds with no row at all
    for iid in instrument_ids:
        sid = str(iid)
        if sid not in latest:
            latest[sid] = {"5y": None, "10y": None}
    return latest


def _thbb_weights_for_fund(
    has_10y: bool, has_5y: bool,
) -> tuple[float, float, float]:
    """Availability-conditional THBB blend weights, renormalized to 1.0.

    Schedule:
      10y + 5y + eq:  (0.5, 0.3, 0.2)
      5y + eq:        (0.0, 0.7, 0.3)
      eq only:        (0.0, 0.0, 1.0)
    """
    if has_10y and has_5y:
        return 0.5, 0.3, 0.2
    if has_5y:
        return 0.0, 0.7, 0.3
    return 0.0, 0.0, 1.0


def _build_thbb_prior(
    available_ids: list[str],
    return_horizons: dict[str, dict[str, float | None]],
    sigma_annual: np.ndarray,
    w_benchmark: np.ndarray,
    risk_aversion: float,
) -> tuple[np.ndarray, dict[str, float], dict[str, int]]:
    """Three-Horizon Bayesian Blend prior for expected returns.

    μ₀ = w_10·return_10y_ann + w_5·return_5y_ann + w_eq·π
    where π = γ·Σ·w_benchmark (He-Litterman reverse optimization).

    Returns:
        (mu_prior, mean_weights_used, n_funds_by_history)
        - mu_prior: (N,) annualized prior returns
        - mean_weights_used: mean across funds of (w_10, w_5, w_eq) — for audit
        - n_funds_by_history: counts per availability bucket
    """
    pi = risk_aversion * (sigma_annual @ w_benchmark)

    N = len(available_ids)
    mu_prior = np.zeros(N, dtype=np.float64)
    accum_w10 = accum_w5 = accum_weq = 0.0
    buckets = {"10y+": 0, "5y+": 0, "1y_only": 0}

    for i, fid in enumerate(available_ids):
        r10 = return_horizons.get(fid, {}).get("10y")
        r5 = return_horizons.get(fid, {}).get("5y")
        has_10y = r10 is not None
        has_5y = r5 is not None

        w10, w5, weq = _thbb_weights_for_fund(has_10y, has_5y)
        accum_w10 += w10
        accum_w5 += w5
        accum_weq += weq

        if has_10y:
            buckets["10y+"] += 1
        elif has_5y:
            buckets["5y+"] += 1
        else:
            buckets["1y_only"] += 1

        mu_prior[i] = (
            w10 * (r10 if r10 is not None else 0.0)
            + w5 * (r5 if r5 is not None else 0.0)
            + weq * pi[i]
        )

    mean_weights = {
        "10y": accum_w10 / N if N else 0.0,
        "5y": accum_w5 / N if N else 0.0,
        "eq": accum_weq / N if N else 0.0,
    }
    return mu_prior, mean_weights, buckets


def _build_data_view(
    returns_matrix: np.ndarray,
    available_ids: list[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Data-view tuple (P, Q, Ω) for Black-Litterman.

    - P = I_N   (each fund has its own view on its own mean)
    - Q = annualized 1Y daily mean per fund (tail of the returns matrix)
    - Ω = diag(σ²_annual / N_obs_1y)   (standard error of the mean)

    Returns arrays ready for BL stacking in PR-A2. Not consumed in PR-A1.
    """
    N = len(available_ids)
    if returns_matrix.shape[1] != N:
        raise ValueError(
            f"returns_matrix has {returns_matrix.shape[1]} columns, expected {N}",
        )

    tail_n = min(TRADING_DAYS_PER_YEAR, returns_matrix.shape[0])
    tail = returns_matrix[-tail_n:]
    daily_mean = tail.mean(axis=0)
    daily_var = tail.var(axis=0, ddof=1)
    q = daily_mean * TRADING_DAYS_PER_YEAR
    omega_diag = (daily_var * TRADING_DAYS_PER_YEAR) / max(tail_n, 1)
    return np.eye(N, dtype=np.float64), q, np.diag(omega_diag)


def _winsorize_returns(
    returns_matrix: np.ndarray, lower: float = 0.01, upper: float = 0.99,
) -> np.ndarray:
    """Column-wise winsorization at given percentiles for higher-moment estimation."""
    if returns_matrix.shape[0] < 10:
        return returns_matrix  # not enough observations to clip meaningfully
    lo = np.quantile(returns_matrix, lower, axis=0)
    hi = np.quantile(returns_matrix, upper, axis=0)
    return np.clip(returns_matrix, lo, hi)


async def _resolve_risk_aversion(
    db: AsyncSession,
    org_id: uuid.UUID | None,
    actor_id: str | None = None,
    request_id: str | None = None,
) -> tuple[float, str]:
    """Resolve γ from ConfigService with audit trail on override.

    Default: RISK_AVERSION_INSTITUTIONAL_DEFAULT (2.5). ConfigService override
    at wealth/construction.risk_aversion triggers an AuditEvent with before/after.

    Returns (gamma, source).
    """
    if org_id is None:
        return RISK_AVERSION_INSTITUTIONAL_DEFAULT, "institutional_default"

    try:
        from app.core.config.config_service import ConfigService
    except ImportError:
        return RISK_AVERSION_INSTITUTIONAL_DEFAULT, "institutional_default"

    try:
        result = await ConfigService(db=db).get("wealth", "construction", org_id=org_id)
        cfg = result.value if hasattr(result, "value") else result
        override = cfg.get("risk_aversion") if isinstance(cfg, dict) else None
    except Exception as exc:
        logger.debug("risk_aversion_config_fetch_failed", error=str(exc))
        return RISK_AVERSION_INSTITUTIONAL_DEFAULT, "institutional_default"

    if override is None:
        return RISK_AVERSION_INSTITUTIONAL_DEFAULT, "institutional_default"

    try:
        gamma = float(override)
    except (TypeError, ValueError):
        return RISK_AVERSION_INSTITUTIONAL_DEFAULT, "institutional_default"

    if gamma == RISK_AVERSION_INSTITUTIONAL_DEFAULT:
        return gamma, "institutional_default"

    # Audit every non-default γ value so the IC can trace every override.
    try:
        from app.core.db.audit import write_audit_event

        await write_audit_event(
            db,
            actor_id=actor_id,
            request_id=request_id,
            action="risk_aversion_overridden",
            entity_type="wealth_construction_config",
            entity_id=str(org_id),
            before={"risk_aversion": RISK_AVERSION_INSTITUTIONAL_DEFAULT},
            after={"risk_aversion": gamma},
            organization_id=org_id,
        )
    except Exception as exc:  # audit failure must not block estimator
        logger.warning("risk_aversion_audit_failed", error=str(exc))

    return gamma, "config_override"


async def _fetch_returns_by_type(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
    start_date: date,
    as_of_date: date,
) -> tuple[dict[str, dict[date, float]], str]:
    """Fetch returns filtered by return_type: prefer 'log', fallback 'arithmetic'.

    Never mixes return types in the same result. Returns (fund_returns_dict, used_type).
    """
    for return_type in ("log", "arithmetic"):
        ret_stmt = (
            select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
            .where(
                NavTimeseries.instrument_id.in_(instrument_ids),
                NavTimeseries.nav_date >= start_date,
                NavTimeseries.nav_date <= as_of_date,
                NavTimeseries.return_1d.is_not(None),
                NavTimeseries.return_type == return_type,
            )
            .order_by(NavTimeseries.nav_date)
        )
        ret_result = await db.execute(ret_stmt)

        fund_returns: dict[str, dict[date, float]] = defaultdict(dict)
        for instrument_id, nav_date, return_1d in ret_result.all():
            fund_returns[str(instrument_id)][nav_date] = float(return_1d)

        n_funds_with_data = sum(
            1 for iid in instrument_ids if str(iid) in fund_returns
        )
        if n_funds_with_data >= 2:
            if return_type == "arithmetic":
                logger.warning(
                    "fund_returns_fallback_to_arithmetic",
                    reason="insufficient funds with log returns",
                    n_funds=n_funds_with_data,
                )
            return fund_returns, return_type

    # Neither type yielded ≥2 funds — return empty (caller raises ValueError)
    logger.warning("no_return_type_yielded_sufficient_funds")
    return defaultdict(dict), "none"


async def fetch_bl_views_for_portfolio(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    fund_ids: list[str],
) -> list[dict[str, Any]]:
    """Fetch active IC views and map instrument_ids to fund index positions.

    Returns list of dicts ready for black_litterman_service.compute_bl_returns().
    """
    from app.domains.wealth.models.portfolio_view import PortfolioView

    today = date.today()
    stmt = (
        select(PortfolioView)
        .where(
            PortfolioView.portfolio_id == portfolio_id,
            PortfolioView.effective_from <= today,
        )
        .where(
            (PortfolioView.effective_to.is_(None))
            | (PortfolioView.effective_to >= today),
        )
    )
    result = await db.execute(stmt)
    views = result.scalars().all()

    if not views:
        return []

    # Build instrument_id -> index map
    id_to_idx = {fid: i for i, fid in enumerate(fund_ids)}

    bl_views: list[dict[str, Any]] = []
    for v in views:
        if v.view_type == "absolute":
            asset_id = str(v.asset_instrument_id) if v.asset_instrument_id else None
            if asset_id and asset_id in id_to_idx:
                bl_views.append({
                    "type": "absolute",
                    "asset_idx": id_to_idx[asset_id],
                    "Q": float(v.expected_return),
                    "confidence": float(v.confidence),
                })
        elif v.view_type == "relative":
            long_id = str(v.asset_instrument_id) if v.asset_instrument_id else None
            short_id = str(v.peer_instrument_id) if v.peer_instrument_id else None
            if long_id and short_id and long_id in id_to_idx and short_id in id_to_idx:
                bl_views.append({
                    "type": "relative",
                    "long_idx": id_to_idx[long_id],
                    "short_idx": id_to_idx[short_id],
                    "Q": float(v.expected_return),
                    "confidence": float(v.confidence),
                })

    return bl_views


async def _build_ic_views(
    db: AsyncSession,
    portfolio_id: uuid.UUID | None,
    available_ids: list[str],
    sigma_annual: np.ndarray,
    tau: float,
) -> list:
    """Build IC views for multi-view Black-Litterman stacking.

    Pulls active `portfolio_views` rows, maps them to picking-matrix rows, and
    computes Ω_ii via the Idzorek (2005) mapping:

        Ω_ii = (1 - confidence) / confidence · (P_i · τΣ · P_iᵀ)

    Where `P_i · τΣ · P_iᵀ` is the prior variance along the view direction —
    an Idzorek-style scale-matched uncertainty. Confidence is NOT clamped here:
    confidence=1.0 produces Ω_ii = 0 and is handled by the regularization
    inside :func:`compute_bl_posterior_multi_view`.

    Returns a list of `View` dataclasses (quant_engine.black_litterman_service.View).
    Empty list if no portfolio_id, no active views, or none map to available_ids.
    """
    if portfolio_id is None:
        return []

    from app.domains.wealth.models.portfolio_view import PortfolioView
    from quant_engine.black_litterman_service import View

    today = date.today()
    stmt = (
        select(PortfolioView)
        .where(
            PortfolioView.portfolio_id == portfolio_id,
            PortfolioView.effective_from <= today,
        )
        .where(
            (PortfolioView.effective_to.is_(None))
            | (PortfolioView.effective_to >= today),
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    id_to_idx = {fid: i for i, fid in enumerate(available_ids)}
    n = len(available_ids)
    views: list[View] = []

    for v in rows:
        p_row = np.zeros(n, dtype=np.float64)
        if v.view_type == "absolute":
            asset_id = str(v.asset_instrument_id) if v.asset_instrument_id else None
            if asset_id is None or asset_id not in id_to_idx:
                continue
            p_row[id_to_idx[asset_id]] = 1.0
        elif v.view_type == "relative":
            long_id = str(v.asset_instrument_id) if v.asset_instrument_id else None
            short_id = str(v.peer_instrument_id) if v.peer_instrument_id else None
            if (
                long_id is None or short_id is None
                or long_id not in id_to_idx or short_id not in id_to_idx
            ):
                continue
            p_row[id_to_idx[long_id]] = 1.0
            p_row[id_to_idx[short_id]] = -1.0
        else:
            continue

        conf = float(v.confidence)
        # Prior variance along the view direction (Idzorek 2005).
        prior_var = float(p_row @ (tau * sigma_annual) @ p_row)
        if prior_var <= 0.0:
            prior_var = 1e-12

        if conf <= 0.0:
            # Degenerate: zero confidence → view carries no information.
            # Make Ω_ii huge so the posterior ignores it.
            omega_ii = prior_var * 1e12
        elif conf >= 1.0:
            # Certainty: Ω_ii → 0. Regularization in compute_bl_posterior_multi_view
            # keeps the solve stable while letting the view dominate.
            omega_ii = 0.0
        else:
            omega_ii = prior_var * (1.0 - conf) / conf

        views.append(
            View(
                P=p_row.reshape(1, n),
                Q=np.array([float(v.expected_return)], dtype=np.float64),
                Omega=np.array([[omega_ii]], dtype=np.float64),
                source="ic_view",
                confidence=conf,
            ),
        )

    return views


async def fetch_strategic_weights_for_funds(
    db: AsyncSession,
    fund_ids: list[str],
    profile: str,
) -> np.ndarray:
    """Fetch strategic allocation targets as market proxy weights for BL.

    Maps block-level targets to individual fund weights (equal-split within block).
    Returns (N,) array aligned with fund_ids.
    """
    from app.domains.wealth.models.instrument_org import InstrumentOrg

    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to > today),
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    block_targets = {a.block_id: float(a.target_weight) for a in alloc_result.scalars().all()}

    # Map fund_ids to blocks via InstrumentOrg
    fund_uuids = [uuid.UUID(fid) for fid in fund_ids]
    inst_stmt = (
        select(InstrumentOrg.instrument_id, InstrumentOrg.block_id)
        .where(InstrumentOrg.instrument_id.in_(fund_uuids))
    )
    inst_result = await db.execute(inst_stmt)
    fund_block_map = {str(r.instrument_id): r.block_id for r in inst_result.all()}

    # Count funds per block for equal-split
    block_fund_counts: dict[str, int] = defaultdict(int)
    for fid in fund_ids:
        blk = fund_block_map.get(fid)
        if blk and blk in block_targets:
            block_fund_counts[blk] += 1

    # Assign weights
    w_market = np.zeros(len(fund_ids))
    for i, fid in enumerate(fund_ids):
        blk = fund_block_map.get(fid)
        if blk and blk in block_targets and block_fund_counts[blk] > 0:
            w_market[i] = block_targets[blk] / block_fund_counts[blk]

    # Normalize
    total = w_market.sum()
    if total > 0:
        w_market /= total

    return w_market


async def compute_fund_level_inputs(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
    *,
    cov_lookback_days: int = COV_LOOKBACK_DAYS_5Y,
    higher_moments_window: int = HIGHER_MOMENTS_WINDOW_3Y,
    ewma_lambda: float = EWMA_LAMBDA_DEFAULT,
    mu_prior: Literal["thbb", "historical_1y", "equilibrium"] = "thbb",
    as_of_date: date | None = None,
    config: dict[str, Any] | None = None,
    portfolio_id: uuid.UUID | None = None,
    profile: str | None = None,
    organization_id: uuid.UUID | None = None,
    actor_id: str | None = None,
    request_id: str | None = None,
) -> FundLevelInputs:
    """Phase A multi-horizon Bayesian-factor estimator.

    Replaces the 1Y rectangular estimator with:
      - 5Y EWMA covariance (λ=0.97 half-life ≈ 23d)
      - Three-Horizon Bayesian Blend (THBB) for expected returns
      - 3Y window for higher moments (skew/kurt) with 1%/99% winsorization
      - κ(Σ) guardrail — warn > 1e3, raise > 1e4

    Fundamental factor-model covariance is layered on top in PR-A3. In PR-A1
    the covariance is 5Y EWMA with Ledoit-Wolf shrinkage fallback.

    Returns a frozen FundLevelInputs dataclass. Raises IllConditionedCovarianceError
    if κ(Σ) > 1e4 — the caller MUST NOT proceed to the optimizer in that case.

    Raises:
        ValueError: If <2 funds have aligned data or <MIN_OBSERVATIONS trading days.
        IllConditionedCovarianceError: If κ(Σ) > KAPPA_ERROR_THRESHOLD.
    """
    from scipy import stats as sp_stats

    if as_of_date is None:
        as_of_date = date.today()

    lookback_start = as_of_date - timedelta(days=int(cov_lookback_days * 1.5))

    # ── 1. Fetch returns (log preferred, arithmetic fallback) ──────────────
    fund_returns, used_return_type = await _fetch_returns_by_type(
        db, instrument_ids, lookback_start, as_of_date,
    )

    # ── 2. Exclude pathological funds (NaN/Inf/zero-var) pre-alignment ─────
    fund_returns, clean_ids, excluded = _sanitize_returns(fund_returns, instrument_ids)

    # Keep only funds with data (clean_ids already ordered by instrument_ids)
    available_ids = clean_ids
    if len(available_ids) < 2:
        raise ValueError(
            f"Need ≥2 funds with usable NAV data, found {len(available_ids)} "
            f"(excluded: {len(excluded)})",
        )

    returns_matrix, common_dates = _align_returns_with_ffill(fund_returns, available_ids)

    if len(common_dates) < MIN_OBSERVATIONS:
        raise ValueError(
            f"Insufficient aligned fund data: {len(common_dates)} trading days "
            f"(minimum: {MIN_OBSERVATIONS})",
        )

    # Trim to the requested 5Y cov window (may have pulled more via ffill)
    if returns_matrix.shape[0] > cov_lookback_days:
        returns_matrix = returns_matrix[-cov_lookback_days:]

    # ── 3. Covariance estimation (Fundamental Factor vs LW Fallback) ──────
    factor_loadings = None
    factor_names = None
    residual_variance = None
    # PR-A9 — hoisted factor fit reference so the κ guardrail below can swap in
    # ``assemble_factor_covariance(fit)`` as a fallback when the primary Σ lands
    # in the [5e4, 1e6) band. ``fit`` stays None in the LW-only branches where
    # the factor model was unavailable; the fallback then raises per spec B.2.
    fit = None
    covariance_source: Literal["sample", "factor_model"] = "sample"
    # A.2 — metadata persisted on FundLevelInputs.inputs_metadata
    factor_model_meta: dict[str, Any] = {
        "k_factors": 8,
        "k_factors_effective": 0,
        "factors_skipped": [],
        "r_squared_per_fund": {},
        "kappa_factor_cov": None,
        "shrinkage_lambda": None,
    }
    residual_pca_meta: dict[str, Any] = {
        "n_components": 0,
        "cumulative_variance": [],
        "top_eigenvalue_share": 0.0,
    }

    # A.7 — hoist `build_fundamental_factor_returns` out of the N>=20 / N<20
    # branch so it is called exactly once per invocation (previously called in
    # the factor-model path AND again in the LW fallback to recover the market
    # proxy).
    try:
        factor_returns_df = await build_fundamental_factor_returns(
            db, common_dates[0], common_dates[-1]
        )
    except Exception as fr_err:
        logger.warning(
            "factor_returns_fetch_failed",
            reason=str(fr_err),
        )
        factor_returns_df = pd.DataFrame()

    if len(available_ids) >= 20:
        if not factor_returns_df.empty and len(factor_returns_df) >= MIN_OBSERVATIONS:
            common_idx = factor_returns_df.index.intersection(
                pd.to_datetime(common_dates)
            )
            if len(common_idx) >= MIN_OBSERVATIONS:
                f_returns = factor_returns_df.loc[common_idx].values
                date_to_idx = {d: i for i, d in enumerate(pd.to_datetime(common_dates))}
                matrix_idx = [date_to_idx[d] for d in common_idx]
                r_matrix = returns_matrix[matrix_idx]

                fit = fit_fundamental_loadings(
                    r_matrix,
                    f_returns,
                    factor_names=factor_returns_df.columns.tolist(),
                    ewma_lambda=ewma_lambda,
                )
                annual_cov = assemble_factor_covariance(fit)
                covariance_source = "factor_model"

                # A.2 — residual PCA diagnostic wired into metadata (was discarded)
                pca_diag = compute_residual_pca(fit.residual_series)

                factor_loadings = fit.loadings
                factor_names = fit.factor_names
                residual_variance = fit.residual_variance

                factors_skipped = factor_returns_df.attrs.get("skipped", [])
                try:
                    kappa_factor_cov = float(np.linalg.cond(fit.factor_cov))
                except Exception:
                    kappa_factor_cov = float("nan")

                factor_model_meta = {
                    "k_factors": 8,
                    "k_factors_effective": len(fit.factor_names),
                    "factors_skipped": [s.get("name", "") for s in factors_skipped],
                    "r_squared_per_fund": {
                        fid: float(fit.r_squared_per_fund[i])
                        for i, fid in enumerate(available_ids)
                    },
                    "kappa_factor_cov": kappa_factor_cov,
                    "shrinkage_lambda": fit.shrinkage_lambda,
                }
                ev = pca_diag.explained_variance_ratio
                residual_pca_meta = {
                    "n_components": int(len(ev)),
                    "cumulative_variance": [float(x) for x in np.cumsum(ev).tolist()],
                    "top_eigenvalue_share": float(ev[0]) if len(ev) > 0 else 0.0,
                }

                if factors_skipped:
                    logger.info(
                        "fundamental_factor_model_partial_fit",
                        n_factors=len(fit.factor_names),
                        skipped_count=len(factors_skipped),
                        skipped=factors_skipped,
                    )
            else:
                logger.warning(
                    "factor_returns_alignment_failed",
                    reason="insufficient overlapping dates",
                )
                daily_cov = _apply_ledoit_wolf(returns_matrix)
                annual_cov = daily_cov * TRADING_DAYS_PER_YEAR
        else:
            logger.warning(
                "fundamental_factor_model_skipped",
                reason="insufficient factor data",
            )
            daily_cov = _apply_ledoit_wolf(returns_matrix)
            annual_cov = daily_cov * TRADING_DAYS_PER_YEAR
    else:
        # 3b. LW single-index shrinkage fallback (N < 20)
        market_index = None
        if (
            not factor_returns_df.empty
            and "equity_us" in factor_returns_df.columns
        ):
            market_index = (
                factor_returns_df["equity_us"]
                .reindex(pd.to_datetime(common_dates))
                .ffill()
                .values
            )

        daily_cov = _apply_ledoit_wolf(returns_matrix, market_index=market_index)
        annual_cov = daily_cov * TRADING_DAYS_PER_YEAR

    # PSD repair (pre-κ — a slightly non-PSD matrix must be clamped before the
    # eigenvalue ratio guard is meaningful).
    annual_cov, _was_repaired = _repair_psd(annual_cov)

    # ── 4. Optional regime conditioning (runs on top of EWMA base) ─────────
    regime_cov = _maybe_regime_condition_cov(db, returns_matrix, annual_cov, config)
    if regime_cov is not None:
        annual_cov, _ = _repair_psd(regime_cov)

    # ── 5. κ(Σ) three-tier guardrail + lazy factor-model fallback ──────────
    # PR-A9 — the primary covariance (factor or LW) is evaluated against the
    # recalibrated ladder:
    #   κ < 1e4              → pristine, no warn
    #   1e4 ≤ κ < 5e4        → warn, proceed with primary Σ
    #   5e4 ≤ κ < 1e6        → swap in PR-A3 factor covariance if we have a fit;
    #                          otherwise raise per B.2 (fallback unavailable)
    #   κ ≥ 1e6              → raise (pathological, not recoverable)
    kappa_sample_observed = float(_compute_condition_number(annual_cov))
    try:
        cond_primary = check_covariance_conditioning(annual_cov)
    except IllConditionedCovarianceError:
        logger.error(
            "construction_covariance_ill_conditioned",
            kappa=kappa_sample_observed,
            covariance_source=covariance_source,
            n_funds=annual_cov.shape[0],
            n_obs=returns_matrix.shape[0],
        )
        raise

    kappa_factor_fallback: float | None = None
    if cond_primary.decision == "factor_fallback":
        fallback_available = (
            covariance_source == "sample"
            and fit is not None
            and factor_model_meta.get("k_factors_effective", 0) > 0
        )
        if not fallback_available:
            # Either already on factor cov (can't go further), or no factor fit
            # was produced in this run — raise with the empirical κ so the
            # operator can distinguish "sample too collinear, no factor help"
            # from a true pathological rank deficiency.
            logger.error(
                "construction_covariance_fallback_unavailable",
                kappa_sample=cond_primary.kappa,
                covariance_source=covariance_source,
                fit_available=fit is not None,
                k_factors_effective=factor_model_meta.get("k_factors_effective", 0),
                n_funds=annual_cov.shape[0],
                n_obs=returns_matrix.shape[0],
            )
            raise IllConditionedCovarianceError(
                condition_number=cond_primary.kappa,
                n_funds=annual_cov.shape[0],
                n_obs=returns_matrix.shape[0],
                message=(
                    f"κ(Σ)={cond_primary.kappa:.3e} in fallback band "
                    f"[{KAPPA_FALLBACK_THRESHOLD:.0e}, {KAPPA_ERROR_THRESHOLD:.0e}) "
                    f"but factor fallback unavailable (source={covariance_source}, "
                    f"fit={'set' if fit is not None else 'none'}, "
                    f"k_effective={factor_model_meta.get('k_factors_effective', 0)})"
                ),
            )

        # Assemble the factor-cov candidate lazily (avoids wasted work when
        # primary Σ was already acceptable). PR-A3 clamps PSD internally, but
        # the regime-conditioning path further downstream assumes PSD input —
        # run _repair_psd to keep the contract explicit.
        assert fit is not None  # fallback_available guarantees this; narrows type for mypy
        factor_cov_candidate = assemble_factor_covariance(fit)
        factor_cov_candidate, _ = _repair_psd(factor_cov_candidate)
        try:
            cond_factor = check_covariance_conditioning(factor_cov_candidate)
        except IllConditionedCovarianceError as factor_exc:
            logger.error(
                "construction_covariance_factor_fallback_pathological",
                kappa_sample=cond_primary.kappa,
                reason=str(factor_exc),
            )
            raise IllConditionedCovarianceError(
                condition_number=cond_primary.kappa,
                n_funds=annual_cov.shape[0],
                n_obs=returns_matrix.shape[0],
                message=(
                    f"Both sample (κ={cond_primary.kappa:.3e}) and factor "
                    f"(κ≥{KAPPA_ERROR_THRESHOLD:.0e}) covariances are "
                    f"ill-conditioned."
                ),
            ) from factor_exc
        if cond_factor.decision != "sample":
            raise IllConditionedCovarianceError(
                condition_number=cond_primary.kappa,
                n_funds=annual_cov.shape[0],
                n_obs=returns_matrix.shape[0],
                message=(
                    f"Both sample (κ={cond_primary.kappa:.3e}) and factor "
                    f"(κ={cond_factor.kappa:.3e}) covariances are "
                    f"ill-conditioned."
                ),
            )
        logger.info(
            "construction_covariance_factor_fallback_engaged",
            kappa_sample=cond_primary.kappa,
            kappa_factor=cond_factor.kappa,
            n_funds=annual_cov.shape[0],
            n_obs=returns_matrix.shape[0],
        )
        annual_cov = factor_cov_candidate
        covariance_source = "factor_model"
        kappa_factor_fallback = cond_factor.kappa
        # Wire the factor provenance into metadata the return dataclass emits,
        # so downstream (stats, audit, narrative) sees the real cov.
        if factor_loadings is None:
            factor_loadings = fit.loadings
        if factor_names is None:
            factor_names = fit.factor_names
        if residual_variance is None:
            residual_variance = fit.residual_variance
    elif cond_primary.warn:
        logger.warning(
            "construction_covariance_poorly_conditioned",
            kappa=cond_primary.kappa,
            decision=cond_primary.decision,
            covariance_source=covariance_source,
            n_funds=annual_cov.shape[0],
            n_obs=returns_matrix.shape[0],
        )

    kappa_final = kappa_factor_fallback if kappa_factor_fallback is not None else cond_primary.kappa
    condition_number = kappa_final
    # Legacy booleans on FundLevelInputs — retained for back-compat with PR-A4
    # inputs_metadata readers. Semantics track the new three-tier ladder.
    kappa_warn = kappa_final >= KAPPA_WARN_THRESHOLD
    kappa_error = False  # would have raised above

    # ── 6. Higher moments on 3Y tail with 1%/99% winsorization ─────────────
    tail_n = min(higher_moments_window, returns_matrix.shape[0])
    higher_moments_tail = returns_matrix[-tail_n:]
    winsorized_tail = _winsorize_returns(higher_moments_tail, lower=0.01, upper=0.99)
    skewness = sp_stats.skew(winsorized_tail, axis=0, bias=False)
    excess_kurtosis = sp_stats.kurtosis(winsorized_tail, axis=0, fisher=True, bias=False)

    # ── 7. Risk aversion γ (config-overridable, audit on override) ─────────
    gamma, gamma_source = await _resolve_risk_aversion(
        db, organization_id, actor_id=actor_id, request_id=request_id,
    )

    # ── 8. Build expected returns per mu_prior mode ────────────────────────
    mean_weights_used: dict[str, float]
    n_funds_by_history: dict[str, int]

    if mu_prior == "historical_1y":
        # Legacy pre-Phase-A behavior — keep as an opt-in escape hatch.
        hist_tail = returns_matrix[-min(TRADING_DAYS_PER_YEAR, returns_matrix.shape[0]):]
        daily_means = hist_tail.mean(axis=0)
        annual_returns = daily_means * TRADING_DAYS_PER_YEAR
        mu_vec = annual_returns
        mean_weights_used = {"10y": 0.0, "5y": 0.0, "eq": 0.0}
        n_funds_by_history = {"10y+": 0, "5y+": 0, "1y_only": len(available_ids)}
    else:
        # Fetch strategic weights (benchmark) — equal-weight fallback if profile missing
        if profile is not None:
            w_benchmark = await fetch_strategic_weights_for_funds(db, available_ids, profile)
        else:
            w_benchmark = np.full(len(available_ids), 1.0 / len(available_ids))
        if w_benchmark.sum() == 0:
            w_benchmark = np.full(len(available_ids), 1.0 / len(available_ids))

        if mu_prior == "equilibrium":
            mu_vec = gamma * (annual_cov @ w_benchmark)
            mean_weights_used = {"10y": 0.0, "5y": 0.0, "eq": 1.0}
            n_funds_by_history = {"10y+": 0, "5y+": 0, "1y_only": len(available_ids)}
        else:
            # THBB (default) — per-fund availability-conditional blend.
            # PR-A2: wrap THBB prior in multi-view BL with data view + IC views.
            instrument_uuids = [uuid.UUID(fid) for fid in available_ids]
            return_horizons = await _fetch_return_horizons(
                db, instrument_uuids, as_of_date,
            )
            mu_prior_vec, mean_weights_used, n_funds_by_history = _build_thbb_prior(
                available_ids,
                return_horizons,
                annual_cov,
                w_benchmark,
                risk_aversion=gamma,
            )

            from quant_engine.black_litterman_service import (
                TAU_PHASE_A,
                View,
                compute_bl_posterior_multi_view,
            )

            # Data view: each fund's own 1Y annualized mean with standard-error Ω
            P_data, Q_data, Omega_data = _build_data_view(returns_matrix, available_ids)
            data_view = View(
                P=P_data, Q=Q_data, Omega=Omega_data,
                source="data_view", confidence=None,
            )

            # IC views from portfolio_views (empty list if no portfolio_id)
            ic_views = await _build_ic_views(
                db, portfolio_id, available_ids, annual_cov, tau=TAU_PHASE_A,
            )

            mu_vec = compute_bl_posterior_multi_view(
                mu_prior=mu_prior_vec,
                sigma=annual_cov,
                views=[data_view, *ic_views],
                tau=TAU_PHASE_A,
            )

    expected_returns = {fid: float(mu_vec[i]) for i, fid in enumerate(available_ids)}

    # ── 9. Fee adjustment (expense ratio subtracted from μ) ────────────────
    if config and config.get("fee_adjustment", {}).get("enabled"):
        from app.domains.wealth.models.instrument import Instrument

        inst_rows = (
            await db.execute(
                select(Instrument).where(
                    Instrument.instrument_id.in_(instrument_ids),
                ),
            )
        ).scalars().all()
        instruments_by_id = {str(i.instrument_id): i for i in inst_rows}
        for fid in available_ids:
            inst = instruments_by_id.get(fid)
            if inst and inst.attributes:
                er = inst.attributes.get("expense_ratio_pct")
                if er is not None:
                    expected_returns[fid] -= float(er)

    # ── 10. Regime probability snapshot (for audit — best effort) ──────────
    regime_probability_at_calc: float | None = None
    if config and isinstance(config, dict):
        probs = config.get("regime_cov", {}).get("_regime_probs")
        if probs:
            lookback = min(21, len(probs))
            regime_probability_at_calc = float(np.mean(probs[-lookback:]))

    logger.info(
        "fund_level_inputs_computed_phase_a",
        n_funds=len(available_ids),
        observations=returns_matrix.shape[0],
        return_type=used_return_type,
        mu_prior=mu_prior,
        ewma_lambda=ewma_lambda,
        condition_number=condition_number,
        kappa_sample=kappa_sample_observed,
        kappa_final=kappa_final,
        covariance_source=covariance_source,
        kappa_warn=kappa_warn,
        gamma=gamma,
        gamma_source=gamma_source,
        excluded_count=len(excluded),
    )

    # PR-A12 — warn on short history (T < 504 = 2Y daily). The RU LP still
    # works but CVaR tail is estimated from <2 full credit cycles. Hard
    # floor MIN_OBSERVATIONS (252 = 1Y) is enforced earlier in this
    # function; anything below that has already raised ValueError.
    T_effective = int(returns_matrix.shape[0])
    if T_effective < 504:
        logger.warning(
            "fund_level_inputs_short_history",
            t_effective=T_effective,
            recommended_min=504,
            hard_floor=MIN_OBSERVATIONS,
        )

    return FundLevelInputs(
        cov_matrix=annual_cov,
        expected_returns=expected_returns,
        available_ids=available_ids,
        returns_scenarios=np.ascontiguousarray(returns_matrix, dtype=np.float64),
        skewness=np.asarray(skewness, dtype=np.float64),
        excess_kurtosis=np.asarray(excess_kurtosis, dtype=np.float64),
        condition_number=condition_number,
        factor_loadings=factor_loadings,
        factor_names=factor_names,
        residual_variance=residual_variance,
        prior_weights_used=mean_weights_used,
        n_funds_by_history=n_funds_by_history,
        regime_probability_at_calc=regime_probability_at_calc,
        used_return_type=used_return_type,
        lookback_start_date=common_dates[0] if common_dates else lookback_start,
        lookback_end_date=common_dates[-1] if common_dates else as_of_date,
        risk_aversion_gamma=gamma,
        risk_aversion_source=gamma_source,
        kappa_warning_triggered=kappa_warn,
        kappa_error_triggered=kappa_error,
        funds_excluded=tuple(excluded),
        inputs_metadata={
            "factor_model": factor_model_meta,
            "residual_pca": residual_pca_meta,
            # PR-A9 — three-tier conditioning telemetry. Persisted in
            # ``portfolio_construction_runs.statistical_inputs`` so the
            # SHRINKAGE phase SSE payload (PR-A10) can format human labels.
            "conditioning": {
                "kappa_sample": float(kappa_sample_observed),
                "kappa_final": float(kappa_final),
                "kappa_factor_fallback": (
                    float(kappa_factor_fallback)
                    if kappa_factor_fallback is not None
                    else None
                ),
                "covariance_source": covariance_source,
                "warn": bool(kappa_warn),
            },
        },
    )


# ── Regime-conditioned covariance (BL-5) ─────────────────────────────


def compute_regime_conditioned_cov(
    returns_matrix: np.ndarray,
    regime_probs: np.ndarray,
    short_window: int = 63,
    long_window: int = 252,
) -> np.ndarray:
    """Compute regime-adaptive covariance matrix.

    Strategy:
    - If current regime (mean of last 21d regime_probs) > 0.6 (stress):
        use short window (63d) with stress-weighted observations
    - Otherwise: use long window (252d) standard estimation

    Returns annualized (N x N) covariance.
    """
    T = returns_matrix.shape[0]

    # Current regime: average P(high_vol) over last 21 days
    lookback = min(21, len(regime_probs))
    current_regime_prob = float(np.mean(regime_probs[-lookback:]))

    if current_regime_prob > 0.6:
        # Stress regime: use short window, weight by regime probability
        window = min(short_window, T)
        recent_returns = returns_matrix[-window:]
        recent_probs = regime_probs[-window:] if len(regime_probs) >= window else regime_probs

        # Stress-weight: upweight high-vol observations
        weights = np.array(recent_probs[-len(recent_returns):], dtype=np.float64)
        weights = weights / weights.sum() * len(weights)  # normalize to preserve scale

        # Weighted covariance
        mean_r = np.average(recent_returns, axis=0, weights=weights)
        demeaned = recent_returns - mean_r
        weighted_cov = (demeaned.T * weights) @ demeaned / (weights.sum() - 1)
        annual_cov: np.ndarray = weighted_cov * TRADING_DAYS_PER_YEAR
    else:
        # Normal regime: use long window with Ledoit-Wolf shrinkage
        window = min(long_window, T)
        recent_returns = returns_matrix[-window:]
        daily_cov: np.ndarray = _apply_ledoit_wolf(recent_returns)
        annual_cov = daily_cov * TRADING_DAYS_PER_YEAR

    # PSD adjustment
    eigenvalues = np.linalg.eigvalsh(annual_cov)
    if eigenvalues.min() < -1e-10:
        eigvals, eigvecs = np.linalg.eigh(annual_cov)
        eigvals = np.maximum(eigvals, 1e-10)
        annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T

    return annual_cov


def _maybe_regime_condition_cov(
    db: AsyncSession,
    returns_matrix: np.ndarray,
    fallback_cov: np.ndarray,
    config: dict[str, Any] | None,
) -> np.ndarray | None:
    """Try to apply regime-conditioned covariance. Returns None if regime data unavailable.

    This is a sync helper that reads the latest regime_probs from the most recent
    PortfolioSnapshot. If no regime data exists (regime_fit never ran), returns None
    and the caller uses standard covariance (silent fallback per spec).
    """
    # We need regime_probs from the latest snapshot. Since this function is called
    # from an async context but the data is already in memory from portfolio_eval,
    # we query the DB synchronously via the async session's sync_session.
    # However, since we're already in async context, we'll do a lightweight check.

    # Instead of querying here (which would require await), we check if regime_probs
    # were passed through config. The caller (model_portfolios.py) will inject them.
    if not config:
        return None

    regime_probs_list = config.get("_regime_probs")
    if not regime_probs_list:
        return None

    regime_probs = np.array(regime_probs_list, dtype=np.float64)
    if len(regime_probs) < 21:
        return None

    # Trim regime_probs to match returns_matrix length
    T = returns_matrix.shape[0]
    if len(regime_probs) > T:
        regime_probs = regime_probs[-T:]
    elif len(regime_probs) < T:
        # Pad with neutral (0.5) for missing early observations
        pad = np.full(T - len(regime_probs), 0.5)
        regime_probs = np.concatenate([pad, regime_probs])

    return compute_regime_conditioned_cov(returns_matrix, regime_probs)


# ── Drift queries ────────────────────────────────────────────────────


async def compute_drift(
    db: AsyncSession,
    profile: str,
    as_of_date: date | None = None,
    min_trade_threshold: float = 0.005,
    config: dict[str, Any] | None = None,
) -> DriftReport:
    """Compute drift for all blocks in a profile.

    Queries PortfolioSnapshot, StrategicAllocation, TacticalPosition,
    then delegates to pure compute_block_drifts().

    Returns a DriftReport.
    """
    from quant_engine.drift_service import (
        DriftReport,
        compute_block_drifts,
        resolve_drift_thresholds,
    )

    if as_of_date is None:
        as_of_date = date.today()

    maintenance_trigger, urgent_trigger = resolve_drift_thresholds(config)

    snap_stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    snap_result = await db.execute(snap_stmt)
    snapshot = snap_result.scalar_one_or_none()

    if snapshot is None or not snapshot.weights:
        return DriftReport(
            profile=profile,
            as_of_date=as_of_date,
            blocks=[],
            max_drift_pct=0.0,
            overall_status="ok",
            rebalance_recommended=False,
            estimated_turnover=0.0,
            maintenance_trigger=maintenance_trigger,
            urgent_trigger=urgent_trigger,
        )

    current_weights: dict[str, float] = {
        k: float(v) for k, v in snapshot.weights.items()
    }

    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= as_of_date,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= as_of_date),
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    strategic = {a.block_id: float(a.target_weight) for a in alloc_result.scalars().all()}

    tact_stmt = (
        select(TacticalPosition)
        .where(
            TacticalPosition.profile == profile,
            TacticalPosition.valid_from <= as_of_date,
        )
        .where(
            (TacticalPosition.valid_to.is_(None))
            | (TacticalPosition.valid_to >= as_of_date),
        )
    )
    tact_result = await db.execute(tact_stmt)
    tactical = {t.block_id: float(t.overweight) for t in tact_result.scalars().all()}

    target_weights: dict[str, float] = {}
    for block_id in set(strategic.keys()) | set(tactical.keys()):
        target_weights[block_id] = strategic.get(block_id, 0.0) + tactical.get(block_id, 0.0)

    drifts = compute_block_drifts(
        current_weights, target_weights,
        maintenance_trigger, urgent_trigger,
    )

    max_abs = max((abs(d.absolute_drift) for d in drifts), default=0.0)

    if any(d.status == "urgent" for d in drifts):
        overall = "urgent"
    elif any(d.status == "maintenance" for d in drifts):
        overall = "maintenance"
    else:
        overall = "ok"

    meaningful_trades = [
        abs(d.absolute_drift) for d in drifts
        if abs(d.absolute_drift) >= min_trade_threshold
    ]
    turnover = sum(meaningful_trades) / 2

    rebalance_recommended = overall != "ok" and turnover >= 0.01

    return DriftReport(
        profile=profile,
        as_of_date=as_of_date,
        blocks=[d for d in drifts if d.status != "ok"],
        max_drift_pct=round(max_abs, 6),
        overall_status=overall,
        rebalance_recommended=rebalance_recommended,
        estimated_turnover=round(turnover, 6),
        maintenance_trigger=maintenance_trigger,
        urgent_trigger=urgent_trigger,
    )


# ── Peer comparison queries ──────────────────────────────────────────


def compare(
    db: Session,
    *,
    fund_id: uuid.UUID,
    block_id: str,
    aum_min: Decimal | None = None,
    aum_max: Decimal | None = None,
    config: dict[str, Any] | None = None,
) -> PeerComparison:
    """Rank a fund against its peers within a block.

    Queries Fund and FundRiskMetrics, then ranks by manager_score.
    Returns a PeerComparison.
    """
    from quant_engine.peer_comparison_service import PeerComparison, PeerRank

    stmt = select(Fund).where(
        Fund.block_id == block_id,
        Fund.is_active.is_(True),
        Fund.approval_status == "approved",
    )

    if aum_min is not None:
        stmt = stmt.where(Fund.aum_usd >= aum_min)
    if aum_max is not None:
        stmt = stmt.where(Fund.aum_usd <= aum_max)

    funds_result = db.execute(stmt)
    funds = list(funds_result.scalars().all())

    if not funds:
        return PeerComparison(target_fund_id=fund_id, block_id=block_id)

    peer_fund_ids = [f.fund_id for f in funds]

    risk_stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id.in_(peer_fund_ids))
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc())
        .distinct(FundRiskMetrics.instrument_id)
    )
    risk_result = db.execute(risk_stmt)
    risk_map = {r.instrument_id: r for r in risk_result.scalars().all()}

    scored: list[dict[str, Any]] = []
    for f in funds:
        risk = risk_map.get(f.fund_id)
        scored.append({
            "fund_id": f.fund_id,
            "fund_name": f.name,
            "manager_score": float(risk.manager_score) if risk and risk.manager_score else None,
            "sharpe_1y": float(risk.sharpe_1y) if risk and risk.sharpe_1y else None,
            "return_1y": float(risk.return_1y) if risk and risk.return_1y else None,
        })

    scored.sort(key=lambda s: float(s["manager_score"]) if s["manager_score"] is not None else -999.0, reverse=True)

    peers: list[PeerRank] = []
    target_rank = None
    for i, s in enumerate(scored, 1):
        peer = PeerRank(
            fund_id=uuid.UUID(str(s["fund_id"])),
            fund_name=str(s["fund_name"]),
            manager_score=float(s["manager_score"]) if s["manager_score"] is not None else None,
            sharpe_1y=float(s["sharpe_1y"]) if s["sharpe_1y"] is not None else None,
            return_1y=float(s["return_1y"]) if s["return_1y"] is not None else None,
            rank=i,
            peer_count=len(scored),
        )
        peers.append(peer)
        if s["fund_id"] == fund_id:
            target_rank = i

    return PeerComparison(
        target_fund_id=fund_id,
        block_id=block_id,
        peers=peers,
        target_rank=target_rank,
        peer_count=len(scored),
    )


# ── Rebalance queries ────────────────────────────────────────────────


async def create_system_rebalance_event(
    db: AsyncSession,
    profile: str,
    event_type: str,
    trigger_reason: str,
    weights_before: dict[str, Any] | None = None,
    cvar_before: float | None = None,
    actor_source: str = "system",
) -> RebalanceEvent:
    """Create a rebalance event generated by the system (not manual)."""
    event = RebalanceEvent(
        profile=profile,
        event_date=date.today(),
        event_type=event_type,
        trigger_reason=trigger_reason,
        weights_before=weights_before,
        cvar_before=Decimal(str(round(cvar_before, 6))) if cvar_before is not None else None,
        status="pending",
        actor_source=actor_source,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    logger.info(
        "System rebalance event created",
        event_id=str(event.event_id),
        profile=profile,
        event_type=event_type,
        actor_source=actor_source,
    )
    return event


async def process_cascade(
    db: AsyncSession,
    profile: str,
    trigger_status: str,
    cvar_utilized_pct: float,
    consecutive_breach_days: int,
    cvar_current: float | None = None,
    current_weights: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> CascadeResult:
    """Process the rebalance cascade for a profile.

    Queries PortfolioSnapshot for previous status, delegates to
    determine_cascade_action(), creates event if needed.

    Returns a CascadeResult.
    """
    from quant_engine.rebalance_service import CascadeResult, determine_cascade_action

    stmt = (
        select(PortfolioSnapshot.trigger_status)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    previous_status = result.scalar_one_or_none()

    event_type, reason = determine_cascade_action(
        trigger_status,
        previous_status,
        cvar_utilized_pct,
        consecutive_breach_days,
        profile,
        config=config,
    )

    if event_type is None:
        return CascadeResult(
            previous_status=previous_status or "ok",
            new_status=trigger_status,
            event_created=False,
        )

    event = await create_system_rebalance_event(
        db,
        profile=profile,
        event_type=event_type,
        trigger_reason=reason or "",
        weights_before=current_weights,
        cvar_before=cvar_current,
        actor_source="system",
    )

    return CascadeResult(
        previous_status=previous_status or "ok",
        new_status=trigger_status,
        event_created=True,
        event_id=event.event_id,
        reason=reason,
    )
