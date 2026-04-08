"""Black-Litterman expected returns model.

Pure sync. Zero I/O. Config via parameters.

Implements the canonical Black-Litterman (1992) posterior:
    1. Compute market-implied returns: pi = lambda * Sigma * w_mkt
    2. If no views: return pi (equilibrium returns)
    3. Build P, Q, Omega from IC views
    4. Posterior: mu_BL = inv(inv(tau*Sigma) + P'*inv(Omega)*P) *
                          (inv(tau*Sigma)*pi + P'*inv(Omega)*Q)

Sprint S3 calibrations:
    * ``tau`` is adaptive (≈ 1/T) when the caller supplies the prior
      sample size, defaulting to the 0.05 folklore value otherwise.
    * ``risk_aversion`` (λ) can be resolved from an investor ``mandate``
      via the shared :mod:`quant_engine.mandate_risk_aversion` helper,
      so Conservative / Moderate / Aggressive clients stop collapsing
      onto the same equilibrium returns.
    * Omega follows a proper Idzorek-style mapping: ``confidence=1``
      means the view dominates (ω → 0), ``confidence=0.5`` means the
      view is as uncertain as the prior, ``confidence → 0`` ignores it.
    * On every run we log a He-Litterman (1999) consistency warning
      whenever a view Q is more than 3σ away from its prior-implied
      value P·π — the classic red flag for "IC views fighting the
      equilibrium".
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

from quant_engine.mandate_risk_aversion import resolve_risk_aversion

logger = structlog.get_logger()


# Confidence is clamped into a strictly open interval so the Idzorek
# mapping ω = prior_var · (1 − c) / c never hits division by zero at
# c=0 nor degenerates into ω=0 (singular Omega) at c=1.
_CONFIDENCE_FLOOR = 0.01
_CONFIDENCE_CEIL = 0.99


def compute_bl_returns(
    sigma: "np.ndarray",
    w_market: "np.ndarray",
    views: "list[dict[str, Any]] | None",
    risk_aversion: float | None = 2.5,
    tau: float | None = None,
    sample_size: int | None = None,
    mandate: str | None = None,
) -> "np.ndarray":
    """Compute Black-Litterman posterior expected returns.

    Args:
        sigma: (N x N) annualized covariance matrix.
        w_market: (N,) market equilibrium weights (strategic allocation targets).
        views: List of IC views. Each view is a dict with:
            - type: "absolute" | "relative"
            - asset_idx: int (for absolute views)
            - long_idx: int, short_idx: int (for relative views)
            - Q: float — expected return (or return differential)
            - confidence: float in (0, 1] — maps to omega via Idzorek method
        risk_aversion: λ override. When ``None``, λ is resolved from the
            ``mandate`` argument (or falls back to the moderate default).
            Backwards-compat: historical callers pass ``2.5`` which is
            honoured verbatim.
        tau: Scalar uncertainty on equilibrium prior. When ``None``, τ is
            derived adaptively as ``1 / sample_size`` (see He & Litterman
            1999 §3.2). Falls back to the 0.05 folklore value if
            ``sample_size`` is not supplied.
        sample_size: Number of historical observations used to build the
            prior covariance. Used only to derive an adaptive τ; does not
            affect the posterior otherwise.
        mandate: Investor mandate label (``"conservative"``,
            ``"moderate"``, ``"aggressive"``, …). Resolved through
            :func:`quant_engine.mandate_risk_aversion.resolve_risk_aversion`
            when ``risk_aversion`` is None.

    Returns:
        (N,) array of BL posterior expected returns.
    """
    n = sigma.shape[0]

    # ── Resolve λ ────────────────────────────────────────────────────────
    lambda_risk = resolve_risk_aversion(risk_aversion, mandate)

    # ── Resolve τ ────────────────────────────────────────────────────────
    # He & Litterman (1999) and Meucci (2010) both recommend τ ≈ 1/T: the
    # posterior uncertainty on the prior mean should scale with the sample
    # size used to estimate it. A hardcoded 0.05 silently assumes T=20,
    # which is nonsense for a weekly-rebalanced strategic allocation with
    # 3–5 years of history.
    if tau is None:
        if sample_size is not None and sample_size > 0:
            tau_eff = 1.0 / float(sample_size)
        else:
            tau_eff = 0.05  # legacy fallback
    else:
        tau_eff = float(tau)

    # Normalize w_market to sum to 1 (handles partial coverage)
    w_sum = w_market.sum()
    if w_sum > 0:
        w_mkt = w_market / w_sum
    else:
        w_mkt = np.ones(n) / n

    # Step 1: Market-implied equilibrium returns
    pi = lambda_risk * sigma @ w_mkt

    # Step 2: No views — return equilibrium
    if not views:
        return np.asarray(pi)

    # Step 3: Build P (K x N), Q (K,), Omega (K x K)
    P_rows: list[np.ndarray] = []
    Q_list: list[float] = []
    omega_diag: list[float] = []

    for view in views:
        vtype = view.get("type", "absolute")
        q_val = float(view["Q"])
        conf = view.get("confidence", 0.5)
        confidence = max(_CONFIDENCE_FLOOR, min(float(conf), _CONFIDENCE_CEIL))

        p_row = np.zeros(n)

        if vtype == "absolute":
            idx = int(view["asset_idx"])
            if idx < 0 or idx >= n:
                continue
            p_row[idx] = 1.0
        elif vtype == "relative":
            long_idx = int(view["long_idx"])
            short_idx = int(view["short_idx"])
            if long_idx < 0 or long_idx >= n or short_idx < 0 or short_idx >= n:
                continue
            p_row[long_idx] = 1.0
            p_row[short_idx] = -1.0
        else:
            continue

        # Idzorek-style omega mapping:
        #   ω_k = prior_var · (1 − confidence) / confidence
        # At confidence → 1 the view dominates (ω → 0), at confidence=0.5
        # the view is as uncertain as the prior, at confidence → 0 the
        # view is effectively ignored. The previous formulation
        # (ω = prior_var / confidence) made confidence=1 equal to the
        # prior uncertainty itself — i.e. a "certain" view and the
        # equilibrium were given equal weight, silencing the IC.
        prior_var = float(p_row @ (tau_eff * sigma) @ p_row)
        omega_k = prior_var * (1.0 - confidence) / confidence

        # Numerical guard: keep Omega strictly positive-definite even for
        # degenerate priors (e.g. zero-variance view direction).
        omega_k = max(omega_k, 1e-12)

        P_rows.append(p_row)
        Q_list.append(q_val)
        omega_diag.append(omega_k)

    if not P_rows:
        return np.asarray(pi)

    P = np.array(P_rows)       # (K x N)
    Q = np.array(Q_list)       # (K,)
    omega_arr = np.array(omega_diag)
    Omega = np.diag(omega_arr)  # (K x K)

    # He & Litterman (1999) consistency check: warn whenever a view Q
    # lies more than 3 standard deviations away from its prior-implied
    # value P·π. The standard deviation is the square root of the
    # corresponding diagonal entry of P·Σ·P', i.e. the view's a-priori
    # dispersion. This is the textbook "views fighting the equilibrium"
    # alarm bell — users should know before the posterior produces
    # extreme tilts.
    try:
        prior_view = P @ pi                              # (K,)
        view_cov = P @ sigma @ P.T                       # (K, K)
        view_sigma = np.sqrt(np.maximum(np.diag(view_cov), 0.0))
        residual = np.abs(Q - prior_view)
        threshold = 3.0 * view_sigma
        inconsistent = residual > threshold
        if bool(inconsistent.any()):
            logger.warning(
                "black_litterman_view_inconsistent_with_prior",
                n_flagged=int(inconsistent.sum()),
                max_z=round(
                    float(np.max(residual / np.where(view_sigma > 0, view_sigma, 1.0))),
                    4,
                ),
                threshold_sigma=3.0,
            )
    except Exception as e:  # pragma: no cover — defensive
        logger.debug("he_litterman_check_failed", error=str(e))

    # Step 4: Posterior
    tau_sigma = tau_eff * sigma
    tau_sigma_inv = np.linalg.inv(tau_sigma)
    Omega_inv = np.diag(1.0 / omega_arr)

    # M = inv(tau*Sigma)^{-1} + P' Omega^{-1} P
    M = tau_sigma_inv + P.T @ Omega_inv @ P
    M_inv = np.linalg.inv(M)

    mu_bl = M_inv @ (tau_sigma_inv @ pi + P.T @ Omega_inv @ Q)

    logger.info(
        "bl_returns_computed",
        n_assets=n,
        n_views=len(P_rows),
        risk_aversion=round(lambda_risk, 4),
        tau=round(tau_eff, 6),
        tau_source="adaptive" if tau is None and sample_size else "explicit" if tau is not None else "fallback",
        mandate=mandate,
    )

    return np.asarray(mu_bl)
