"""Unit tests for the canonical Brinson-Fachler pure function (PR-Q5).

No DB, no I/O. Exercises the identity, edge cases, and determinism of
``vertical_engines.wealth.attribution.brinson_fachler.brinson_fachler``.
"""

from __future__ import annotations

import pytest

from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler


def test_brinson_fachler_golden_textbook():
    """A hand-worked two-sector example with well-known effects.

    Fund overweighted Tech (60% vs 50%) which returned 10% vs index-wide
    8%, and underweighted Financials (40% vs 50%) which returned 2% vs
    6%. R_B = 0.5*0.08 + 0.5*0.04 = 0.06.

    Tech:
        allocation = (0.6 - 0.5) * (0.08 - 0.06) = +0.002
        selection  = 0.5 * (0.10 - 0.08) = +0.010
        interaction = (0.6 - 0.5) * (0.10 - 0.08) = +0.002
    Financials:
        allocation = (0.4 - 0.5) * (0.04 - 0.06) = +0.002
        selection  = 0.5 * (0.02 - 0.04) = -0.010
        interaction = (0.4 - 0.5) * (0.02 - 0.04) = +0.002
    Totals: alloc=+0.004, select=0.000, interact=+0.004 → active=+0.008
    """
    fund_w = {"Tech": 0.6, "Financials": 0.4}
    fund_r = {"Tech": 0.10, "Financials": 0.02}
    bench_w = {"Tech": 0.5, "Financials": 0.5}
    bench_r = {"Tech": 0.08, "Financials": 0.04}

    result = brinson_fachler(fund_w, fund_r, bench_w, bench_r)

    assert result.allocation_effect == pytest.approx(0.004, abs=1e-9)
    assert result.selection_effect == pytest.approx(0.0, abs=1e-9)
    assert result.interaction_effect == pytest.approx(0.004, abs=1e-9)
    assert result.total_active_return == pytest.approx(0.008, abs=1e-9)


def test_brinson_fachler_identity_sum_matches_active_return():
    """Sum of three effects must equal total_active_return (identity)."""
    fund_w = {"IT": 0.3, "Fin": 0.25, "Health": 0.2, "Energy": 0.15, "Cash": 0.1}
    fund_r = {"IT": 0.12, "Fin": 0.03, "Health": 0.07, "Energy": -0.02, "Cash": 0.01}
    bench_w = {"IT": 0.25, "Fin": 0.3, "Health": 0.2, "Energy": 0.2, "Cash": 0.05}
    bench_r = {"IT": 0.10, "Fin": 0.05, "Health": 0.06, "Energy": -0.05, "Cash": 0.015}

    r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)
    assert r.allocation_effect + r.selection_effect + r.interaction_effect == (
        pytest.approx(r.total_active_return, abs=1e-12)
    )


def test_brinson_fachler_fund_sector_absent_from_benchmark():
    """Fund holds Crypto (5%), benchmark doesn't. Allocation must take
    the full bet. Selection/interaction fall through to the aggregate
    benchmark return fallback."""
    fund_w = {"Equity": 0.95, "Crypto": 0.05}
    fund_r = {"Equity": 0.08, "Crypto": 0.25}
    bench_w = {"Equity": 1.0}
    bench_r = {"Equity": 0.08}

    r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)

    # Benchmark doesn't hold crypto; using R_B = 0.08 as fallback.
    # allocation_crypto = (0.05 - 0) * (0.08 - 0.08) = 0
    # selection_crypto = 0 * (0.25 - 0.08) = 0
    # interaction_crypto = 0.05 * (0.25 - 0.08) = 0.0085
    # Equity: all zero since weights and returns equal on both sides.
    assert r.interaction_effect == pytest.approx(0.0085, abs=1e-9)


def test_brinson_fachler_zero_benchmark_weight_zero_selection_interaction():
    """Sector with zero benchmark weight → selection=0 (w_b=0)."""
    fund_w = {"A": 0.5, "B": 0.5}
    fund_r = {"A": 0.10, "B": 0.05}
    bench_w = {"A": 1.0, "B": 0.0}
    bench_r = {"A": 0.08, "B": 0.04}

    r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)

    b = next(s for s in r.by_sector if s.sector == "B")
    assert b.selection_effect == pytest.approx(0.0, abs=1e-12)
    # interaction = (0.5 - 0) * (0.05 - 0.04) = 0.005
    assert b.interaction_effect == pytest.approx(0.005, abs=1e-12)


def test_brinson_fachler_zero_fund_weight_zero_selection_effect_for_fund_only():
    """Sector with zero fund weight: w_p=0, so selection effect uses w_b
    times (0 - r_b) — that's the selection-from-underweight."""
    fund_w = {"A": 1.0, "B": 0.0}
    fund_r = {"A": 0.10, "B": 0.0}
    bench_w = {"A": 0.5, "B": 0.5}
    bench_r = {"A": 0.08, "B": 0.04}

    r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)
    b = next(s for s in r.by_sector if s.sector == "B")
    # interaction = (0 - 0.5) * (0 - 0.04) = 0.02
    assert b.interaction_effect == pytest.approx(0.02, abs=1e-12)
    # Fund fully underweights B.
    assert b.portfolio_weight == 0.0


def test_brinson_fachler_same_weights_allocation_zero():
    """Fund and benchmark identical weights → allocation effect = 0."""
    fund_w = {"A": 0.6, "B": 0.4}
    bench_w = {"A": 0.6, "B": 0.4}
    fund_r = {"A": 0.10, "B": 0.02}
    bench_r = {"A": 0.08, "B": 0.04}

    r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)
    assert r.allocation_effect == pytest.approx(0.0, abs=1e-12)
    assert r.interaction_effect == pytest.approx(0.0, abs=1e-12)


def test_brinson_fachler_same_returns_selection_zero():
    """Fund and benchmark identical per-sector returns → selection = 0."""
    fund_w = {"A": 0.7, "B": 0.3}
    fund_r = {"A": 0.05, "B": 0.10}
    bench_w = {"A": 0.5, "B": 0.5}
    bench_r = {"A": 0.05, "B": 0.10}

    r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)
    assert r.selection_effect == pytest.approx(0.0, abs=1e-12)
    assert r.interaction_effect == pytest.approx(0.0, abs=1e-12)


def test_brinson_fachler_deterministic():
    """Same inputs → identical outputs on repeated calls."""
    fund_w = {"A": 0.4, "B": 0.6}
    fund_r = {"A": 0.05, "B": 0.08}
    bench_w = {"A": 0.5, "B": 0.5}
    bench_r = {"A": 0.04, "B": 0.07}

    r1 = brinson_fachler(fund_w, fund_r, bench_w, bench_r)
    r2 = brinson_fachler(fund_w, fund_r, bench_w, bench_r)
    assert r1 == r2


def test_brinson_fachler_by_sector_covers_all_sectors():
    """by_sector must include every sector from either side of the comparison."""
    fund_w = {"A": 0.5, "B": 0.5}
    fund_r = {"A": 0.1, "B": 0.1}
    bench_w = {"B": 0.6, "C": 0.4}
    bench_r = {"B": 0.05, "C": 0.08}

    r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)
    sectors = {s.sector for s in r.by_sector}
    assert sectors == {"A", "B", "C"}
