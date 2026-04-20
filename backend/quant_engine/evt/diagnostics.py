"""EVT diagnostic analytics.

Provides data for Mean Excess Plots and Hill Estimator stability.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MeanExcessPlotData:
    thresholds: np.ndarray
    mean_excesses: np.ndarray


def compute_mean_excess_data(returns: np.ndarray, n_points: int = 50) -> MeanExcessPlotData:
    """Compute mean excess values for a range of thresholds.

    Used to visually identify the linear region of the mean excess plot,
    which indicates the threshold above which the GPD is a good fit.
    """
    clean_returns = returns[~np.isnan(returns)]
    losses = -clean_returns[clean_returns < 0]
    if len(losses) < 20:
        return MeanExcessPlotData(np.array([]), np.array([]))

    sorted_losses = np.sort(losses)
    # Range from 50th percentile to 95th percentile
    u_min = np.quantile(sorted_losses, 0.50)
    u_max = np.quantile(sorted_losses, 0.95)
    
    thresholds = np.linspace(u_min, u_max, n_points)
    mean_excesses = []
    
    for u in thresholds:
        excesses = sorted_losses[sorted_losses > u] - u
        if len(excesses) > 0:
            mean_excesses.append(np.mean(excesses))
        else:
            mean_excesses.append(0.0)
            
    return MeanExcessPlotData(thresholds, np.array(mean_excesses))


@dataclass(frozen=True)
class HillPlotData:
    ks: np.ndarray
    xis: np.ndarray


def compute_hill_plot_data(returns: np.ndarray, min_k: int = 10, max_k: int | None = None) -> HillPlotData:
    """Compute Hill estimates for varying k values."""
    from .pot_gpd import compute_hill_estimator
    
    clean_returns = returns[~np.isnan(returns)]
    losses = -clean_returns[clean_returns < 0]
    if len(losses) < min_k:
        return HillPlotData(np.array([]), np.array([]))
        
    if max_k is None:
        max_k = min(len(losses) - 1, 500)
        
    ks = np.arange(min_k, max_k + 1)
    xis = [compute_hill_estimator(losses, k) for k in ks]
    
    return HillPlotData(ks, np.array(xis))
