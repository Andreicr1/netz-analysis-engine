"""PR-Q25 regression tests — 11 tests for 6 fixes + invariant.

Each test maps to a confirmed bug from Wave 5 audit of ipca/fit.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_engine.ipca.fit import _detect_convergence_from_stdout, fit_ipca


def _build_panel(n_assets=5, n_periods=24, K=2, seed=0, names=("asset", "date")):
    """Build a synthetic IPCA-compatible panel."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-31", periods=n_periods, freq="ME")
    assets = [f"A{i}" for i in range(n_assets)]
    if names == ("asset", "date"):
        index = pd.MultiIndex.from_product([assets, dates], names=names)
    else:
        index = pd.MultiIndex.from_product(
            [dates, assets] if names[0] == "date" else [assets, dates],
            names=names,
        )
    n = len(index)
    chars = pd.DataFrame(
        rng.normal(0, 1, size=(n, K + 1)),
        index=index,
        columns=[f"char_{i}" for i in range(K + 1)],
    )
    returns = pd.DataFrame(
        rng.normal(0, 0.05, size=(n, 1)),
        index=index,
        columns=["ret"],
    )
    return returns, chars


# ---------------------------------------------------------------------------
# BUG-T2a-MASK: multi-column returns rejected
# ---------------------------------------------------------------------------
class TestBugT2aMask:
    def test_multi_col_returns_rejected(self):
        """fit_ipca rejects multi-column return DataFrames."""
        returns, chars = _build_panel()
        multi_returns = pd.concat(
            [returns, returns.rename(columns={"ret": "ret2"})], axis=1
        )
        with pytest.raises(ValueError, match="single-column"):
            fit_ipca(multi_returns, chars, K=2)

    def test_full_row_nan_mask(self):
        """Row with NaN in single return column is dropped from fit."""
        returns, chars = _build_panel(n_assets=3, n_periods=24)
        returns_with_nan = returns.copy()
        returns_with_nan.iloc[0] = np.nan
        fit = fit_ipca(returns_with_nan, chars, K=2)
        assert fit.gamma.shape[1] == 2
        assert not np.isnan(fit.gamma).any()


# ---------------------------------------------------------------------------
# BUG-T2a-DATEINDEX: date extraction by name
# ---------------------------------------------------------------------------
class TestBugT2aDateIndex:
    def test_date_asset_index_order(self):
        """Index ordered (date, asset) extracts dates correctly via name."""
        returns, chars = _build_panel(names=("date", "asset"))
        fit = fit_ipca(returns, chars, K=2)
        assert fit.dates is not None
        assert isinstance(fit.dates, pd.DatetimeIndex)
        assert fit.dates.is_monotonic_increasing
        assert len(fit.dates) == 24

    def test_unnamed_index_string_level1_raises(self):
        """Unnamed MultiIndex with non-date at level 1 raises clear error."""
        rng = np.random.default_rng(0)
        dates = pd.date_range("2024-01-31", periods=12, freq="ME")
        assets = ["A", "B", "C"]
        # Build (date, asset) WITHOUT 'date' name — positional fallback
        # detects level 1 (asset, string) is not datetime → raises
        index = pd.MultiIndex.from_product([dates, assets])  # no names
        chars = pd.DataFrame(rng.normal(0, 1, size=(36, 3)), index=index)
        returns = pd.DataFrame(
            rng.normal(0, 0.05, size=(36, 1)), index=index, columns=["ret"]
        )
        with pytest.raises(ValueError, match="MultiIndex level 1 must be dates"):
            fit_ipca(returns, chars, K=2)


# ---------------------------------------------------------------------------
# BUG-T2b-CONVERGENCE: degraded flag when convergence undetectable
# ---------------------------------------------------------------------------
class TestBugT2bConvergence:
    def test_convergence_undetectable_marks_degraded(self):
        """When no 'Step N:' lines in stdout, result is degraded."""
        converged, n_iter, degraded, reason = _detect_convergence_from_stdout(
            "", max_iter=200, K=2
        )
        assert converged is False
        assert n_iter == 0
        assert degraded is True
        assert reason is not None
        assert "ipca_convergence_undetectable" in reason

    def test_normal_convergence_not_degraded(self):
        """Normal stdout with Step lines → not degraded."""
        stdout = "Step 1: ...\nStep 2: ...\nStep 3: ...\n"
        converged, n_iter, degraded, reason = _detect_convergence_from_stdout(
            stdout, max_iter=200, K=2
        )
        assert converged is True
        assert n_iter == 3
        assert degraded is False
        assert reason is None

    def test_non_convergence_not_degraded(self):
        """max_iter reached → not converged but NOT degraded (detection worked)."""
        stdout = "Step 1: ...\nStep 2: ...\nStep 3: ...\n"
        converged, n_iter, degraded, reason = _detect_convergence_from_stdout(
            stdout, max_iter=3, K=2
        )
        assert converged is False
        assert n_iter == 3
        assert degraded is False


# ---------------------------------------------------------------------------
# BUG-T2b-FACTORSHAPE: factor_returns shape (K, T)
# ---------------------------------------------------------------------------
class TestBugT2bFactorShape:
    def test_factor_returns_shape_K_by_T(self):
        returns, chars = _build_panel(n_periods=36)
        fit = fit_ipca(returns, chars, K=2)
        assert fit.factor_returns.shape[0] == 2  # K
        assert fit.factor_returns.shape[1] == 36  # T


# ---------------------------------------------------------------------------
# BUG-T3-IMMUTABLE: gamma and factor_returns are read-only
# ---------------------------------------------------------------------------
class TestBugT3Immutable:
    def test_gamma_is_immutable(self):
        returns, chars = _build_panel()
        fit = fit_ipca(returns, chars, K=2)
        with pytest.raises(ValueError, match="read-only"):
            fit.gamma[0, 0] = 999.0

    def test_factor_returns_is_immutable(self):
        returns, chars = _build_panel()
        fit = fit_ipca(returns, chars, K=2)
        with pytest.raises(ValueError, match="read-only"):
            fit.factor_returns[0, 0] = 999.0


# ---------------------------------------------------------------------------
# Invariant: oos_r_squared always None from fit_ipca
# ---------------------------------------------------------------------------
class TestInvariantOosRSquared:
    def test_oos_r_squared_always_none(self):
        returns, chars = _build_panel()
        fit = fit_ipca(returns, chars, K=2)
        assert fit.oos_r_squared is None
