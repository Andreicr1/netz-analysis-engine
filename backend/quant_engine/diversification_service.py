"""Diversification analytics — Effective Number of Bets (Meucci 2009, 2013).

Pure sync computation — no I/O, no DB access, no async, no module-level state.
Deterministic for fixed inputs (closed-form, no randomness).

Consumable by DD ch.5 and construction dashboards. Does not modify
``factor_model_service.py``; factor covariance is passed in by the caller
(typically derived from ``decompose_portfolio()`` output via
``np.cov(factor_returns.T)``).

References
----------
- Meucci, A. (2009). "Managing Diversification". Risk, 22(5), 74-79.
- Meucci, A., Santangelo, A., Deguest, R. (2013). "Measuring Portfolio
  Diversification Based on Optimized Uncorrelated Factors".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

_EPS = 1e-12
_PSD_TOL = -1e-8


@dataclass(frozen=True, slots=True)
class ENBResult:
    """Effective Number of Bets decomposition.

    ``enb_entropy`` (Meucci 2009) and ``enb_minimum_torsion`` (Meucci 2013)
    are both bounded by ``n_factors``. Values close to ``n_factors`` indicate
    balanced diversification across factors; values close to 1 indicate
    concentration.
    """

    enb_entropy: float
    enb_minimum_torsion: float | None
    risk_contributions: NDArray[np.float64]
    factor_exposures: NDArray[np.float64]
    method: Literal["entropy", "minimum_torsion", "both"]
    n_factors: int
    degraded: bool
    degraded_reason: str | None = None


def effective_number_of_bets(
    weights: NDArray[np.float64],
    factor_loadings: NDArray[np.float64],
    factor_cov: NDArray[np.float64],
    method: Literal["entropy", "minimum_torsion", "both"] = "both",
) -> ENBResult:
    """Compute Effective Number of Bets for a portfolio.

    Parameters
    ----------
    weights : (N,) array
        Portfolio weights. Need not sum to 1 (scale-invariant for RC).
    factor_loadings : (N, K) array
        Asset-on-factor loadings matrix ``B``.
    factor_cov : (K, K) array
        Factor covariance matrix ``Sigma_f``. Must be symmetric PSD.
    method : {"entropy", "minimum_torsion", "both"}
        Which ENB metric(s) to compute.

    Returns
    -------
    ENBResult
        Degraded flag set if ``factor_cov`` is non-PSD, ``var_p <= 0``,
        ``B'ΣB`` singular, or any NaN encountered.
    """

    w = np.asarray(weights, dtype=np.float64).ravel()
    B = np.asarray(factor_loadings, dtype=np.float64)
    Sigma_f = np.asarray(factor_cov, dtype=np.float64)

    if B.ndim == 1:
        B = B.reshape(-1, 1)

    K = B.shape[1]

    if Sigma_f.shape != (K, K):
        return _degraded(K, "factor_cov_shape_mismatch")
    if B.shape[0] != w.shape[0]:
        return _degraded(K, "loadings_weights_shape_mismatch")
    if not (np.all(np.isfinite(w)) and np.all(np.isfinite(B)) and np.all(np.isfinite(Sigma_f))):
        return _degraded(K, "nan_in_inputs")

    # Symmetrise and PSD check
    Sigma_f_sym = 0.5 * (Sigma_f + Sigma_f.T)
    eigvals = np.linalg.eigvalsh(Sigma_f_sym)
    if eigvals.min() < _PSD_TOL:
        return _degraded(K, "factor_cov_not_psd")

    p_f = B.T @ w  # (K,)
    var_p = float(p_f @ Sigma_f_sym @ p_f)
    if not np.isfinite(var_p) or var_p <= _EPS:
        return _degraded(K, "non_positive_portfolio_variance", exposures=p_f)

    # Entropy ENB (Meucci 2009)
    rc = _risk_contributions(p_f, Sigma_f_sym, var_p)
    if not np.all(np.isfinite(rc)):
        return _degraded(K, "nan_risk_contributions", exposures=p_f)

    enb_ent = _entropy_enb(rc)

    if K == 1:
        # Edge: single factor, exactly one bet
        single_mt = 1.0 if method in ("minimum_torsion", "both") else None
        return ENBResult(
            enb_entropy=1.0,
            enb_minimum_torsion=single_mt,
            risk_contributions=rc,
            factor_exposures=p_f,
            method=method,
            n_factors=1,
            degraded=False,
            degraded_reason=None,
        )

    enb_mt: float | None = None
    if method in ("minimum_torsion", "both"):
        try:
            t = _minimum_torsion(Sigma_f_sym)
            # q = t^{-T} p_f : bet exposures under uncorrelated basis
            # Portfolio variance = q' I q = ||q||^2
            t_inv_T = np.linalg.inv(t).T
            q = t_inv_T @ p_f
            var_mt = float(q @ q)
            if not np.isfinite(var_mt) or var_mt <= _EPS:
                return ENBResult(
                    enb_entropy=enb_ent,
                    enb_minimum_torsion=None,
                    risk_contributions=rc,
                    factor_exposures=p_f,
                    method=method,
                    n_factors=K,
                    degraded=True,
                    degraded_reason="minimum_torsion_degenerate_variance",
                )
            rc_mt = (q * q) / var_mt
            rc_mt = np.clip(rc_mt, 0.0, 1.0)
            enb_mt = _entropy_enb(rc_mt)
            if not np.isfinite(enb_mt):
                return ENBResult(
                    enb_entropy=enb_ent,
                    enb_minimum_torsion=None,
                    risk_contributions=rc,
                    factor_exposures=p_f,
                    method=method,
                    n_factors=K,
                    degraded=True,
                    degraded_reason="minimum_torsion_nan",
                )
        except (np.linalg.LinAlgError, ValueError):
            return ENBResult(
                enb_entropy=enb_ent,
                enb_minimum_torsion=None,
                risk_contributions=rc,
                factor_exposures=p_f,
                method=method,
                n_factors=K,
                degraded=True,
                degraded_reason="minimum_torsion_singular",
            )

    if method == "entropy":
        enb_mt = None

    return ENBResult(
        enb_entropy=enb_ent,
        enb_minimum_torsion=enb_mt,
        risk_contributions=rc,
        factor_exposures=p_f,
        method=method,
        n_factors=K,
        degraded=False,
        degraded_reason=None,
    )


def _risk_contributions(
    p_f: NDArray[np.float64],
    Sigma_f: NDArray[np.float64],
    var_p: float,
) -> NDArray[np.float64]:
    """Euler RC decomposition: sum_k RC_k = 1."""
    contrib = p_f * (Sigma_f @ p_f)
    rc = contrib / var_p
    # Clip tiny negatives from floating-point to 0 (can occur near-zero exposure).
    rc = np.where(np.abs(rc) < _EPS, 0.0, rc)
    return rc


def _entropy_enb(rc: NDArray[np.float64]) -> float:
    """Shannon-entropy ENB: exp(-Σ RC_k log RC_k). Guards log(0) with EPS."""
    # RC can be slightly negative from numerical noise; take positive part
    # for entropy since H(negative) is undefined. Tiny magnitudes were already
    # zeroed in ``_risk_contributions``.
    rc_pos = np.where(rc > 0.0, rc, 0.0)
    total = rc_pos.sum()
    if total <= _EPS:
        return float("nan")
    rc_norm = rc_pos / total
    entropy = -float(np.sum(rc_norm * np.log(rc_norm + _EPS)))
    return float(np.exp(entropy))


def _minimum_torsion(Sigma_f: NDArray[np.float64]) -> NDArray[np.float64]:
    """Meucci 2013 minimum-torsion matrix t with t·Σ_f·tᵀ = I.

    Closed form (Meucci et al. 2013, eq. 18)::

        t = σ⁻¹ · C^{1/2} · (C^{1/2} · σ⁻² · C^{1/2})^{-1/2} · C^{1/2}

    where σ = diag(√diag(Σ_f)), C = σ⁻¹ Σ_f σ⁻¹.

    Among all invertible matrices that decorrelate factors, MT minimises the
    tracking error of the rotated bets vs original factors, making the bets
    the "closest uncorrelated basis" — more stable than PCA when factors are
    correlated.
    """
    diag_var = np.diag(Sigma_f).copy()
    diag_var = np.where(diag_var > _EPS, diag_var, _EPS)
    sigma = np.sqrt(diag_var)
    sigma_inv = np.diag(1.0 / sigma)
    C = sigma_inv @ Sigma_f @ sigma_inv
    C = 0.5 * (C + C.T)

    C_half = _sym_sqrt(C)
    sigma_inv_sq = np.diag(1.0 / (sigma * sigma))
    inner = C_half @ sigma_inv_sq @ C_half
    inner = 0.5 * (inner + inner.T)
    inner_inv_half = _sym_sqrt(inner, inverse=True)

    t = sigma_inv @ C_half @ inner_inv_half @ C_half
    return t


def _sym_sqrt(M: NDArray[np.float64], inverse: bool = False) -> NDArray[np.float64]:
    """Symmetric matrix square root (or inverse square root) via eigendecomp.

    Eigenvalues are clamped at ``_EPS`` to stay real and strictly positive.
    """
    eigvals, eigvecs = np.linalg.eigh(M)
    eigvals = np.clip(eigvals, _EPS, None)
    if inverse:
        d = 1.0 / np.sqrt(eigvals)
    else:
        d = np.sqrt(eigvals)
    out: NDArray[np.float64] = (eigvecs * d) @ eigvecs.T
    return out


def _degraded(
    K: int,
    reason: str,
    exposures: NDArray[np.float64] | None = None,
) -> ENBResult:
    nan_rc = np.full(K, np.nan, dtype=np.float64)
    exp = exposures if exposures is not None else np.full(K, np.nan, dtype=np.float64)
    return ENBResult(
        enb_entropy=float("nan"),
        enb_minimum_torsion=float("nan"),
        risk_contributions=nan_rc,
        factor_exposures=exp,
        method="both",
        n_factors=K,
        degraded=True,
        degraded_reason=reason,
    )
