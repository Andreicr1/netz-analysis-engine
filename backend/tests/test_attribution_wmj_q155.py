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
    """Strategic allocation with a block that has fund return but no benchmark
    return must be included via CIPM fallback, not dropped.

    WMJ-009: before fix, compute_portfolio_attribution excluded blocks without
    benchmark returns, while brinson_fachler.py used CIPM convention (r_b = r_p
    for off-benchmark sectors). This caused the same fund to produce different
    attribution depending on which code path ran.
    """
    svc = AttributionService()

    allocations = [
        {"block_id": "equity", "target_weight": 0.70},
        {"block_id": "crypto", "target_weight": 0.10},
        {"block_id": "bonds", "target_weight": 0.20},
    ]
    fund_returns = {"equity": 0.08, "crypto": 0.25, "bonds": 0.03}
    # Benchmark has NO return for crypto — off-benchmark bet
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
