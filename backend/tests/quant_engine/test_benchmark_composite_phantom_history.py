"""Regression tests for S05-F01: composite NAV phantom history + day-level renormalization.

Two complementary defects in compute_composite_nav:
1. Phantom history from earliest-inception start date (Gemini angle)
2. Day-level renormalization without active-weight floor (Opus angle)

Both confirmed by GPT-5.4 + GPT-5.5 dual jury with line-level trace.
Stage 3 triage: TP Tier 1 (Math High / Inst High).
"""

from __future__ import annotations

from datetime import date

import pytest

from quant_engine.benchmark_composite_service import compute_composite_nav


def _nav(nav_date: date, return_1d: float) -> dict:
    """Build a nav dict matching the benchmark_navs input shape."""
    return {"nav_date": nav_date, "return_1d": return_1d}


# ── Regression tests for S05-F01 angle 1 (phantom history) ──────────────


class TestPhantomHistoryElimination:
    """Composite must start at latest common inception, not earliest."""

    def test_composite_starts_at_latest_common_inception_date(self) -> None:
        """Block A 2020-01-01→05; Block B 2020-01-03→05.
        Composite must start 2020-01-03 (3 dates, not 5)."""
        block_weights = {"a": 0.6, "b": 0.4}
        benchmark_navs = {
            "a": [
                _nav(date(2020, 1, 1), 0.01),
                _nav(date(2020, 1, 2), 0.02),
                _nav(date(2020, 1, 3), 0.01),
                _nav(date(2020, 1, 4), 0.005),
                _nav(date(2020, 1, 5), -0.01),
            ],
            "b": [
                _nav(date(2020, 1, 3), 0.003),
                _nav(date(2020, 1, 4), 0.001),
                _nav(date(2020, 1, 5), -0.002),
            ],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert len(result) == 3, f"expected 3 dates >= 2020-01-03, got {len(result)}"
        assert result[0].nav_date == date(2020, 1, 3)
        assert all(r.nav_date >= date(2020, 1, 3) for r in result)

    def test_composite_returns_empty_when_block_missing_from_navs(self) -> None:
        """If a required block has no key in benchmark_navs, composite is undefined."""
        block_weights = {"a": 0.6, "b": 0.4}
        benchmark_navs: dict = {
            "a": [_nav(date(2020, 1, 3), 0.01)],
            # "b" missing entirely
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert result == []

    def test_composite_returns_empty_when_block_has_empty_rows(self) -> None:
        """If a required block has key but empty list, composite is undefined."""
        block_weights = {"a": 0.6, "b": 0.4}
        benchmark_navs = {
            "a": [_nav(date(2020, 1, 3), 0.01)],
            "b": [],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert result == []


# ── Regression tests for S05-F01 angle 2 (day-level renorm threshold) ──


class TestDayLevelRenormThreshold:
    """Day-level renormalization requires >= 50% active weight."""

    def test_low_active_weight_day_skipped(self) -> None:
        """30% active weight (<50% floor) must be skipped, not renormalized.
        Pre-fix: 0.3*0.02 / 0.3 = 0.02 reported as composite.
        Post-fix: day skipped."""
        block_weights = {"a": 0.3, "b": 0.7}
        benchmark_navs = {
            "a": [
                _nav(date(2020, 1, 2), 0.01),
                _nav(date(2020, 1, 3), 0.02),
            ],
            "b": [
                _nav(date(2020, 1, 2), 0.005),
                # Missing 2020-01-03 — 30% active < 50% floor
            ],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        # 2020-01-02 included (full coverage). 2020-01-03 skipped.
        assert len(result) == 1
        assert result[0].nav_date == date(2020, 1, 2)

    def test_high_active_weight_day_renormalized(self) -> None:
        """60% active weight (>=50% floor) IS renormalized.
        Block A 60% present + Block B 40% missing → composite = A's return
        scaled to full weight."""
        block_weights = {"a": 0.6, "b": 0.4}
        benchmark_navs = {
            "a": [
                _nav(date(2020, 1, 2), 0.01),
                _nav(date(2020, 1, 3), 0.02),
            ],
            "b": [
                _nav(date(2020, 1, 2), 0.005),
                # Missing 2020-01-03 — 60% active, above 50% floor
            ],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert len(result) == 2
        # Day 1: full coverage: 0.6*0.01 + 0.4*0.005 = 0.008
        assert result[0].nav_date == date(2020, 1, 2)
        assert result[0].daily_return == pytest.approx(0.008, abs=1e-9)
        # Day 2: 60% active, renormalized: 0.6*0.02 / 0.6 = 0.02
        assert result[1].nav_date == date(2020, 1, 3)
        assert result[1].daily_return == pytest.approx(0.02, abs=1e-9)


# ── Existing-behavior preservation (control tests) ─────────────────────


class TestControlPreservation:
    """Verify unchanged behavior for healthy scenarios."""

    def test_full_coverage_returns_unchanged(self) -> None:
        """All days full coverage → composite = weighted sum."""
        block_weights = {"a": 0.6, "b": 0.4}
        benchmark_navs = {
            "a": [_nav(date(2020, 1, 1), 0.01), _nav(date(2020, 1, 2), 0.02)],
            "b": [_nav(date(2020, 1, 1), 0.005), _nav(date(2020, 1, 2), 0.003)],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert len(result) == 2
        # Day 1: 0.6*0.01 + 0.4*0.005 = 0.008
        assert result[0].daily_return == pytest.approx(0.008, abs=1e-9)
        # Day 2: 0.6*0.02 + 0.4*0.003 = 0.0132
        assert result[1].daily_return == pytest.approx(0.0132, abs=1e-9)

    def test_inception_nav_default_preserved(self) -> None:
        """inception_nav=1000 IS the local convention (F13 REFUTED)."""
        block_weights = {"a": 1.0}
        benchmark_navs = {"a": [_nav(date(2020, 1, 1), 0.0)]}
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert result[0].nav == 1000.0

    def test_zero_weight_sum_returns_empty(self) -> None:
        """Existing guard preserved."""
        block_weights = {"a": 0.0, "b": 0.0}
        benchmark_navs = {
            "a": [_nav(date(2020, 1, 1), 0.01)],
            "b": [_nav(date(2020, 1, 1), 0.01)],
        }
        result = compute_composite_nav(block_weights, benchmark_navs)
        assert result == []
