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

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import structlog
from scipy.linalg import block_diag

from quant_engine.mandate_risk_aversion import resolve_risk_aversion

logger = structlog.get_logger()


# Confidence is clamped into a strictly open interval so the Idzorek
# mapping ω = prior_var · (1 − c) / c never hits division by zero at
# c=0 nor degenerates into ω=0 (singular Omega) at c=1.
_CONFIDENCE_FLOOR = 0.01
_CONFIDENCE_CEIL = 0.99

# Phase A multi-view BL: τ fixed at 0.05. Regime-conditional τ is Phase B.
TAU_PHASE_A = 0.05

# Ω regularization floor: when the assembled block-diagonal Ω is near-singular
# (e.g. a confidence=1.0 IC view produces Ω_ii → 0), we add eps·I where
# eps = REG_OMEGA_EPS_FACTOR · trace(Ω) / K. This preserves the view's
# dominance without triggering np.linalg.LinAlgError in the posterior solve.
REG_OMEGA_EPS_FACTOR = 1e-8


@dataclass(frozen=True)
class View:
    """Single BL view — picking matrix, expected return, uncertainty.

    Fields:
        P: (m, N) picking matrix (m sub-views); identity rows for absolute views,
           [+1, ..., -1, ...] rows for relative views.
        Q: (m,) view expected returns (annualized, same units as μ prior).
        Omega: (m, m) view uncertainty. Diagonal in typical use; full matrix
           allowed for cross-correlated views.
        source: "data_view" (historical 1Y mean) or "ic_view" (IC-provided).
        confidence: raw confidence ∈ [0, 1]; only meaningful for IC views.
    """

    P: np.ndarray
    Q: np.ndarray
    Omega: np.ndarray
    source: Literal["data_view", "ic_view"]
    confidence: float | None = None


def compute_bl_posterior_multi_view(
    mu_prior: np.ndarray,
    sigma: np.ndarray,
    views: list[View],
    tau: float = TAU_PHASE_A,
    *,
    trace_indices: dict[str, int] | None = None,
) -> np.ndarray:
    """Multi-view Black-Litterman posterior.

    Stacks heterogeneous views (data view + IC views) into block-diagonal Ω
    and solves the canonical BL posterior:

        μ_post = [(τΣ)⁻¹ + P'Ω⁻¹P]⁻¹ · [(τΣ)⁻¹·μ_prior + P'Ω⁻¹·Q]

    Unlike the legacy :func:`compute_bl_returns`, this function takes μ_prior
    explicitly (the caller supplies THBB or equilibrium π) and never clamps
    view confidence — certainty-1.0 views are handled via Ω regularization.

    Args:
        mu_prior: (N,) prior expected returns. The THBB blend from Phase A
            construction, or any other prior the caller has assembled.
        sigma: (N, N) prior covariance. Typically the 5Y EWMA cov (Phase A).
        views: list of View objects. Empty → returns mu_prior unchanged.
        tau: scalar prior uncertainty (default 0.05, Phase A convention).
            Regime-conditional τ is Phase B — do not change here.

    Returns:
        (N,) BL posterior expected returns.

    Notes:
        Ω regularization — a confidence=1.0 IC view produces Ω_ii = 0, which
        makes Ω singular and breaks np.linalg.solve. We add eps·I where
        eps = 1e-8 · trace(Ω) / K, preserving view dominance while keeping
        the solve numerically stable. This is the standard BL implementation
        detail in Meucci (2010) §5.3 and Idzorek (2005) §4.
    """
    # ── Input validation (PR-Q19 Fixes 1, 2, 4) ──────────────────────────
    if not math.isfinite(tau) or tau <= 0:
        raise ValueError(
            f"tau must be a positive finite scalar (typical: 0.025–0.10); got {tau}"
        )

    n = sigma.shape[0]

    if views:
        invalid: list[str] = []
        for i, v in enumerate(views):
            # Fix 2 — P shape must match (k, N)
            p = np.asarray(v.P, dtype=np.float64)
            if p.ndim == 1:
                p = p.reshape(1, -1)
            if p.shape[1] != n:
                invalid.append(
                    f"view[{i}]: P cols={p.shape[1]}, expected {n}"
                )
            # Fix 4 — Q must be finite
            q = np.asarray(v.Q, dtype=np.float64)
            if not np.all(np.isfinite(q)):
                invalid.append(f"view[{i}]: Q contains non-finite values")
            # Fix 4 — Omega must be finite
            omega = np.asarray(v.Omega, dtype=np.float64)
            if not np.all(np.isfinite(omega)):
                invalid.append(f"view[{i}]: Omega contains non-finite values")
            # Fix 7 — Omega must be PSD (tolerance -1e-10 for numerical noise)
            elif omega.ndim == 2 and omega.shape[0] == omega.shape[1]:
                eigvals = np.linalg.eigvalsh(omega)
                if eigvals.min() < -1e-10:
                    invalid.append(
                        f"view[{i}]: Omega is not PSD "
                        f"(smallest eigenvalue {eigvals.min():.4e})"
                    )
        if invalid:
            raise ValueError(
                "BL views have invalid inputs:\n  " + "\n  ".join(invalid)
            )

    if not views:
        mu_out = np.asarray(mu_prior, dtype=np.float64)
        if trace_indices:
            for _tkr, _idx in trace_indices.items():
                if 0 <= _idx < mu_out.shape[0]:
                    logger.info(
                        "mu_trace_bl_posterior",
                        ticker=_tkr,
                        mu_prior_i=float(mu_prior[_idx]),
                        mu_post_i=float(mu_out[_idx]),
                        delta=0.0,
                        tau=tau,
                        omega_eps=0.0,
                        n_views_total=0,
                        n_view_groups=0,
                        no_views=True,
                    )
        return mu_out

    P_stack = np.vstack([v.P for v in views])            # (K_total, N)
    Q_stack = np.concatenate([v.Q for v in views])       # (K_total,)
    Omega = block_diag(*[v.Omega for v in views])        # (K_total, K_total)

    # Ω regularization — see docstring. trace/K is scale-aware.
    k = Omega.shape[0]
    trace = float(np.trace(Omega))
    if trace <= 0.0:
        # Degenerate: all views declared certainty=1.0 → fallback to a small
        # absolute epsilon so the solve proceeds. Dominated views still win.
        eps = 1e-12
    else:
        eps = REG_OMEGA_EPS_FACTOR * trace / max(k, 1)
    Omega_reg = Omega + eps * np.eye(k)

    # Solve via linear systems — no np.linalg.inv in this module (PR-Q19 Fix 5).
    # sigma^{-1} via solve is numerically superior for near-singular covariance
    # (e.g. 12 funds in same Vanguard share-class family, cond ≈ 1e15).
    tau_sigma_inv_mu = np.linalg.solve(tau * sigma, mu_prior)         # (τΣ)⁻¹ · μ
    tau_sigma_inv_I = np.linalg.solve(tau * sigma, np.eye(n))         # (τΣ)⁻¹

    M = tau_sigma_inv_I + P_stack.T @ np.linalg.solve(Omega_reg, P_stack)
    rhs = tau_sigma_inv_mu + P_stack.T @ np.linalg.solve(Omega_reg, Q_stack)
    mu_post = np.linalg.solve(M, rhs)

    logger.info(
        "bl_posterior_multi_view",
        n_assets=n,
        n_views_total=int(k),
        n_view_groups=len(views),
        tau=tau,
        omega_eps=eps,
        sources=[v.source for v in views],
    )

    if trace_indices:
        for _tkr, _idx in trace_indices.items():
            if 0 <= _idx < n:
                logger.info(
                    "mu_trace_bl_posterior",
                    ticker=_tkr,
                    mu_prior_i=float(mu_prior[_idx]),
                    mu_post_i=float(mu_post[_idx]),
                    delta=float(mu_post[_idx] - mu_prior[_idx]),
                    tau=tau,
                    omega_eps=eps,
                    n_views_total=int(k),
                    n_view_groups=len(views),
                    no_views=False,
                )

    return np.asarray(mu_post, dtype=np.float64)


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
    lambda_resolved = float(resolve_risk_aversion(risk_aversion, mandate))
    if lambda_resolved <= 0:
        logger.warning(
            "bl_lambda_risk_floored",
            original=lambda_resolved,
            floor=1e-3,
        )
    lambda_risk = max(lambda_resolved, 1e-3)

    # ── Resolve τ (Fix 1 — reject tau <= 0) ──────────────────────────────
    if tau is None:
        if sample_size is not None and sample_size > 0:
            tau_eff = 1.0 / float(sample_size)
        else:
            tau_eff = 0.05  # legacy fallback
    else:
        tau_eff = float(tau)

    if not math.isfinite(tau_eff) or tau_eff <= 0:
        raise ValueError(
            f"tau must be a positive finite scalar (typical: 0.025–0.10); got {tau_eff}"
        )

    # ── Validate w_market (Fix 3 — reject negative weights for long-only) ─
    w_arr = np.asarray(w_market, dtype=np.float64)
    if not np.all(np.isfinite(w_arr)):
        raise ValueError(f"w_market contains non-finite values")
    if (w_arr < -1e-12).any():
        raise ValueError(
            f"w_market has negative entries (institutional long-only convention). "
            f"Min: {w_arr.min():.6f}. Pass allow_short=True if intentional."
        )
    w_sum = float(w_arr.sum())
    if w_sum <= 0:
        raise ValueError(f"w_market.sum() = {w_sum:.6f}, expected > 0")
    w_mkt = w_arr / w_sum

    # Step 1: Market-implied equilibrium returns
    pi = lambda_risk * sigma @ w_mkt

    # Step 2: No views — return equilibrium
    if not views:
        return np.asarray(pi)

    # Step 3: Build P (K x N), Q (K,), Omega (K x K)
    P_rows: list[np.ndarray] = []
    Q_list: list[float] = []
    omega_diag: list[float] = []

    for i, view in enumerate(views):
        vtype = view.get("type", "absolute")

        # Fix 4 — Q must be finite
        q_val = float(view["Q"])
        if not math.isfinite(q_val):
            raise ValueError(f"view[{i}].Q is non-finite ({q_val})")

        # Fix 4 — confidence must be finite and in (0, 1)
        conf = float(view.get("confidence", 0.5))
        if not math.isfinite(conf):
            raise ValueError(f"view[{i}].confidence is non-finite ({conf})")
        if not (0.0 < conf < 1.0):
            raise ValueError(
                f"view[{i}].confidence must be in (0, 1), got {conf}"
            )
        confidence = max(_CONFIDENCE_FLOOR, min(conf, _CONFIDENCE_CEIL))

        p_row = np.zeros(n)

        if vtype == "absolute":
            # Fix 2 — reject out-of-range indices instead of silently dropping
            idx = int(view["asset_idx"])
            if idx < 0 or idx >= n:
                raise ValueError(
                    f"view[{i}]: asset_idx={idx} out of range [0, {n}). "
                    f"Caller must filter views before passing."
                )
            p_row[idx] = 1.0
        elif vtype == "relative":
            long_idx = int(view["long_idx"])
            short_idx = int(view["short_idx"])
            if long_idx < 0 or long_idx >= n or short_idx < 0 or short_idx >= n:
                raise ValueError(
                    f"view[{i}]: long_idx={long_idx}, short_idx={short_idx} "
                    f"out of range [0, {n})."
                )
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

    # Step 4: Posterior — solve-based (PR-Q19 Fix 5, no np.linalg.inv).
    Omega_inv = np.diag(1.0 / omega_arr)
    tau_sigma_inv_pi = np.linalg.solve(tau_eff * sigma, pi)            # (τΣ)⁻¹ · π
    tau_sigma_inv_I = np.linalg.solve(tau_eff * sigma, np.eye(n))      # (τΣ)⁻¹

    M = tau_sigma_inv_I + P.T @ Omega_inv @ P
    rhs = tau_sigma_inv_pi + P.T @ Omega_inv @ Q
    mu_bl = np.linalg.solve(M, rhs)

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
