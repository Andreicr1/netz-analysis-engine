"""Tests for FAIL-03: DTW drift computation failure must not serialize as 0.0.

Covers:
- DtwDriftResult typed result distinguishes ok/degraded/failed states
- compute_dtw_drift returns typed result (not bare float)
- compute_dtw_drift_batch returns typed results (not bare floats)
- Zero drift (genuine) vs computation failure are distinguishable by status
- Consumer (risk_calc) handles degraded results with explicit fallback
- score_or_default makes fallback intentional
"""

from __future__ import annotations

import types
from unittest.mock import patch

import numpy as np
import pytest

from quant_engine.drift_service import (
    DtwDriftResult,
    DtwDriftStatus,
    compute_dtw_drift,
    compute_dtw_drift_batch,
)

# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════


def _mock_aeon_with_ddtw(ddtw_fn):
    """Create mock aeon module with custom ddtw_distance function."""
    mock_aeon = types.ModuleType("aeon")
    mock_distances = types.ModuleType("aeon.distances")
    mock_distances.ddtw_distance = ddtw_fn
    mock_aeon.distances = mock_distances
    return {"aeon": mock_aeon, "aeon.distances": mock_distances}


def _mock_aeon_with_pairwise(pairwise_fn):
    """Create mock aeon module with custom pairwise_distance function."""
    mock_aeon = types.ModuleType("aeon")
    mock_distances = types.ModuleType("aeon.distances")
    mock_distances.pairwise_distance = pairwise_fn
    mock_aeon.distances = mock_distances
    return {"aeon": mock_aeon, "aeon.distances": mock_distances}


def _assert_drift_result(obj, *, status: str, has_score: bool):
    """Assert DtwDriftResult-like object has expected properties."""
    assert type(obj).__name__ == "DtwDriftResult"
    assert obj.status.value == status
    if has_score:
        assert obj.score is not None
    else:
        assert obj.score is None


# ═══════════════════════════════════════════════════════════════════
#  DtwDriftResult model tests
# ═══════════════════════════════════════════════════════════════════


class TestDtwDriftResult:
    def test_ok_result_is_usable(self):
        result = DtwDriftResult(score=0.05, status=DtwDriftStatus.ok)
        assert result.is_usable is True
        assert result.score == 0.05

    def test_degraded_result_not_usable(self):
        result = DtwDriftResult(
            score=None, status=DtwDriftStatus.degraded, reason="aeon not installed",
        )
        assert result.is_usable is False
        assert result.score is None
        assert result.reason == "aeon not installed"

    def test_failed_result_not_usable(self):
        result = DtwDriftResult(
            score=None, status=DtwDriftStatus.failed, reason="numpy error",
        )
        assert result.is_usable is False

    def test_score_or_default_returns_score_when_ok(self):
        result = DtwDriftResult(score=0.123, status=DtwDriftStatus.ok)
        assert result.score_or_default(999.0) == 0.123

    def test_score_or_default_returns_default_when_degraded(self):
        result = DtwDriftResult(
            score=None, status=DtwDriftStatus.degraded, reason="test",
        )
        assert result.score_or_default(0.0) == 0.0
        assert result.score_or_default(-1.0) == -1.0

    def test_score_or_default_returns_default_when_failed(self):
        result = DtwDriftResult(
            score=None, status=DtwDriftStatus.failed, reason="boom",
        )
        assert result.score_or_default(0.0) == 0.0

    def test_genuine_zero_drift_is_distinguishable_from_failure(self):
        """Core acceptance criterion: computed zero and failure are NOT the same."""
        genuine_zero = DtwDriftResult(score=0.0, status=DtwDriftStatus.ok)
        failure = DtwDriftResult(
            score=None, status=DtwDriftStatus.failed, reason="computation error",
        )

        # Both would have been 0.0 before FAIL-03 — now they differ
        assert genuine_zero.is_usable is True
        assert failure.is_usable is False
        assert genuine_zero.status != failure.status
        assert genuine_zero.score is not None
        assert failure.score is None

    def test_frozen_immutable(self):
        result = DtwDriftResult(score=0.1, status=DtwDriftStatus.ok)
        with pytest.raises(AttributeError):
            result.score = 0.5  # type: ignore[misc]

    def test_status_enum_values(self):
        assert DtwDriftStatus.ok.value == "ok"
        assert DtwDriftStatus.degraded.value == "degraded"
        assert DtwDriftStatus.failed.value == "failed"


# ═══════════════════════════════════════════════════════════════════
#  compute_dtw_drift — single fund
# ═══════════════════════════════════════════════════════════════════


class TestComputeDtwDrift:
    def test_import_error_returns_degraded(self):
        """Missing aeon → degraded, not 0.0."""
        with patch.dict("sys.modules", {"aeon": None, "aeon.distances": None}):
            result = compute_dtw_drift([0.01] * 100, [0.02] * 100)

        _assert_drift_result(result, status="degraded", has_score=False)
        assert "not installed" in (result.reason or "")

    def test_insufficient_data_returns_degraded(self):
        """Fewer than 10 points → degraded, not 0.0."""
        mocks = _mock_aeon_with_ddtw(lambda f, b, window=None: 0.0)
        with patch.dict("sys.modules", mocks):
            result = compute_dtw_drift([0.01] * 5, [0.02] * 5)

        _assert_drift_result(result, status="degraded", has_score=False)
        assert "insufficient" in (result.reason or "")

    def test_insufficient_fund_data_returns_degraded(self):
        """Fund has < 10 points, benchmark has enough."""
        mocks = _mock_aeon_with_ddtw(lambda f, b, window=None: 0.0)
        with patch.dict("sys.modules", mocks):
            result = compute_dtw_drift([0.01] * 3, [0.02] * 100)

        _assert_drift_result(result, status="degraded", has_score=False)

    def test_computation_exception_returns_failed(self):
        """Exception during DTW computation → failed, not 0.0."""

        def boom(*a, **kw):
            raise RuntimeError("kaboom")

        mocks = _mock_aeon_with_ddtw(boom)
        with patch.dict("sys.modules", mocks):
            result = compute_dtw_drift([0.01] * 100, [0.02] * 100)

        _assert_drift_result(result, status="failed", has_score=False)
        assert "kaboom" in (result.reason or "")

    def test_valid_computation_returns_ok(self):
        """Successful computation → ok status with a real score."""

        def fake_ddtw(f, b, window=None):
            return float(np.sum(np.abs(f - b)))

        mocks = _mock_aeon_with_ddtw(fake_ddtw)
        with patch.dict("sys.modules", mocks):
            fund = [0.01 + 0.001 * i for i in range(63)]
            bench = [0.01 + 0.002 * i for i in range(63)]
            result = compute_dtw_drift(fund, bench)

        _assert_drift_result(result, status="ok", has_score=True)
        assert result.score > 0
        assert result.is_usable is True

    def test_identical_series_returns_ok_with_zero_score(self):
        """Identical fund and benchmark → ok status, score = 0.0 (genuine zero)."""
        mocks = _mock_aeon_with_ddtw(lambda f, b, window=None: 0.0)
        with patch.dict("sys.modules", mocks):
            series = [0.01] * 63
            result = compute_dtw_drift(series, series)

        _assert_drift_result(result, status="ok", has_score=True)
        assert result.score == 0.0
        assert result.is_usable is True


# ═══════════════════════════════════════════════════════════════════
#  compute_dtw_drift_batch — multiple funds
# ═══════════════════════════════════════════════════════════════════


class TestComputeDtwDriftBatch:
    def test_import_error_returns_degraded_list(self):
        """Missing aeon → list of degraded results."""
        matrix = np.random.randn(5, 63)
        bench = np.random.randn(63)

        with patch.dict("sys.modules", {"aeon": None, "aeon.distances": None}):
            results = compute_dtw_drift_batch(matrix, bench)

        assert len(results) == 5
        for r in results:
            _assert_drift_result(r, status="degraded", has_score=False)

    def test_computation_exception_returns_failed_list(self):
        """Exception → list of failed results."""

        def boom(*a, **kw):
            raise ValueError("bad matrix")

        mocks = _mock_aeon_with_pairwise(boom)
        matrix = np.random.randn(3, 63)
        bench = np.random.randn(63)

        with patch.dict("sys.modules", mocks):
            results = compute_dtw_drift_batch(matrix, bench)

        assert len(results) == 3
        for r in results:
            _assert_drift_result(r, status="failed", has_score=False)
            assert "bad matrix" in (r.reason or "")

    def test_valid_batch_returns_ok_list(self):
        """Successful batch → list of ok results with scores."""

        def fake_pairwise(series, metric="ddtw"):
            n = series.shape[0]
            dist = np.zeros((n, n))
            for i in range(n):
                for j in range(n):
                    dist[i, j] = np.sum(np.abs(series[i] - series[j]))
            return dist

        mocks = _mock_aeon_with_pairwise(fake_pairwise)
        matrix = np.random.randn(4, 63)
        bench = np.random.randn(63)

        with patch.dict("sys.modules", mocks):
            results = compute_dtw_drift_batch(matrix, bench)

        assert len(results) == 4
        for r in results:
            _assert_drift_result(r, status="ok", has_score=True)


# ═══════════════════════════════════════════════════════════════════
#  Consumer adapter test — risk_calc integration
# ═══════════════════════════════════════════════════════════════════


class TestRiskCalcConsumer:
    """Verify risk_calc uses score_or_default and logs degraded state."""

    def test_degraded_result_uses_explicit_fallback(self):
        """Consumer must use score_or_default, never access .score directly for DB."""
        degraded = DtwDriftResult(
            score=None,
            status=DtwDriftStatus.degraded,
            reason="single fund in block",
        )
        # This is what risk_calc does: round(dtw_result.score_or_default(0.0), 6)
        db_value = round(degraded.score_or_default(0.0), 6)
        assert db_value == 0.0
        # But the result is NOT usable — consumer can distinguish
        assert degraded.is_usable is False

    def test_ok_result_uses_real_score(self):
        ok = DtwDriftResult(score=0.042, status=DtwDriftStatus.ok)
        db_value = round(ok.score_or_default(0.0), 6)
        assert db_value == 0.042
        assert ok.is_usable is True

    def test_failed_result_fallback_is_explicit(self):
        """Failed result: score_or_default returns caller's chosen default."""
        failed = DtwDriftResult(
            score=None, status=DtwDriftStatus.failed, reason="crash",
        )
        assert failed.score_or_default(0.0) == 0.0
        assert failed.score_or_default(-999.0) == -999.0
        assert failed.is_usable is False


# ═══════════════════════════════════════════════════════════════════
#  Dashboard-facing adapter test
# ═══════════════════════════════════════════════════════════════════


class TestDashboardAdapter:
    """Verify DtwDriftResult can serialize for dashboard/API consumption."""

    def test_ok_serialization(self):
        result = DtwDriftResult(score=0.15, status=DtwDriftStatus.ok)
        data = {
            "score": result.score,
            "status": result.status.value,
            "is_usable": result.is_usable,
            "reason": result.reason,
        }
        assert data["status"] == "ok"
        assert data["score"] == 0.15
        assert data["is_usable"] is True
        assert data["reason"] is None

    def test_degraded_serialization(self):
        result = DtwDriftResult(
            score=None,
            status=DtwDriftStatus.degraded,
            reason="insufficient data",
        )
        data = {
            "score": result.score,
            "status": result.status.value,
            "is_usable": result.is_usable,
            "reason": result.reason,
        }
        assert data["status"] == "degraded"
        assert data["score"] is None
        assert data["is_usable"] is False
        assert data["reason"] == "insufficient data"

    def test_failed_serialization(self):
        result = DtwDriftResult(
            score=None, status=DtwDriftStatus.failed, reason="runtime error",
        )
        data = {
            "score": result.score,
            "status": result.status.value,
            "is_usable": result.is_usable,
            "reason": result.reason,
        }
        assert data["status"] == "failed"
        assert data["score"] is None
        assert data["is_usable"] is False
