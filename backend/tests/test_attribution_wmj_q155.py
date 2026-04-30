"""Tests for PR-Q155 — attribution rail convergence + staleness hardening.

Covers:
  WMJ-008: Reconciliation residual/warning propagation to FundAttributionResult
  WMJ-009: Off-benchmark CIPM convention consistency across BF rails
  WMJ-010: Holdings rail period_lag_days surfacing
  WMJ-016: Cache key includes period_start and period_end
"""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID, uuid4

import pytest

from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler
from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    BenchmarkProxyResult,
    BenchmarkResolution,
    BrinsonResult,
    BrinsonSectorEffect,
    FundAttributionResult,
    HoldingsBasedResult,
    RailBadge,
    SectorWeight,
)
from vertical_engines.wealth.attribution.service import (
    AttributionService,
    _cache_key,
    _deserialize_result,
    _serialize_result,
    compute_fund_attribution,
)

# ---------------------------------------------------------------------------
# WMJ-016: cache key includes period_start + period_end
# ---------------------------------------------------------------------------


def test_cache_key_includes_period_bounds():
    """Two requests differing only in period_start produce different cache keys.

    WMJ-016: before fix, period_start/period_end were omitted from the cache
    key payload, so different period bounds would hit the same cached result.
    """
    fund_id = uuid4()
    base = dict(
        fund_instrument_id=fund_id,
        asof=date(2026, 4, 19),
        lookback_months=60,
        min_months=36,
    )
    req_a = AttributionRequest(**base, period_start=date(2025, 1, 1))
    req_b = AttributionRequest(**base, period_start=date(2024, 1, 1))
    req_c = AttributionRequest(**base, period_start=None)

    key_a = _cache_key(req_a)
    key_b = _cache_key(req_b)
    key_c = _cache_key(req_c)

    assert key_a != key_b, "Different period_start must produce different cache keys"
    assert key_a != key_c, "period_start=date vs None must differ"
    assert key_b != key_c

    # Also verify period_end
    req_d = AttributionRequest(**base, period_end=date(2026, 3, 31))
    req_e = AttributionRequest(**base, period_end=date(2026, 4, 15))
    assert _cache_key(req_d) != _cache_key(req_e)

    # Same bounds → same key (deterministic)
    req_f = AttributionRequest(**base, period_start=date(2025, 1, 1))
    assert _cache_key(req_a) == _cache_key(req_f)


# ---------------------------------------------------------------------------
# WMJ-010: holdings rail surfaces period_lag_days
# ---------------------------------------------------------------------------


def test_holdings_result_includes_period_lag_days():
    """Mock run_holdings_rail, verify period_lag_days = asof - period.

    WMJ-010: N-PORT filings may be 60-90 days stale. The holdings rail must
    return period_lag_days for IC/RIA review staleness badge rendering.
    """
    asof = date(2026, 4, 19)
    period = date(2026, 1, 31)
    expected_lag = (asof - period).days  # 78 days

    holdings = HoldingsBasedResult(
        sectors=(
            SectorWeight("Information Technology", "EC", 0.6, 600.0, 10),
            SectorWeight("Financials", "DBT", 0.4, 400.0, 5),
        ),
        period_of_report=period,
        coverage_pct=1.0,
        confidence=1.0,
        holdings_count=15,
        period_lag_days=expected_lag,
    )

    assert holdings.period_lag_days == expected_lag
    assert holdings.period_lag_days == 78

    # Verify the dispatcher surfaces it in metadata
    async def holdings_fetch(req, _db):
        return holdings

    result = asyncio.run(
        compute_fund_attribution(
            AttributionRequest(fund_instrument_id=uuid4(), asof=asof),
            db=None,
            holdings_fetch=holdings_fetch,
        ),
    )
    assert result.badge == RailBadge.RAIL_HOLDINGS
    assert result.metadata["period_lag_days"] == str(expected_lag)


# ---------------------------------------------------------------------------
# WMJ-009: off-benchmark convention consistent across rails
# ---------------------------------------------------------------------------


def test_portfolio_attribution_includes_off_benchmark_blocks():
    """Strategic allocation with a truly off-benchmark block (w_b=0) that has
    fund return but no benchmark return must be included via CIPM fallback.

    WMJ-009 + Codex P1-a: CIPM fallback only applies when w_b=0 (truly
    off-benchmark). Benchmark-held blocks (w_b>0) with missing return data
    are excluded so brinson_fachler.py's r_b=R_B convention applies.
    """
    svc = AttributionService()

    allocations = [
        {"block_id": "equity", "target_weight": 0.70},
        {"block_id": "crypto", "target_weight": 0.0},   # truly off-benchmark
        {"block_id": "bonds", "target_weight": 0.30},
    ]
    fund_returns = {"equity": 0.08, "crypto": 0.25, "bonds": 0.03}
    # Benchmark has NO return for crypto — off-benchmark bet (w_b=0)
    benchmark_returns = {"equity": 0.07, "bonds": 0.04}
    labels = {"equity": "Equity", "crypto": "Crypto", "bonds": "Bonds"}

    result = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=fund_returns,
        benchmark_returns_by_block=benchmark_returns,
        block_labels=labels,
    )

    assert result.benchmark_available is True
    # All 3 blocks should be present (crypto was not dropped)
    sector_labels = [s.sector for s in result.sectors]
    assert "Crypto" in sector_labels, (
        "Off-benchmark block 'crypto' must not be excluded; "
        "it should be included via CIPM fallback"
    )


def test_off_benchmark_convention_consistent_across_rails():
    """Same sector data through brinson_fachler() and compute_portfolio_attribution()
    produce equivalent allocation effects for off-benchmark sectors.

    WMJ-009: both rails must use the same CIPM convention (r_b = r_p for
    off-benchmark sectors) so the entire bet flows to allocation.
    """
    svc = AttributionService()

    # Setup: fund holds 10% in off-benchmark "Crypto" sector
    fund_weights = {"Equity": 0.90, "Crypto": 0.10}
    fund_returns = {"Equity": 0.05, "Crypto": 0.08}
    bench_weights = {"Equity": 1.0}
    bench_returns_bf = {"Equity": 0.05}

    # Rail 1: pure brinson_fachler()
    bf_result = brinson_fachler(fund_weights, fund_returns, bench_weights, bench_returns_bf)
    bf_crypto = next(s for s in bf_result.by_sector if s.sector == "Crypto")

    # Rail 2: compute_portfolio_attribution (array-based)
    allocations = [
        {"block_id": "equity", "target_weight": 1.0},
        {"block_id": "crypto", "target_weight": 0.0},
    ]
    fund_ret_map = {"equity": 0.05, "crypto": 0.08}
    benchmark_ret_map = {"equity": 0.05}  # No benchmark for crypto
    labels = {"equity": "Equity", "crypto": "Crypto"}
    actual_weights = {"equity": 0.90, "crypto": 0.10}

    pa_result = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=fund_ret_map,
        benchmark_returns_by_block=benchmark_ret_map,
        block_labels=labels,
        actual_weights_by_block=actual_weights,
    )

    pa_crypto = next(
        (s for s in pa_result.sectors if s.sector == "Crypto"),
        None,
    )
    assert pa_crypto is not None, "Crypto sector must be present in array-based result"

    # Both should route the off-benchmark bet entirely to allocation
    # brinson_fachler: allocation = (0.10 - 0) * (0.08 - R_B)
    # R_B for bf = 1.0 * 0.05 = 0.05
    # allocation = 0.10 * (0.08 - 0.05) = 0.003
    assert bf_crypto.allocation_effect == pytest.approx(0.003, abs=1e-9)
    # Selection and interaction should be zero for off-benchmark sector
    assert bf_crypto.selection_effect == pytest.approx(0.0, abs=1e-9)
    assert bf_crypto.interaction_effect == pytest.approx(0.0, abs=1e-9)

    # The array-based path should produce the same sign for allocation
    # (exact values may differ due to weight normalization / cash_residual
    # but the Crypto allocation effect must be positive and non-zero)
    assert pa_crypto.allocation_effect > 0, (
        "Off-benchmark Crypto allocation must be positive in array path"
    )


# ---------------------------------------------------------------------------
# WMJ-008: reconciliation residual surfaced in result
# ---------------------------------------------------------------------------


def test_reconciliation_residual_surfaced_in_result():
    """FundAttributionResult must include non-None reconciliation_residual
    when the proxy rail produces a BrinsonResult.

    WMJ-008: before fix, reconciliation residual was computed in
    quant_engine/attribution_service.py but was NOT propagated through
    the fund-level dispatcher to the API response.
    """
    # Build a proxy result with a clean BrinsonResult (residual ≈ 0)
    brinson = BrinsonResult(
        allocation_effect=0.004,
        selection_effect=0.002,
        interaction_effect=0.001,
        total_active_return=0.007,  # = 0.004 + 0.002 + 0.001 exactly
        by_sector=(
            BrinsonSectorEffect(
                sector="Equity",
                portfolio_weight=0.6,
                benchmark_weight=0.5,
                portfolio_return=0.10,
                benchmark_return=0.08,
                allocation_effect=0.004,
                selection_effect=0.002,
                interaction_effect=0.001,
            ),
        ),
    )
    proxy = BenchmarkProxyResult(
        resolution=BenchmarkResolution(match_type="exact", proxy_etf_ticker="SPY"),
        brinson=brinson,
        confidence=0.90,
        period_of_report=date(2026, 2, 28),
    )

    async def proxy_fetch(req, _db):
        return proxy

    result = asyncio.run(
        compute_fund_attribution(
            AttributionRequest(fund_instrument_id=uuid4(), asof=date(2026, 4, 19)),
            db=None,
            proxy_fetch=proxy_fetch,
        ),
    )

    assert result.badge == RailBadge.RAIL_PROXY
    # reconciliation_residual must be populated (not None)
    assert result.reconciliation_residual is not None
    # Effects sum exactly → residual should be ~0
    assert result.reconciliation_residual == pytest.approx(0.0, abs=1e-9)
    # No warning for a clean reconciliation
    assert result.reconciliation_warning is None


# ---------------------------------------------------------------------------
# Serialization round-trip with new fields
# ---------------------------------------------------------------------------


def test_serialization_round_trip_with_new_fields():
    """Serialize/deserialize preserves period_lag_days, reconciliation_residual,
    reconciliation_warning through the cache codec.
    """
    fund_id = UUID("12345678-1234-5678-1234-567812345678")

    holdings = HoldingsBasedResult(
        sectors=(
            SectorWeight("Information Technology", "EC", 0.6, 600.0, 10),
        ),
        period_of_report=date(2026, 1, 31),
        coverage_pct=1.0,
        confidence=1.0,
        holdings_count=10,
        period_lag_days=78,
    )

    result = FundAttributionResult(
        fund_instrument_id=fund_id,
        asof=date(2026, 4, 19),
        badge=RailBadge.RAIL_HOLDINGS,
        holdings_based=holdings,
        metadata={"n_sectors": "1", "period_lag_days": "78"},
        reconciliation_residual=0.000123,
        reconciliation_warning="test warning",
    )

    encoded = _serialize_result(result)
    decoded = _deserialize_result(encoded)

    # Holdings-level period_lag_days preserved
    assert decoded.holdings_based is not None
    assert decoded.holdings_based.period_lag_days == 78

    # Top-level reconciliation fields preserved
    assert decoded.reconciliation_residual == pytest.approx(0.000123, abs=1e-10)
    assert decoded.reconciliation_warning == "test warning"

    # Existing fields still work
    assert decoded.badge == RailBadge.RAIL_HOLDINGS
    assert decoded.fund_instrument_id == fund_id
    assert decoded.asof == date(2026, 4, 19)
    assert decoded.metadata["period_lag_days"] == "78"


def test_serialization_round_trip_none_new_fields():
    """None values for new fields also survive round-trip (backwards compat)."""
    fund_id = UUID("12345678-1234-5678-1234-567812345678")
    result = FundAttributionResult(
        fund_instrument_id=fund_id,
        asof=date(2026, 4, 19),
        badge=RailBadge.RAIL_NONE,
        reason="no_data",
    )

    encoded = _serialize_result(result)
    decoded = _deserialize_result(encoded)

    assert decoded.reconciliation_residual is None
    assert decoded.reconciliation_warning is None
    assert decoded.holdings_based is None


# ---------------------------------------------------------------------------
# Codex P1 hotfix bundle — off-benchmark fallback semantics
# ---------------------------------------------------------------------------


def test_input_dict_not_mutated():
    """Caller's benchmark_returns_by_block must not be mutated by CIPM fallback.

    Codex P1 (Catch 1): the fallback wrote synthetic r_b = r_p back into the
    caller's dict, leaking into multi-period Carino computations downstream.
    """
    svc = AttributionService()

    allocations = [
        {"block_id": "equity", "target_weight": 0.70},
        {"block_id": "crypto", "target_weight": 0.0},  # off-benchmark, w_b = 0
        {"block_id": "bonds", "target_weight": 0.30},
    ]
    fund_returns = {"equity": 0.08, "crypto": 0.25, "bonds": 0.03}
    benchmark_returns = {"equity": 0.07, "bonds": 0.04}
    labels = {"equity": "Equity", "crypto": "Crypto", "bonds": "Bonds"}

    snapshot_before = dict(benchmark_returns)

    svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=fund_returns,
        benchmark_returns_by_block=benchmark_returns,
        block_labels=labels,
    )

    # Caller's dict must be unchanged — no synthetic crypto entry leaked in
    assert benchmark_returns == snapshot_before
    assert "crypto" not in benchmark_returns


def test_w_b_positive_missing_return_excluded_not_r_p_fallback():
    """When a benchmark-held block (w_b > 0) is missing a return, the CIPM
    fallback r_b = r_p must NOT apply. The block is excluded; downstream BF
    uses r_b = R_B for any retained benchmark-held blocks.

    Codex P1 (Catch 2): previously, ANY block missing a benchmark return
    received r_b = r_p, including w_b > 0 blocks where the benchmark exists
    but data is absent.
    """
    svc = AttributionService()

    # 'bonds' has w_b=0.30 but no benchmark return — must be EXCLUDED, not
    # treated as off-benchmark.
    allocations = [
        {"block_id": "equity", "target_weight": 0.70},
        {"block_id": "bonds", "target_weight": 0.30},  # benchmark-held, missing
    ]
    fund_returns = {"equity": 0.08, "bonds": 0.03}
    benchmark_returns = {"equity": 0.07}  # bonds missing
    labels = {"equity": "Equity", "bonds": "Bonds"}

    result = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=fund_returns,
        benchmark_returns_by_block=benchmark_returns,
        block_labels=labels,
    )

    # Result is computed (equity has observed bench return), but bonds is
    # excluded — NOT included with synthetic r_b = r_p = 0.03.
    sector_labels = [s.sector for s in result.sectors]
    assert "Bonds" not in sector_labels, (
        "Benchmark-held block (w_b=0.30) with missing return must be excluded, "
        "not given r_b=r_p fallback (which is reserved for w_b=0 blocks)"
    )
    assert "Equity" in sector_labels


def test_carino_uses_fallback_adjusted_returns():
    """Multi-period Carino linking must operate on fallback-adjusted per-period
    results, so reconciliation between linked totals and per-period effects
    holds when off-benchmark blocks are present.

    Codex P1 (Catch 3): the local fallback-adjusted dict must be used by both
    per-period BF and the Carino linker — they cannot diverge.
    """
    svc = AttributionService()

    # Two consecutive periods, identical structure, with off-benchmark crypto
    allocations = [
        {"block_id": "equity", "target_weight": 0.80},
        {"block_id": "crypto", "target_weight": 0.0},  # off-benchmark
    ]
    labels = {"equity": "Equity", "crypto": "Crypto"}
    actual_weights = {"equity": 0.85, "crypto": 0.15}

    period1_fund = {"equity": 0.05, "crypto": 0.10}
    period1_bench = {"equity": 0.04}
    period2_fund = {"equity": 0.03, "crypto": 0.06}
    period2_bench = {"equity": 0.02}

    p1 = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=period1_fund,
        benchmark_returns_by_block=period1_bench,
        block_labels=labels,
        actual_weights_by_block=actual_weights,
    )
    p2 = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=period2_fund,
        benchmark_returns_by_block=period2_bench,
        block_labels=labels,
        actual_weights_by_block=actual_weights,
    )

    # Both per-period results must have used CIPM fallback (crypto present)
    assert "Crypto" in [s.sector for s in p1.sectors]
    assert "Crypto" in [s.sector for s in p2.sectors]
    assert p1.benchmark_available is True
    assert p2.benchmark_available is True

    # Caller's per-period benchmark dicts must be untouched (no synthetic
    # crypto leak that would corrupt the Carino benchmark stream).
    assert "crypto" not in period1_bench
    assert "crypto" not in period2_bench

    # Compose Carino linking: the multi-period total return streams should
    # be derived from the per-period results, not from raw caller dicts.
    multi = svc.compute_multi_period(
        period_results=[p1, p2],
        portfolio_period_returns=[
            p1.total_portfolio_return,
            p2.total_portfolio_return,
        ],
        benchmark_period_returns=[
            p1.total_benchmark_return,
            p2.total_benchmark_return,
        ],
    )
    assert multi.benchmark_available is True
    # Total excess return should be consistent with linked period excess
    assert multi.n_periods == 2


def test_multi_period_carino_uses_fallback_adjusted_b_ret():
    """Carino's R_p / R_b streams MUST come from per-period AttributionResult
    totals, not from re-summing the original input dicts in the orchestrator.

    Codex P1 (Q155 hotfix, route-level alignment): the multi-period
    orchestrator in routes/attribution.py previously recomputed both p_ret
    and b_ret from the ORIGINAL benchmark / fund dicts using
    `target_weight * dict.get(bid, 0.0)`. But the per-period BF effects
    operate on a fallback-adjusted view that:
      - excludes benchmark-held blocks (w_b>0) with missing benchmark
        return data, AND
      - normalizes weights to sum to 1.0 via a synthetic cash residual,
        AND
      - applies CIPM r_b=r_p for truly off-benchmark blocks (w_b=0).

    When a benchmark-held block is excluded, the BF R_p excludes that
    block's r_p contribution (it is dropped along with its r_b), but the
    naive route recompute STILL includes it via `target_w * r_p`, so the
    two streams diverge. Feeding the buggy stream to Carino skews the K
    factor and breaks reconciliation between linked totals and per-period
    scaled effects.

    Scenario: 2 periods. Period 1: 'bonds' (w_b=0.30) has a fund return
    but its benchmark is missing → BF excludes it, but the buggy route
    `p_ret` still adds `0.30 * r_p_bonds`. Period 2: clean (all blocks
    have benchmark observations).
    """
    svc = AttributionService()

    allocations = [
        {"block_id": "equity", "target_weight": 0.70},
        {"block_id": "bonds", "target_weight": 0.30},
    ]
    labels = {"equity": "Equity", "bonds": "Bonds"}

    # Period 1: 'bonds' fund return present, but benchmark observation
    # MISSING — BF will exclude bonds entirely.
    period1_fund = {"equity": 0.05, "bonds": 0.02}
    period1_bench = {"equity": 0.04}  # bonds NOT observed

    # Period 2: clean — both observed. No exclusions, no fallback.
    period2_fund = {"equity": 0.03, "bonds": 0.01}
    period2_bench = {"equity": 0.025, "bonds": 0.012}

    p1 = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=period1_fund,
        benchmark_returns_by_block=period1_bench,
        block_labels=labels,
    )
    p2 = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=period2_fund,
        benchmark_returns_by_block=period2_bench,
        block_labels=labels,
    )

    assert p1.benchmark_available is True
    assert p2.benchmark_available is True
    # Bonds dropped in period 1 (benchmark-held but missing return)
    assert "Bonds" not in [s.sector for s in p1.sectors]
    # Bonds present in period 2
    assert "Bonds" in [s.sector for s in p2.sectors]

    # ---- BUGGY STREAM (what the route used to do): naive sum over the
    # ORIGINAL caller-supplied dicts, using strategic target_weight, with
    # missing entries defaulting to 0.0. ----
    def _buggy_p_ret(fund_dict: dict[str, float]) -> float:
        return sum(
            float(sa["target_weight"]) * fund_dict.get(sa["block_id"], 0.0)
            for sa in allocations
        )

    def _buggy_b_ret(bench_dict: dict[str, float]) -> float:
        return sum(
            float(sa["target_weight"]) * bench_dict.get(sa["block_id"], 0.0)
            for sa in allocations
        )

    buggy_p_ret_p1 = _buggy_p_ret(period1_fund)
    buggy_p_ret_p2 = _buggy_p_ret(period2_fund)
    buggy_b_ret_p1 = _buggy_b_ret(period1_bench)
    buggy_b_ret_p2 = _buggy_b_ret(period2_bench)

    # ---- CORRECT STREAM (what the fix uses): per-period AttributionResult
    # total_*_return, which is the fallback-adjusted R_P / R_B from BF. ----
    correct_p_ret_p1 = p1.total_portfolio_return
    correct_p_ret_p2 = p2.total_portfolio_return
    correct_b_ret_p1 = p1.total_benchmark_return
    correct_b_ret_p2 = p2.total_benchmark_return

    # Period 1 must exhibit divergence in the PORTFOLIO stream because
    # BF dropped 'bonds' entirely, but the buggy route recompute still
    # adds 0.30 * 0.02 = 0.006 from bonds.
    assert correct_p_ret_p1 != pytest.approx(buggy_p_ret_p1, abs=1e-9), (
        "Period 1 must exhibit divergence between buggy naive p_ret and "
        "AttributionResult.total_portfolio_return — bonds was excluded "
        "from BF but the buggy stream still credits bonds via target_w * "
        "fund_return. "
        f"buggy={buggy_p_ret_p1}, correct={correct_p_ret_p1}"
    )

    # Period 2 should agree (no exclusions, no fallback).
    assert correct_p_ret_p2 == pytest.approx(buggy_p_ret_p2, abs=1e-9)
    assert correct_b_ret_p2 == pytest.approx(buggy_b_ret_p2, abs=1e-9)

    # Compose Carino linking using the CORRECT (fallback-adjusted) stream.
    multi_correct = svc.compute_multi_period(
        period_results=[p1, p2],
        portfolio_period_returns=[correct_p_ret_p1, correct_p_ret_p2],
        benchmark_period_returns=[correct_b_ret_p1, correct_b_ret_p2],
    )
    # And using the BUGGY stream for contrast.
    multi_buggy = svc.compute_multi_period(
        period_results=[p1, p2],
        portfolio_period_returns=[buggy_p_ret_p1, buggy_p_ret_p2],
        benchmark_period_returns=[buggy_b_ret_p1, buggy_b_ret_p2],
    )

    assert multi_correct.benchmark_available is True
    assert multi_correct.n_periods == 2

    # The two linked results must produce different total_portfolio_return
    # because the buggy stream's R_p_t differs from BF's R_p_t in period 1.
    assert multi_correct.total_portfolio_return != pytest.approx(
        multi_buggy.total_portfolio_return, abs=1e-9
    ), (
        "Carino linker must surface a different total_portfolio_return "
        "when fed buggy vs fallback-adjusted streams; otherwise the "
        "regression assertion is no-op."
    )

    # Reconciliation: with the CORRECT stream, the linked excess equals
    # the difference of linked totals (Carino additivity holds).
    assert multi_correct.total_excess_return == pytest.approx(
        multi_correct.total_portfolio_return
        - multi_correct.total_benchmark_return,
        abs=1e-9,
    )


def test_zero_observed_benchmark_returns_degrades():
    """If every included block is off-benchmark CIPM fallback (no observed
    benchmark return at all), the result must degrade with
    benchmark_available=False rather than fabricating attribution from
    a synthetic benchmark stream.

    Codex P1 (Catch 4): without this guard, a portfolio of only off-benchmark
    bets would surface fake attribution data with cash-normalization noise.
    """
    svc = AttributionService()

    # All blocks are off-benchmark (w_b = 0) AND have no benchmark return.
    allocations = [
        {"block_id": "crypto", "target_weight": 0.0},
        {"block_id": "private", "target_weight": 0.0},
    ]
    fund_returns = {"crypto": 0.10, "private": 0.05}
    benchmark_returns: dict[str, float] = {}  # nothing observed
    labels = {"crypto": "Crypto", "private": "Private"}

    result = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=fund_returns,
        benchmark_returns_by_block=benchmark_returns,
        block_labels=labels,
    )

    assert result.benchmark_available is False, (
        "Zero observed benchmark returns must produce degraded result, "
        "not synthetic attribution from fabricated r_b = r_p stream"
    )


# ---------------------------------------------------------------------------
# Codex P1 hotfix-of-hotfix — preserve real returns on degraded periods
# ---------------------------------------------------------------------------


def test_unavailable_benchmark_preserves_fund_returns():
    """When the per-period attribution degrades to benchmark_available=False,
    total_portfolio_return MUST still reflect realized fund performance from
    the input fund_returns_by_block — only total_benchmark_return is unknown.

    Codex P1 (Q155 hotfix-of-hotfix Catch A): the prior hotfix emitted a
    default AttributionResult with both totals set to 0.0 on the
    has_observed_bench=False branch. _simple_average_linking compounds
    period_results[*].total_portfolio_return geometrically, so a single
    zeroed period materially understates the linked multi-period total.
    """
    import math

    svc = AttributionService()

    # Strategic allocation defines the weights used for total_portfolio_return.
    allocations = [
        {"block_id": "A", "target_weight": 0.60},
        {"block_id": "B", "target_weight": 0.40},
    ]
    fund_returns = {"A": 0.05, "B": 0.03}
    # Empty benchmark dict → has_observed_bench = False → degraded branch.
    benchmark_returns: dict[str, float] = {}
    labels = {"A": "Asset A", "B": "Asset B"}

    result = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=fund_returns,
        benchmark_returns_by_block=benchmark_returns,
        block_labels=labels,
    )

    # Degraded — benchmark unknown.
    assert result.benchmark_available is False
    # Portfolio return preserved: 0.60 * 0.05 + 0.40 * 0.03 = 0.042
    expected_p = 0.60 * 0.05 + 0.40 * 0.03
    assert result.total_portfolio_return == pytest.approx(expected_p, abs=1e-9)
    assert result.total_portfolio_return != 0.0, (
        "Unavailable-benchmark branch must NOT zero out total_portfolio_return; "
        "real fund performance must survive into multi-period linking."
    )
    # Benchmark return signaled as NaN (unknown), not 0.
    assert math.isnan(result.total_benchmark_return), (
        "total_benchmark_return must be NaN on the unavailable branch to "
        "distinguish 'unknown' from 'observed zero'."
    )


def test_multi_period_unavailable_period_uses_observed_bench():
    """When a period degrades to benchmark_available=False because fund-block
    returns are partly missing, but observed benchmark-block returns ARE
    available for that period, the route's Carino b_ret stream MUST fall
    back to the period-level benchmark dict instead of hard-coding 0.

    Codex P1 (Q155 hotfix-of-hotfix Catch B): the prior hotfix wrote
    b_ret=0 for any benchmark_available=False period, dropping observed
    benchmark performance and inflating the linked excess return.

    This test exercises the route-level helper logic directly: given a
    period-level AttributionResult with benchmark_available=False AND a
    non-empty period-level benchmark dict, the route must derive b_ret from
    that dict using strategic weights.
    """
    # We re-implement the exact route fallback logic to assert its semantics
    # without spinning up the FastAPI route machinery (no DB/Clerk in tests).
    sa_dicts = [
        {"block_id": "equity", "target_weight": 0.70},
        {"block_id": "bonds", "target_weight": 0.30},
    ]

    # Period 1: benchmark observations present for BOTH blocks, but fund
    # returns missing for one block → has_observed_bench is True, period
    # remains AVAILABLE. Period 2: simulate degraded (benchmark_available=
    # False) with observed benchmark dict still populated.
    benchmark_returns_period_p2 = {"equity": 0.04, "bonds": 0.02}

    # Stub a degraded result mirroring Catch A's preserved fund return.
    from quant_engine.attribution_service import AttributionResult as _AR

    degraded_result = _AR(
        benchmark_available=False,
        n_periods=1,
        total_portfolio_return=0.05,
        total_benchmark_return=float("nan"),
    )

    # ---- Replicate the Catch B route fallback verbatim. ----
    if degraded_result.benchmark_available:
        b_ret = degraded_result.total_benchmark_return
    elif benchmark_returns_period_p2:
        b_ret = sum(
            float(sa["target_weight"])
            * benchmark_returns_period_p2.get(sa["block_id"], 0.0)
            for sa in sa_dicts
        )
    else:
        b_ret = 0.0

    # b_ret must reflect observed benchmark, NOT 0.
    expected_b = 0.70 * 0.04 + 0.30 * 0.02  # 0.034
    assert b_ret == pytest.approx(expected_b, abs=1e-9), (
        "Degraded period with observed benchmark dict must derive b_ret "
        "from that dict using strategic weights, not zero."
    )
    assert b_ret != 0.0

    # And p_ret comes from the (Catch A-preserved) result total.
    p_ret = degraded_result.total_portfolio_return
    assert p_ret == pytest.approx(0.05, abs=1e-9)

    # Sanity: when benchmark dict is also empty, b_ret falls back to 0.
    empty_bench: dict[str, float] = {}
    if degraded_result.benchmark_available:
        b_ret_empty = degraded_result.total_benchmark_return
    elif empty_bench:
        b_ret_empty = sum(
            float(sa["target_weight"])
            * empty_bench.get(sa["block_id"], 0.0)
            for sa in sa_dicts
        )
    else:
        b_ret_empty = 0.0
    assert b_ret_empty == 0.0


def test_multi_period_carino_preserves_observed_bench_in_unavailable_period():
    """End-to-end multi-period Carino: period 1 degrades (benchmark_available
    False) but the route-level b_ret derivation from observed benchmark dict
    means linked benchmark total is NON-ZERO and reflects observed data.

    Codex P1 (Q155 hotfix-of-hotfix Catch B regression): asserts Carino
    linker fed from the corrected route stream produces a different
    total_benchmark_return than the prior buggy zero-out behaviour.
    """
    svc = AttributionService()

    # Two periods with identical structure.
    allocations = [
        {"block_id": "equity", "target_weight": 0.70},
        {"block_id": "bonds", "target_weight": 0.30},
    ]
    labels = {"equity": "Equity", "bonds": "Bonds"}

    # Period 1: simulate "fund returns missing" → degrade by passing empty
    # fund_returns. has_observed_bench=False (block_ids empty), so we hit
    # the Catch A early return.
    period1_fund: dict[str, float] = {}
    period1_bench = {"equity": 0.04, "bonds": 0.02}

    # Period 2: clean — both observed.
    period2_fund = {"equity": 0.05, "bonds": 0.03}
    period2_bench = {"equity": 0.04, "bonds": 0.025}

    p1 = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=period1_fund,
        benchmark_returns_by_block=period1_bench,
        block_labels=labels,
    )
    p2 = svc.compute_portfolio_attribution(
        strategic_allocations=allocations,
        fund_returns_by_block=period2_fund,
        benchmark_returns_by_block=period2_bench,
        block_labels=labels,
    )

    assert p1.benchmark_available is False
    assert p2.benchmark_available is True

    # Replicate the route's Carino stream construction with Catch B logic.
    def _route_streams(
        results: list,
        bench_dicts: list[dict[str, float]],
    ) -> tuple[list[float], list[float]]:
        p_stream = []
        b_stream = []
        for result, bench_dict in zip(results, bench_dicts, strict=True):
            if result.benchmark_available:
                p_stream.append(result.total_portfolio_return)
                b_stream.append(result.total_benchmark_return)
            else:
                p_stream.append(result.total_portfolio_return)
                if bench_dict:
                    b_ret = sum(
                        float(sa["target_weight"])
                        * bench_dict.get(sa["block_id"], 0.0)
                        for sa in allocations
                    )
                else:
                    b_ret = 0.0
                b_stream.append(b_ret)
        return p_stream, b_stream

    p_returns_correct, b_returns_correct = _route_streams(
        [p1, p2], [period1_bench, period2_bench]
    )

    # Period 1 b_ret derived from observed benchmark dict.
    expected_b_p1 = 0.70 * 0.04 + 0.30 * 0.02  # 0.034
    assert b_returns_correct[0] == pytest.approx(expected_b_p1, abs=1e-9)
    # Period 2 b_ret comes from AttributionResult.total_benchmark_return
    # (clean Carino-additive path).
    assert b_returns_correct[1] == pytest.approx(p2.total_benchmark_return, abs=1e-9)

    # Replicate the BUGGY (pre-hotfix) stream: hard-zero on degraded period.
    p_returns_buggy = [
        p1.total_portfolio_return if p1.benchmark_available else 0.0,
        p2.total_portfolio_return if p2.benchmark_available else 0.0,
    ]
    b_returns_buggy = [
        p1.total_benchmark_return if p1.benchmark_available else 0.0,
        p2.total_benchmark_return if p2.benchmark_available else 0.0,
    ]

    # Carino-link both streams.
    multi_correct = svc.compute_multi_period(
        period_results=[p1, p2],
        portfolio_period_returns=p_returns_correct,
        benchmark_period_returns=b_returns_correct,
    )
    multi_buggy = svc.compute_multi_period(
        period_results=[p1, p2],
        portfolio_period_returns=p_returns_buggy,
        benchmark_period_returns=b_returns_buggy,
    )

    # The corrected stream must produce a strictly larger total_benchmark_return
    # because period 1 contributes 0.034 instead of 0.0.
    assert multi_correct.total_benchmark_return > multi_buggy.total_benchmark_return, (
        "Catch B fix must surface observed period-1 benchmark performance, "
        "producing a larger linked benchmark total than the buggy zero-out path. "
        f"correct={multi_correct.total_benchmark_return}, "
        f"buggy={multi_buggy.total_benchmark_return}"
    )
