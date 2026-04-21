"""IPCA fitting logic."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from ipca import InstrumentedPCA
import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class IPCAFit:
    """Result of IPCA model fit."""

    gamma: npt.NDArray[np.float64]
    factor_returns: npt.NDArray[np.float64]
    K: int
    intercept: bool
    r_squared: float
    oos_r_squared: float | None
    converged: bool
    n_iterations: int
    dates: pd.DatetimeIndex | None = None

    def factor_returns_for_period(
        self, period_start: date | None, period_end: date | None
    ) -> npt.NDArray[np.float64]:
        """Return factor returns matrix subset for the given period."""
        if self.dates is None:
            # Fallback if dates were not stored
            return self.factor_returns

        mask = np.ones(len(self.dates), dtype=bool)
        if period_start is not None:
            mask &= (self.dates.date >= period_start)
        if period_end is not None:
            mask &= (self.dates.date <= period_end)
        
        return self.factor_returns[:, mask]


def fit_ipca(
    panel_returns: pd.DataFrame,
    characteristics: pd.DataFrame,
    K: int,
    intercept: bool = False,
    max_iter: int = 200,
    tolerance: float = 1e-6,
) -> IPCAFit:
    """Fit Kelly-Pruitt-Su IPCA model."""
    # Ensure MultiIndex alignment
    aligned_returns, aligned_chars = panel_returns.align(characteristics, join="inner")
    
    # Missing characteristic column edge case handled implicitly by pandas alignment,
    # but we can explicitly check:
    if aligned_chars.empty:
        raise ValueError("No matching characteristics for panel_returns")

    # Handle missing values
    mask = aligned_chars.notna().all(axis=1) & aligned_returns.notna().iloc[:, 0]
    aligned_chars = aligned_chars[mask]
    aligned_returns = aligned_returns[mask]

    reg = InstrumentedPCA(
        n_factors=K, intercept=intercept, max_iter=max_iter, iter_tol=tolerance
    )
    
    X = aligned_chars.values
    y = aligned_returns.values
    
    # If the user passed Series or DataFrame with 1 col
    if y.ndim == 2 and y.shape[1] == 1:
        y = y.flatten()

    reg.fit(X=X, y=y, indices=aligned_chars.index)

    gamma = np.asarray(reg.Gamma, dtype=np.float64)
    factor_returns = np.asarray(reg.Factors, dtype=np.float64)
    r_squared_total, r_squared_predictive = reg.score()
    
    if not reg.converged:
        logger.warning("ipca_fit_did_not_converge", K=K, max_iter=max_iter)

    dates = None
    if isinstance(aligned_chars.index, pd.MultiIndex):
        dates = pd.DatetimeIndex(np.unique(aligned_chars.index.get_level_values(1)))

    return IPCAFit(
        gamma=gamma,
        factor_returns=factor_returns,
        K=K,
        intercept=intercept,
        r_squared=float(r_squared_total),
        oos_r_squared=None,
        converged=reg.converged,
        n_iterations=reg.n_iter,
        dates=dates,
    )
