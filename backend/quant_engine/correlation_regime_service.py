"""Correlation regime analysis — rolling correlation, eigenvalue concentration, diversification ratio.

Pure sync, no I/O, config as parameter.
Includes Marchenko-Pastur denoising and Ledoit-Wolf shrinkage.
Same pattern as attribution_service.py, cvar_service.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Default config
_DEFAULT_WINDOW_DAYS = 60
_DEFAULT_BASELINE_WINDOW_DAYS = 504  # ~2 years
_DEFAULT_CONTAGION_THRESHOLD = 0.3
_DEFAULT_CONCENTRATION_MODERATE = 0.6
_DEFAULT_CONCENTRATION_HIGH = 0.8
_DEFAULT_DR_ALERT_THRESHOLD = 1.2
_DEFAULT_MIN_OBSERVATIONS = 45
_DEFAULT_ABSORPTION_WARNING = 0.80
_DEFAULT_ABSORPTION_CRITICAL = 0.90


@dataclass(frozen=True, slots=True)
class PairCorrelation:
    """Correlation between two instruments."""

    index_a: int
    index_b: int
    current_correlation: float
    baseline_correlation: float
    correlation_change: float
    is_contagion: bool


@dataclass(frozen=True, slots=True)
class ConcentrationResult:
    """Eigenvalue concentration analysis."""

    eigenvalues: tuple[float, ...]
    explained_variance_ratios: tuple[float, ...]
    first_eigenvalue_ratio: float
    concentration_status: str  # "diversified" | "moderate_concentration" | "high_concentration"
    absorption_ratio: float
    absorption_status: str  # "normal" | "warning" | "critical"
    mp_threshold: float  # Marchenko-Pastur upper bound lambda_plus
    n_signal_eigenvalues: int  # eigenvalues above mp_threshold


@dataclass(frozen=True, slots=True)
class CorrelationRegimeResult:
    """Full correlation regime analysis result."""

    instrument_count: int
    window_days: int
    correlation_matrix: tuple[tuple[float, ...], ...]
    pair_correlations: tuple[PairCorrelation, ...]
    concentration: ConcentrationResult
    diversification_ratio: float
    dr_alert: bool
    average_correlation: float
    baseline_average_correlation: float
    regime_shift_detected: bool
    sufficient_data: bool = True


def _resolve_config(config: dict[str, Any] | None) -> dict[str, Any]:
    defaults = {
        "window_days": _DEFAULT_WINDOW_DAYS,
        "baseline_window_days": _DEFAULT_BASELINE_WINDOW_DAYS,
        "contagion_threshold": _DEFAULT_CONTAGION_THRESHOLD,
        "concentration_moderate": _DEFAULT_CONCENTRATION_MODERATE,
        "concentration_high": _DEFAULT_CONCENTRATION_HIGH,
        "dr_alert_threshold": _DEFAULT_DR_ALERT_THRESHOLD,
        "min_observations": _DEFAULT_MIN_OBSERVATIONS,
        "apply_denoising": True,
        "apply_shrinkage": True,
        "absorption_warning": _DEFAULT_ABSORPTION_WARNING,
        "absorption_critical": _DEFAULT_ABSORPTION_CRITICAL,
    }
    if config:
        defaults.update(config)
    return defaults


def _ledoit_wolf_constant_correlation(
    returns: np.ndarray,  # type: ignore[type-arg]
) -> tuple[np.ndarray, float]:  # type: ignore[type-arg]
    """Ledoit & Wolf (2003) shrinkage toward a constant-correlation target.

    ``sklearn.covariance.LedoitWolf`` shrinks toward a *scaled identity*
    (``μ·I`` where ``μ = trace(S)/N``), which destroys the correlation
    structure that downstream diversification, regime, and optimization code
    depends on. For stress regimes (short windows, T in the tens) this is
    the difference between a usable covariance and an unusable one.

    This implementation targets the Ledoit-Wolf 2003 constant-correlation
    matrix F, defined as

        F_ii = S_ii
        F_ij = r_bar * sqrt(S_ii * S_jj)    (i ≠ j)

    where ``r_bar`` is the grand mean of the sample correlation matrix's
    off-diagonal entries. The optimal shrinkage intensity δ is derived from
    the paper's closed-form estimator:

        δ = max(0, min(1, κ / T))
        κ = (π - ρ) / γ

    with π, ρ, γ estimated from the sample. The result
    ``Σ_hat = δ·F + (1 − δ)·S`` preserves the empirical correlation
    structure while stabilising eigenvalues at small T.

    Parameters
    ----------
    returns : np.ndarray
        (T, N) de-meaning is handled internally.

    Returns
    -------
    tuple[np.ndarray, float]
        (shrunk_covariance, shrinkage_intensity_delta)
    """
    T, N = returns.shape
    if T < 2 or N < 2:
        # Degenerate — fall back to plain sample covariance.
        cov = np.cov(returns, rowvar=False) if T > 1 else np.zeros((N, N))
        return np.asarray(cov), 0.0

    X = returns - returns.mean(axis=0, keepdims=True)

    # Sample covariance with 1/T bias (LW paper convention, not 1/(T-1)).
    S = (X.T @ X) / T

    var = np.diag(S).copy()
    std = np.sqrt(np.maximum(var, 1e-20))
    std_outer = np.outer(std, std)

    # Sample correlation matrix.
    R = S / std_outer
    np.fill_diagonal(R, 1.0)

    # Average off-diagonal correlation (r_bar).
    if N > 1:
        mask = ~np.eye(N, dtype=bool)
        r_bar = float(R[mask].mean())
    else:
        r_bar = 0.0

    # Constant-correlation target F.
    F = r_bar * std_outer
    np.fill_diagonal(F, var)

    # π̂ — asymptotic variance of √T · s_ij, summed over i, j.
    X2 = X ** 2
    pi_mat = (X2.T @ X2) / T - S ** 2
    pi_hat = float(pi_mat.sum())

    # ρ̂ — asymptotic covariance between √T · s_ij and √T · f_ij.
    # Diagonal contribution:
    rho_diag = float(np.sum(np.diag(pi_mat)))

    # Off-diagonal contribution (LW 2003 eq. A.1):
    # (1/T) Σ_t (x_{t,i}² − s_ii)(x_{t,i}x_{t,j} − s_ij)
    X3 = X ** 3
    term1 = (X3.T @ X) / T - var[:, None] * S      # θ_{ii, ij}
    term2 = (X.T @ X3) / T - S * var[None, :]      # θ_{jj, ij}

    std_ratio_ji = std[None, :] / std[:, None]     # σ_j / σ_i
    std_ratio_ij = std[:, None] / std[None, :]     # σ_i / σ_j

    rho_off_mat = (r_bar / 2.0) * (std_ratio_ji * term1 + std_ratio_ij * term2)
    np.fill_diagonal(rho_off_mat, 0.0)
    rho_off = float(rho_off_mat.sum())
    rho_hat = rho_diag + rho_off

    # γ̂ — squared Frobenius distance between target and sample.
    gamma_hat = float(np.sum((F - S) ** 2))

    if gamma_hat < 1e-12:
        delta = 0.0
    else:
        kappa = (pi_hat - rho_hat) / gamma_hat
        delta = float(np.clip(kappa / T, 0.0, 1.0))

    shrunk = delta * F + (1.0 - delta) * S
    return np.asarray(shrunk), delta


def _shrink_covariance(returns: np.ndarray, regime: str) -> np.ndarray:  # type: ignore[type-arg]
    """Apply constant-correlation Ledoit-Wolf shrinkage and log the intensity.

    Applied to BOTH the recent (potentially stress) window and the baseline
    window — stress windows need shrinkage the most because T is small.
    """
    cov, delta = _ledoit_wolf_constant_correlation(returns)
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])
    logger.debug(
        "ledoit_wolf_constant_correlation_applied",
        regime=regime,
        delta=round(delta, 6),
        T=int(returns.shape[0]),
        N=int(returns.shape[1]) if returns.ndim > 1 else 1,
    )
    return cov


def _marchenko_pastur_denoise(corr_matrix: np.ndarray, q: float) -> np.ndarray:
    """Apply Marchenko-Pastur denoising to correlation matrix.

    Replace eigenvalues below MP upper bound with their average.
    q = N / T (ratio of instruments to observations).
    """
    eigenvalues, eigenvectors = np.linalg.eigh(corr_matrix)
    # Sort descending
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    # MP upper bound: sigma^2 * (1 + sqrt(q))^2
    # For correlation matrix, sigma^2 = 1
    lambda_max = (1 + np.sqrt(q)) ** 2

    # Separate signal and noise
    noise_mask = eigenvalues < lambda_max
    if noise_mask.any():
        noise_avg = float(np.mean(eigenvalues[noise_mask]))
        eigenvalues[noise_mask] = noise_avg

    # Reconstruct
    denoised = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

    # Normalize to correlation matrix (diagonal = 1)
    d = np.sqrt(np.diag(denoised))
    d[d == 0] = 1.0  # avoid division by zero
    denoised = denoised / np.outer(d, d)
    np.fill_diagonal(denoised, 1.0)

    return np.asarray(denoised)


def _compute_concentration(
    corr_matrix: np.ndarray, config: dict[str, Any], q: float = 0.0,
) -> ConcentrationResult:
    """Eigenvalue concentration analysis."""
    eigenvalues = np.linalg.eigvalsh(corr_matrix)
    eigenvalues = np.sort(eigenvalues)[::-1]  # descending
    eigenvalues = np.maximum(eigenvalues, 0)  # numerical stability

    # Marchenko-Pastur upper bound: lambda_plus = (1 + sqrt(q))^2
    mp_threshold = (1 + np.sqrt(q)) ** 2 if q > 0 else 0.0
    n_signal = int(np.sum(eigenvalues > mp_threshold)) if mp_threshold > 0 else len(eigenvalues)

    total = float(np.sum(eigenvalues))
    if total < 1e-10:
        return ConcentrationResult(
            eigenvalues=tuple(float(e) for e in eigenvalues),
            explained_variance_ratios=(1.0,) if len(eigenvalues) == 1 else (),
            first_eigenvalue_ratio=1.0,
            concentration_status="high_concentration",
            absorption_ratio=1.0,
            absorption_status="critical",
            mp_threshold=round(mp_threshold, 6),
            n_signal_eigenvalues=n_signal,
        )

    ratios = eigenvalues / total
    first_ratio = float(ratios[0])

    # Strict greater-than: 0.60 exactly = "diversified"
    if first_ratio > config["concentration_high"]:
        concentration_status = "high_concentration"
    elif first_ratio > config["concentration_moderate"]:
        concentration_status = "moderate_concentration"
    else:
        concentration_status = "diversified"

    # Absorption ratio: top k eigenvalues / total
    # k = N/5 (at least 1), following Kritzman & Li (2010)
    n = len(eigenvalues)
    k = max(1, n // 5)
    absorption_ratio = float(np.sum(eigenvalues[:k]) / total)

    if absorption_ratio > config["absorption_critical"]:
        absorption_status = "critical"
    elif absorption_ratio > config["absorption_warning"]:
        absorption_status = "warning"
    else:
        absorption_status = "normal"

    return ConcentrationResult(
        eigenvalues=tuple(round(float(e), 6) for e in eigenvalues),
        explained_variance_ratios=tuple(round(float(r), 6) for r in ratios),
        first_eigenvalue_ratio=round(first_ratio, 6),
        concentration_status=concentration_status,
        absorption_ratio=round(absorption_ratio, 6),
        absorption_status=absorption_status,
        mp_threshold=round(float(mp_threshold), 6),
        n_signal_eigenvalues=n_signal,
    )


def _compute_diversification_ratio(
    cov_matrix: np.ndarray, weights: np.ndarray,
) -> float:
    """Choueifaty diversification ratio: sum(w_i * sigma_i) / sigma_portfolio."""
    individual_vols = np.sqrt(np.diag(cov_matrix))
    portfolio_var = float(weights @ cov_matrix @ weights)
    if portfolio_var < 1e-20:
        return 1.0
    portfolio_vol = np.sqrt(portfolio_var)
    dr = float(np.dot(weights, individual_vols) / portfolio_vol)
    return round(dr, 6)


def compute_correlation_regime(
    returns_matrix: np.ndarray,
    weights: np.ndarray | None = None,
    config: dict[str, Any] | None = None,
) -> CorrelationRegimeResult:
    """Compute correlation regime analysis.

    Parameters
    ----------
    returns_matrix : np.ndarray
        (T, N) daily returns matrix. T days, N instruments.
        Must be pre-aligned (date intersection, no NaN).
    weights : np.ndarray | None
        Portfolio weights for diversification ratio.
        If None, equal weights assumed.
    config : dict | None
        Config overrides.

    """
    cfg = _resolve_config(config)
    T, N = returns_matrix.shape

    if cfg["min_observations"] > T:
        return CorrelationRegimeResult(
            instrument_count=N,
            window_days=0,
            correlation_matrix=(),
            pair_correlations=(),
            concentration=ConcentrationResult(
                eigenvalues=(), explained_variance_ratios=(),
                first_eigenvalue_ratio=0.0, concentration_status="diversified",
                absorption_ratio=0.0, absorption_status="normal",
                mp_threshold=0.0, n_signal_eigenvalues=0,
            ),
            diversification_ratio=1.0,
            dr_alert=False,
            average_correlation=0.0,
            baseline_average_correlation=0.0,
            regime_shift_detected=False,
            sufficient_data=False,
        )

    if weights is None:
        weights = np.ones(N) / N

    window = min(cfg["window_days"], T)
    recent_returns = returns_matrix[-window:]
    baseline_returns = returns_matrix[:-window] if window < T else returns_matrix

    # Covariance and correlation — recent window
    # NOTE: Recent windows are short (~60d) and frequently capture stress
    # regimes — precisely where shrinkage matters most. Constant-correlation
    # target (Ledoit-Wolf 2003) preserves cross-asset dependence structure;
    # the sklearn default (scaled identity) erases it.
    if cfg["apply_shrinkage"]:
        cov_recent = _shrink_covariance(recent_returns, regime="recent")
    else:
        cov_recent = np.cov(recent_returns, rowvar=False)

    # Ensure cov is 2D
    if cov_recent.ndim == 0:
        cov_recent = np.array([[float(cov_recent)]])

    # Convert to correlation
    d = np.sqrt(np.diag(cov_recent))
    d[d == 0] = 1.0
    corr_recent = cov_recent / np.outer(d, d)
    np.fill_diagonal(corr_recent, 1.0)

    # Denoising
    if cfg["apply_denoising"] and N > 1:
        q = N / len(recent_returns)
        corr_recent = _marchenko_pastur_denoise(corr_recent, q)

    # Baseline correlation — same constant-correlation shrinkage
    if len(baseline_returns) >= cfg["min_observations"]:
        if cfg["apply_shrinkage"]:
            cov_base = _shrink_covariance(baseline_returns, regime="baseline")
        else:
            cov_base = np.cov(baseline_returns, rowvar=False)

        if cov_base.ndim == 0:
            cov_base = np.array([[float(cov_base)]])

        d_base = np.sqrt(np.diag(cov_base))
        d_base[d_base == 0] = 1.0
        corr_baseline = cov_base / np.outer(d_base, d_base)
        np.fill_diagonal(corr_baseline, 1.0)

        if cfg["apply_denoising"] and N > 1:
            q_base = N / len(baseline_returns)
            corr_baseline = _marchenko_pastur_denoise(corr_baseline, q_base)
    else:
        corr_baseline = corr_recent  # fallback

    # Pair correlations
    pairs = []
    for i in range(N):
        for j in range(i + 1, N):
            curr = float(corr_recent[i, j])
            base = float(corr_baseline[i, j])
            change = curr - base
            # Contagion: significant increase AND currently high
            is_contagion = (
                abs(change) > cfg["contagion_threshold"]
                and curr > 0.7
            )
            pairs.append(PairCorrelation(
                index_a=i,
                index_b=j,
                current_correlation=round(curr, 6),
                baseline_correlation=round(base, 6),
                correlation_change=round(change, 6),
                is_contagion=is_contagion,
            ))

    # Concentration — pass q for Marchenko-Pastur threshold
    q = N / len(recent_returns) if len(recent_returns) > 0 else 0.0
    concentration = _compute_concentration(corr_recent, cfg, q=q)

    # Diversification ratio
    dr = _compute_diversification_ratio(cov_recent, weights)
    # Strict less-than: DR = 1.2 exactly is NOT alert
    dr_alert = dr < cfg["dr_alert_threshold"]

    # Average correlations (upper triangle)
    if N > 1:
        upper_tri = corr_recent[np.triu_indices(N, k=1)]
        avg_corr = float(np.mean(upper_tri))
        upper_tri_base = corr_baseline[np.triu_indices(N, k=1)]
        avg_corr_base = float(np.mean(upper_tri_base))
    else:
        avg_corr = 0.0
        avg_corr_base = 0.0

    # Regime shift
    regime_shift = (avg_corr - avg_corr_base) > cfg["contagion_threshold"]

    # Convert correlation matrix to nested tuples
    corr_tuples = tuple(
        tuple(round(float(v), 6) for v in row) for row in corr_recent
    )

    return CorrelationRegimeResult(
        instrument_count=N,
        window_days=window,
        correlation_matrix=corr_tuples,
        pair_correlations=tuple(pairs),
        concentration=concentration,
        diversification_ratio=dr,
        dr_alert=dr_alert,
        average_correlation=round(avg_corr, 6),
        baseline_average_correlation=round(avg_corr_base, 6),
        regime_shift_detected=regime_shift,
    )
