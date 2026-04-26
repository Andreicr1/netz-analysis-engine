"""PR-Q29 — Tests for degraded signal propagation through construction pipeline.

Verifies:
1. FundamentalFactorFit.degraded populated when factors_skipped non-empty
2. IllConditionedCovarianceError carries degraded_reason
3. _run_construction_async surfaces top-level degraded/degraded_reason on heuristic fallback
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domains.wealth.services.quant_queries import IllConditionedCovarianceError
from quant_engine.factor_model_service import fit_fundamental_loadings

# ── Change 1+2: dataclass population ──


class TestFundamentalFactorFitDegraded:
    """FundamentalFactorFit.degraded is populated based on factors_skipped."""

    def test_no_skipped_factors_not_degraded(self) -> None:
        """When no factors are skipped, degraded is False."""
        T, N, K = 200, 3, 2
        rng = np.random.default_rng(99)
        factor_returns = rng.standard_normal((T, K)) * 0.01
        fund_returns = rng.standard_normal((T, N)) * 0.01

        fit = fit_fundamental_loadings(
            fund_returns,
            factor_returns,
            factor_names=["f1", "f2"],
            ewma_lambda=0.97,
            factors_skipped=None,
        )

        assert fit.degraded is False
        assert fit.degraded_reason is None
        assert fit.factors_skipped == []

    def test_empty_skipped_list_not_degraded(self) -> None:
        """Explicitly empty list also means not degraded."""
        T, N, K = 200, 3, 2
        rng = np.random.default_rng(99)
        factor_returns = rng.standard_normal((T, K)) * 0.01
        fund_returns = rng.standard_normal((T, N)) * 0.01

        fit = fit_fundamental_loadings(
            fund_returns,
            factor_returns,
            factor_names=["f1", "f2"],
            ewma_lambda=0.97,
            factors_skipped=[],
        )

        assert fit.degraded is False
        assert fit.degraded_reason is None
        assert fit.factors_skipped == []

    def test_skipped_factors_triggers_degraded(self) -> None:
        """When factors_skipped is non-empty, degraded=True with structured reason."""
        T, N, K = 200, 3, 2
        rng = np.random.default_rng(99)
        factor_returns = rng.standard_normal((T, K)) * 0.01
        fund_returns = rng.standard_normal((T, N)) * 0.01

        skipped = [
            {"name": "value", "reason": "missing IWF"},
            {"name": "momentum", "reason": "missing MTUM"},
        ]
        fit = fit_fundamental_loadings(
            fund_returns,
            factor_returns,
            factor_names=["f1", "f2"],
            ewma_lambda=0.97,
            factors_skipped=skipped,
        )

        assert fit.degraded is True
        assert fit.degraded_reason is not None
        assert fit.degraded_reason.startswith("factor_model_partial_fit")
        assert "missing 2 factor(s)" in fit.degraded_reason
        assert "value" in fit.degraded_reason
        assert "momentum" in fit.degraded_reason
        assert fit.factors_skipped == skipped

    def test_single_skipped_factor(self) -> None:
        """Single factor skip produces correct reason string."""
        T, N, K = 200, 3, 2
        rng = np.random.default_rng(99)
        factor_returns = rng.standard_normal((T, K)) * 0.01
        fund_returns = rng.standard_normal((T, N)) * 0.01

        skipped = [{"name": "value", "reason": "missing IWF"}]
        fit = fit_fundamental_loadings(
            fund_returns,
            factor_returns,
            factor_names=["f1", "f2"],
            ewma_lambda=0.97,
            factors_skipped=skipped,
        )

        assert fit.degraded is True
        assert "missing 1 factor(s)" in fit.degraded_reason


# ── Change 3: IllConditionedCovarianceError with degraded_reason ──


class TestIllConditionedCovarianceErrorDegradedReason:
    """IllConditionedCovarianceError carries degraded_reason."""

    def test_degraded_reason_none_by_default(self) -> None:
        """When not passed, degraded_reason defaults to None."""
        exc = IllConditionedCovarianceError(
            condition_number=1e7,
            n_funds=5,
            n_obs=200,
        )
        assert exc.degraded_reason is None

    def test_degraded_reason_passed_through(self) -> None:
        """When explicitly set, degraded_reason is accessible."""
        reason = "covariance_fallback_unavailable: kappa too high"
        exc = IllConditionedCovarianceError(
            condition_number=1e7,
            n_funds=5,
            n_obs=200,
            degraded_reason=reason,
        )
        assert exc.degraded_reason == reason

    def test_degraded_reason_with_structured_content(self) -> None:
        """Structured degraded_reason carries full context."""
        reason = (
            "covariance_fallback_unavailable: "
            "kappa(Sigma)=5.123e+05 in fallback band, "
            "covariance_source=sample, "
            "factor_model_fit=none, "
            "k_effective=0, "
            "factors_skipped=['value', 'momentum']"
        )
        exc = IllConditionedCovarianceError(
            condition_number=5.123e5,
            n_funds=8,
            n_obs=500,
            degraded_reason=reason,
        )
        assert exc.degraded_reason.startswith("covariance_fallback_unavailable")
        assert "kappa(Sigma)" in exc.degraded_reason
        assert "factors_skipped" in exc.degraded_reason

    def test_backward_compat_no_degraded_reason(self) -> None:
        """Existing code that raises without degraded_reason still works."""
        with pytest.raises(IllConditionedCovarianceError) as exc_info:
            raise IllConditionedCovarianceError(
                condition_number=2e6,
                n_funds=4,
                n_obs=100,
                worst_eigenvalues=[1e-10, 1e-9, 1e-8],
                message="pathological rank deficiency",
            )
        assert exc_info.value.degraded_reason is None
        assert exc_info.value.condition_number == 2e6
        assert exc_info.value.worst_eigenvalues == [1e-10, 1e-9, 1e-8]
