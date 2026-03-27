"""Black-Litterman expected returns model.

Pure sync. Zero I/O. Config via parameters.

Implements the canonical Black-Litterman (1992) posterior:
    1. Compute market-implied returns: pi = lambda * Sigma * w_mkt
    2. If no views: return pi (equilibrium returns)
    3. Build P, Q, Omega from IC views
    4. Posterior: mu_BL = inv(inv(tau*Sigma) + P'*inv(Omega)*P) *
                          (inv(tau*Sigma)*pi + P'*inv(Omega)*Q)
"""

from __future__ import annotations

import numpy as np
import structlog

logger = structlog.get_logger()


def compute_bl_returns(
    sigma: "np.ndarray",
    w_market: "np.ndarray",
    views: "list[dict[str, object]] | None",
    risk_aversion: float = 2.5,
    tau: float = 0.05,
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
        risk_aversion: Lambda — risk aversion coefficient.
        tau: Scalar uncertainty on equilibrium prior.

    Returns:
        (N,) array of BL posterior expected returns.

    """
    n = sigma.shape[0]

    # Normalize w_market to sum to 1 (handles partial coverage)
    w_sum = w_market.sum()
    if w_sum > 0:
        w_mkt = w_market / w_sum
    else:
        w_mkt = np.ones(n) / n

    # Step 1: Market-implied equilibrium returns
    pi = risk_aversion * sigma @ w_mkt

    # Step 2: No views — return equilibrium
    if not views:
        return pi

    # Step 3: Build P (K x N), Q (K,), Omega (K x K)
    P_rows: list[np.ndarray] = []
    Q_list: list[float] = []
    omega_diag: list[float] = []

    for view in views:
        vtype = view.get("type", "absolute")
        q_val = float(view["Q"])
        confidence = float(view.get("confidence", 0.5))
        confidence = max(0.01, min(confidence, 1.0))  # clamp

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

        # Idzorek-simplified omega: variance of the view's prior / confidence
        # omega_k = (p_k' * tau * Sigma * p_k) / confidence
        prior_var = float(p_row @ (tau * sigma) @ p_row)
        omega_k = prior_var / confidence

        P_rows.append(p_row)
        Q_list.append(q_val)
        omega_diag.append(omega_k)

    if not P_rows:
        return pi

    P = np.array(P_rows)       # (K x N)
    Q = np.array(Q_list)       # (K,)
    Omega = np.diag(omega_diag)  # (K x K)

    # Step 4: Posterior
    tau_sigma = tau * sigma
    tau_sigma_inv = np.linalg.inv(tau_sigma)
    Omega_inv = np.diag(1.0 / np.array(omega_diag))

    # M = inv(tau*Sigma)^{-1} + P' Omega^{-1} P
    M = tau_sigma_inv + P.T @ Omega_inv @ P
    M_inv = np.linalg.inv(M)

    mu_bl = M_inv @ (tau_sigma_inv @ pi + P.T @ Omega_inv @ Q)

    logger.info(
        "bl_returns_computed",
        n_assets=n,
        n_views=len(P_rows),
        risk_aversion=risk_aversion,
        tau=tau,
    )

    return mu_bl
