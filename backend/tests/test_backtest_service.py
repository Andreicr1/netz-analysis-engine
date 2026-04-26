"""Tests for quant_engine/backtest_service.py."""

from __future__ import annotations

import numpy as np

from quant_engine.backtest_service import _compute_fold_metrics

# ── F01: fold metrics capture initial-day drawdown ────────────────────


def test_fold_metrics_capture_initial_drawdown():
    """First-day -5% in a fold must register max_drawdown ~= -5%, not 0."""
    returns = np.concatenate([np.array([-0.05]), np.full(62, 0.001)])
    metrics = _compute_fold_metrics(returns)
    assert metrics["max_drawdown"] is not None
    assert metrics["max_drawdown"] <= -0.049
