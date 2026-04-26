"""PR-Q22 regression tests for drift_service.py correctness fixes.

8 tests covering:
- T1a: √window cross-fund consistency
- T1b: batch matches single (window=0.1)
- T1c: batch short-history no crash
- T2: phantom block inf, negative target, NaN weights, window=0
- T3: DTW window pinned
"""

from __future__ import annotations

import types
from unittest.mock import patch

import numpy as np
import pytest

from quant_engine.drift_service import (
    DtwDriftStatus,
    compute_block_drifts,
    compute_dtw_drift,
    compute_dtw_drift_batch,
)

# ═══════════════════════════════════════════════════════════════════
#  Helpers — mock aeon to control DTW behavior
# ═══════════════════════════════════════════════════════════════════


def _mock_aeon_ddtw_and_pairwise(ddtw_fn, pairwise_fn):
    """Create mock aeon module with both ddtw_distance and pairwise_distance."""
    mock_aeon = types.ModuleType("aeon")
    mock_distances = types.ModuleType("aeon.distances")
    mock_distances.ddtw_distance = ddtw_fn
    mock_distances.pairwise_distance = pairwise_fn
    mock_aeon.distances = mock_distances
    return {"aeon": mock_aeon, "aeon.distances": mock_distances}


def _fake_ddtw(f, b, window=None):
    """Simple L1 distance as fake DTW."""
    return float(np.sum(np.abs(f - b)))


def _fake_pairwise(series, method="ddtw", **kwargs):
    """Simple pairwise L1 distance as fake DTW."""
    n = series.shape[0]
    dist = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            dist[i, j] = np.sum(np.abs(series[i] - series[j]))
    return dist


# ═══════════════════════════════════════════════════════════════════
#  TIER 1 — Production-critical
# ═══════════════════════════════════════════════════════════════════


class TestBugT1aSqrtWindowCrossFundConsistency:
    def test_short_history_fund_is_degraded(self):
        """Two funds with identical raw DTW distance get identical scores
        regardless of history length, OR short-history fund is degraded."""
        mocks = _mock_aeon_ddtw_and_pairwise(_fake_ddtw, _fake_pairwise)
        with patch.dict("sys.modules", mocks):
            # Fund A: 504 points → window=63 fits → ok
            fund_a = np.random.default_rng(0).normal(0, 0.01, size=504).tolist()
            # Fund B: 30 points → window=63 doesn't fit → degraded
            fund_b = np.random.default_rng(0).normal(0, 0.01, size=30).tolist()
            bench = np.random.default_rng(1).normal(0, 0.01, size=504).tolist()

            res_a = compute_dtw_drift(fund_a, bench, window=63)
            res_b = compute_dtw_drift(fund_b, bench, window=63)

        assert res_a.status == DtwDriftStatus.ok
        assert res_b.status == DtwDriftStatus.degraded
        assert "insufficient_window" in (res_b.reason or "")


class TestBugT1bBatchMatchesSingleWindow:
    def test_single_and_batch_produce_equal_scores(self):
        """Single and batch DTW produce equal scores for the same fund."""
        mocks = _mock_aeon_ddtw_and_pairwise(_fake_ddtw, _fake_pairwise)
        rng = np.random.default_rng(0)
        fund = rng.normal(0, 0.01, size=200)
        bench = np.random.default_rng(1).normal(0, 0.01, size=200)

        with patch.dict("sys.modules", mocks):
            single = compute_dtw_drift(fund.tolist(), bench.tolist(), window=63)
            batch = compute_dtw_drift_batch(
                fund_returns_matrix=fund.reshape(1, -1),
                benchmark_returns=bench,
                window=63,
            )

        assert single.status == DtwDriftStatus.ok
        assert batch[0].status == DtwDriftStatus.ok
        assert batch[0].score == pytest.approx(single.score, rel=1e-6)


class TestBugT1cBatchShortHistoryNoCrash:
    def test_batch_with_short_fund_matrix_returns_degraded(self):
        """Batch with fund matrix shorter than benchmark does not crash."""
        mocks = _mock_aeon_ddtw_and_pairwise(_fake_ddtw, _fake_pairwise)
        fund_matrix = np.random.default_rng(0).normal(0, 0.01, size=(5, 50))
        bench = np.random.default_rng(1).normal(0, 0.01, size=200)

        with patch.dict("sys.modules", mocks):
            results = compute_dtw_drift_batch(fund_matrix, bench, window=63)

        assert len(results) == 5
        # actual_window=50 < window=63 → all degraded
        assert all(r.status == DtwDriftStatus.degraded for r in results)


# ═══════════════════════════════════════════════════════════════════
#  TIER 2 — Silent corruption + math
# ═══════════════════════════════════════════════════════════════════


class TestBugT2PhantomBlockInf:
    def test_current_nonzero_target_zero_yields_inf(self):
        """current=0.10, target=0 → rel_drift=inf, status=urgent."""
        drifts = compute_block_drifts(
            current_weights={"A": 0.10},
            target_weights={"A": 0.0},
        )
        assert drifts[0].relative_drift == float("inf")
        assert drifts[0].status == "urgent"  # |0.10| >= urgent_trigger=0.10


class TestBugT2NegativeTarget:
    def test_negative_target_yields_proper_signed_ratio(self):
        """target<0 yields proper signed rel_drift."""
        drifts = compute_block_drifts(
            current_weights={"short": -0.10},
            target_weights={"short": -0.05},
        )
        # abs_drift = -0.10 - (-0.05) = -0.05; -0.05 / -0.05 = 1.0
        assert drifts[0].relative_drift == pytest.approx(1.0)


class TestBugT2NanWeightsRaise:
    def test_nan_weights_raise_value_error(self):
        """NaN weights raise ValueError."""
        with pytest.raises(ValueError, match="non-finite weight"):
            compute_block_drifts(
                current_weights={"X": float("nan")},
                target_weights={"X": 0.10},
            )


class TestBugT2WindowZeroDegraded:
    def test_window_zero_returns_degraded(self):
        """window=0 returns degraded, not full-series DTW."""
        fund = [0.01] * 100
        bench = [0.005] * 100
        result = compute_dtw_drift(fund, bench, window=0)
        assert result.status == DtwDriftStatus.degraded
        assert "invalid window" in (result.reason or "")


# ═══════════════════════════════════════════════════════════════════
#  TIER 3 — Observability
# ═══════════════════════════════════════════════════════════════════


class TestBugT3DtwWindowPinned:
    def test_identical_series_produce_near_zero_score(self):
        """Identical 63-point arrays produce DTW score ≈ 0; pins aeon contract."""
        mocks = _mock_aeon_ddtw_and_pairwise(_fake_ddtw, _fake_pairwise)
        f = np.linspace(0, 0.01, 63).tolist()
        with patch.dict("sys.modules", mocks):
            result = compute_dtw_drift(f, f, window=63)
        assert result.status == DtwDriftStatus.ok
        assert result.score < 1e-6
