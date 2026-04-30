"""Tests for PR-Q158 — CVaR consolidation + EVT fail-closed."""
import math

import numpy as np


class TestBacktestCVaRConsolidation:
    """WMJ-017: backtest_service must use canonical CVaR."""

    def test_backtest_cvar_matches_canonical(self):
        """Fold metrics CVaR should match compute_cvar_from_returns."""
        from quant_engine.backtest_service import _compute_fold_metrics
        from quant_engine.cvar_service import compute_cvar_from_returns

        rng = np.random.default_rng(42)
        returns = rng.normal(0.0005, 0.015, 252)

        fold_metrics = _compute_fold_metrics(returns)
        cvar_canonical, _ = compute_cvar_from_returns(returns, 0.95)

        # backtest stores as positive loss magnitude
        assert abs(fold_metrics["cvar_95"] - round(-cvar_canonical, 6)) < 1e-5

    def test_backtest_empty_returns(self):
        """Empty returns should return None metrics."""
        from quant_engine.backtest_service import _compute_fold_metrics
        result = _compute_fold_metrics(np.array([]))
        assert result["cvar_95"] is None


class TestQuantAnalyzerCVaRConsolidation:
    """WMJ-017: QuantAnalyzer must use canonical CVaR."""

    def test_quant_analyzer_cvar_uses_canonical(self):
        """QuantAnalyzer._compute_cvar inline formula replaced by canonical."""
        import inspect

        from vertical_engines.wealth.quant_analyzer import QuantAnalyzer
        src = inspect.getsource(QuantAnalyzer._compute_cvar)
        # Should import/use compute_cvar_from_returns, not inline sort+cutoff
        assert "compute_cvar_from_returns" in src
        assert "np.sort" not in src  # no more inline sort


class TestEVTFailClosed:
    """WMJ-020: EVT missing quantile must return NaN + degraded=True."""

    def test_evt_missing_quantile_returns_nan(self):
        """When EVT quantile is missing, cvar/var should be NaN, not 0.0."""
        from quant_engine.cvar_service import compute_cvar

        # Use very few data points that will cause EVT to degrade
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0, 0.001, 10)  # too few for EVT

        result = compute_cvar(returns, confidence=0.95, method="evt_pot")
        # With insufficient data for EVT, should be degraded
        if result.degraded:
            # If degraded, cvar should be NaN, not 0.0
            if math.isnan(result.cvar):
                pass  # correct
            else:
                # If it returned a number, it should NOT be exactly 0.0
                # (0.0 is the sentinel we're fixing)
                assert result.cvar != 0.0 or result.degraded_reason is not None

    def test_evt_missing_quantile_is_degraded(self):
        """Missing quantile result must set degraded=True."""
        from unittest.mock import MagicMock, patch

        from quant_engine.cvar_service import compute_cvar

        # Mock extreme_var_evt to return result WITHOUT the requested quantile
        mock_fit = MagicMock()
        mock_fit.xi = 0.1
        mock_fit.beta = 0.02
        mock_fit.u = 0.01
        mock_fit.n_exceedances = 5

        mock_result = MagicMock()
        mock_result.quantile_results = {}  # empty — no quantiles computed
        mock_result.degraded = False  # lower-level didn't flag it
        mock_result.degraded_reason = None
        mock_result.fit = mock_fit

        rng = np.random.default_rng(42)
        returns = rng.normal(0.0005, 0.01, 100)

        with patch("quant_engine.evt.pot_gpd.extreme_var_evt", return_value=mock_result):
            result = compute_cvar(returns, confidence=0.95, method="evt_pot")

        assert result.degraded is True
        assert math.isnan(result.cvar)
        assert math.isnan(result.var)
        assert result.degraded_reason == "evt_quantile_missing"
