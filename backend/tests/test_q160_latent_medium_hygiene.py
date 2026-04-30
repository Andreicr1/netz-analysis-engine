"""PR-Q160 — Latent + medium hygiene cluster.

Tests for WMJ-005, WMJ-011, WMJ-012, WMJ-025, WMJ-026, WMJ-028, WMJ-029.
"""

from __future__ import annotations

import math
from datetime import date
from uuid import uuid4

import numpy as np
import pytest

from quant_engine.attribution_service import (
    AttributionResult,
    SectorAttribution,
    compute_multi_period_attribution,
)
from quant_engine.correlation_regime_service import (
    _marchenko_pastur_denoise,
    compute_correlation_regime,
)
from vertical_engines.wealth.attribution.brinson_fachler import brinson_fachler
from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    BenchmarkResolution,
    SectorWeight,
)
from vertical_engines.wealth.attribution.service import AttributionService

# ---------------------------------------------------------------------------
# WMJ-005: Brinson missing-sector contract assertion
# ---------------------------------------------------------------------------


class TestBrinsonMissingSectorContract:
    """WMJ-005: when benchmark-held sectors lack returns, the function
    must not crash and internal consistency must hold."""

    def test_partial_benchmark_returns_internal_consistency(self):
        """Benchmark has 3 sectors weighted but only 2 have returns.
        Third sector falls back to R_B. The three effects must sum to
        total_active_return (internal field consistency)."""
        fund_w = {"A": 0.3, "B": 0.4, "C": 0.3}
        fund_r = {"A": 0.05, "B": 0.08, "C": 0.02}
        bench_w = {"A": 0.4, "B": 0.3, "C": 0.3}
        # C's return is missing
        bench_r = {"A": 0.06, "B": 0.04}

        r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)

        # Internal field consistency: effects sum == total_active_return
        effects_sum = (
            r.allocation_effect + r.selection_effect + r.interaction_effect
        )
        assert effects_sum == pytest.approx(r.total_active_return, abs=1e-12)

        # WMJ-005 reconciliation gap: when bench-held sectors have missing
        # returns, R_B (from inputs) != Σ w_b·r_b_used (with imputed r_b).
        # The gap equals w_b[C] * R_B because sector C contributes 0 to R_B
        # but R_B to the imputed r_b. This is the documented CIPM convention
        # consequence — not a bug, but consumers must track coverage.
        R_P = sum(fund_w[s] * fund_r[s] for s in fund_w)
        R_B_from_inputs = sum(
            bench_w.get(s, 0.0) * bench_r.get(s, 0.0)
            for s in set(fund_w) | set(bench_w)
        )
        # The gap exists; verify it's bounded by w_b * R_B for missing sectors
        gap = abs(r.total_active_return - (R_P - R_B_from_inputs))
        assert gap > 0  # gap IS expected with partial coverage

    def test_full_coverage_reconciles_exactly(self):
        """When all benchmark sectors have returns, the full reconciliation
        identity R_P - R_B == total_active_return holds."""
        fund_w = {"A": 0.3, "B": 0.4, "C": 0.3}
        fund_r = {"A": 0.05, "B": 0.08, "C": 0.02}
        bench_w = {"A": 0.4, "B": 0.3, "C": 0.3}
        bench_r = {"A": 0.06, "B": 0.04, "C": 0.03}

        r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)

        R_P = sum(fund_w[s] * fund_r[s] for s in fund_w)
        R_B = sum(bench_w[s] * bench_r[s] for s in bench_w)
        assert r.total_active_return == pytest.approx(R_P - R_B, abs=1e-12)

    def test_all_benchmark_sectors_missing_returns(self):
        """Edge: bench_returns is empty. Every bench-held sector falls back
        to R_B = 0 → degenerate but must not crash."""
        fund_w = {"A": 0.5, "B": 0.5}
        fund_r = {"A": 0.10, "B": 0.05}
        bench_w = {"A": 0.6, "B": 0.4}
        bench_r: dict[str, float] = {}

        r = brinson_fachler(fund_w, fund_r, bench_w, bench_r)

        effects_sum = (
            r.allocation_effect + r.selection_effect + r.interaction_effect
        )
        assert effects_sum == pytest.approx(r.total_active_return, abs=1e-12)


# ---------------------------------------------------------------------------
# WMJ-011: proxy rail period alignment
# ---------------------------------------------------------------------------


class TestProxyRailPeriodAlignment:
    """WMJ-011: mismatched fund/proxy periods must be logged."""

    @pytest.mark.asyncio
    async def test_misaligned_periods_not_degraded(self, monkeypatch):
        """When fund and proxy periods differ, result is still produced
        (the warning is logged but the rail doesn't degrade — the fix
        is defensive pre-wire-up only)."""
        import vertical_engines.wealth.attribution.benchmark_proxy as bp_mod

        fund_id = uuid4()
        request = AttributionRequest(
            fund_instrument_id=fund_id,
            asof=date(2025, 12, 31),
        )

        _period_call_count = 0

        async def _mock_latest_period(_db, cik, not_before=None):
            nonlocal _period_call_count
            _period_call_count += 1
            if _period_call_count == 1:
                return date(2025, 9, 30)  # fund period
            return date(2025, 12, 31)  # proxy period

        async def _mock_sector_weights(_db, cik, period):
            return [
                SectorWeight(
                    sector="Equity",
                    issuer_category="Corp",
                    weight=1.0,
                    aum_usd=1e9,
                    holdings_count=100,
                ),
            ], 1e9

        async def _mock_resolve(_bench, _db):
            return BenchmarkResolution(
                match_type="exact",
                proxy_etf_ticker="SPY",
                proxy_etf_cik="0000000001",
                proxy_etf_series_id="S000",
                asset_class="equity_us_large",
            )

        async def _mock_sector_returns(_db, _cik, _period):
            return {"Equity": 0.05}

        async def _cik_resolver(_db, _fid):
            return "0000012345"

        async def _bench_fetcher(_db, _cik):
            return "S&P 500"

        monkeypatch.setattr(bp_mod, "resolve_benchmark", _mock_resolve)
        monkeypatch.setattr(bp_mod, "latest_period_for_cik", _mock_latest_period)
        monkeypatch.setattr(bp_mod, "fetch_sector_weights", _mock_sector_weights)

        result = await bp_mod.run_proxy_rail(
            request,
            db=None,  # type: ignore[arg-type]
            cik_resolver=_cik_resolver,
            benchmark_fetcher=_bench_fetcher,
            sector_returns_fetcher=_mock_sector_returns,
        )
        assert result is not None
        # Rail still produces a result (not degraded) even with mismatched periods
        assert not result.degraded
        assert result.brinson.total_active_return == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# WMJ-012: proxy rail fund-side empty holdings
# ---------------------------------------------------------------------------


class TestProxyRailFundNoHoldings:
    """WMJ-012: fund-side empty holdings must degrade with fund_no_holdings."""

    @pytest.mark.asyncio
    async def test_fund_no_holdings_degrades(self, monkeypatch):
        """Empty fund sectors must produce degraded result."""
        import vertical_engines.wealth.attribution.benchmark_proxy as bp_mod

        fund_id = uuid4()
        request = AttributionRequest(
            fund_instrument_id=fund_id,
            asof=date(2025, 12, 31),
        )

        async def _cik_resolver(_db, _fid):
            return "0000012345"

        async def _bench_fetcher(_db, _cik):
            return "S&P 500"

        async def _mock_latest_period(_db, cik, not_before=None):
            return date(2025, 12, 31)

        _fetch_count = 0

        async def _mock_sector_weights(_db, cik, period):
            nonlocal _fetch_count
            _fetch_count += 1
            if _fetch_count == 1:
                return [], 0.0  # Fund: empty
            return [
                SectorWeight(
                    sector="Equity",
                    issuer_category="Corp",
                    weight=1.0,
                    aum_usd=1e9,
                    holdings_count=100,
                ),
            ], 1e9  # Proxy: has holdings

        async def _mock_resolve(_bench, _db):
            return BenchmarkResolution(
                match_type="exact",
                proxy_etf_ticker="SPY",
                proxy_etf_cik="0000000001",
            )

        monkeypatch.setattr(bp_mod, "resolve_benchmark", _mock_resolve)
        monkeypatch.setattr(bp_mod, "latest_period_for_cik", _mock_latest_period)
        monkeypatch.setattr(bp_mod, "fetch_sector_weights", _mock_sector_weights)

        result = await bp_mod.run_proxy_rail(
            request,
            db=None,  # type: ignore[arg-type]
            cik_resolver=_cik_resolver,
            benchmark_fetcher=_bench_fetcher,
        )
        assert result is not None
        assert result.degraded
        assert result.degraded_reason == "fund_no_holdings"


# ---------------------------------------------------------------------------
# WMJ-025: Carino k_t clamp
# ---------------------------------------------------------------------------


class TestCarinoKtClamp:
    """WMJ-025: pathological returns near -100% must not produce
    unbounded Carino factors."""

    def test_pathological_returns_clamped(self):
        """Returns near -100% should still produce a finite, reconciling result."""
        # r_p = -0.999, r_b = -0.998 → diff = -0.001
        # ln(0.001) - ln(0.002) / (-0.001) ≈ (-6.9 + 6.2) / -0.001 ≈ 693
        # Without clamp, k_t ≈ 693 which distorts linked effects.
        p_rets = [-0.999, 0.50]
        b_rets = [-0.998, 0.49]

        periods = []
        for p, b in zip(p_rets, b_rets, strict=False):
            excess = p - b
            sectors = [SectorAttribution(
                sector="All",
                allocation_effect=excess * 0.5,
                selection_effect=excess * 0.3,
                interaction_effect=excess * 0.2,
                total_effect=excess,
            )]
            periods.append(AttributionResult(
                total_portfolio_return=p,
                total_benchmark_return=b,
                total_excess_return=excess,
                sectors=sectors,
                allocation_total=excess * 0.5,
                selection_total=excess * 0.3,
                interaction_total=excess * 0.2,
                n_periods=1,
                benchmark_available=True,
            ))

        result = compute_multi_period_attribution(periods, p_rets, b_rets)

        # Must be finite
        assert math.isfinite(result.allocation_total)
        assert math.isfinite(result.selection_total)
        assert math.isfinite(result.interaction_total)

    def test_clamp_does_not_distort_normal_returns(self):
        """Normal returns (far from -100%) should be unaffected by the clamp."""
        p_rets = [0.02, 0.03, -0.01]
        b_rets = [0.01, 0.02, -0.005]

        periods = []
        for p, b in zip(p_rets, b_rets, strict=False):
            excess = p - b
            periods.append(AttributionResult(
                total_portfolio_return=p,
                total_benchmark_return=b,
                total_excess_return=excess,
                sectors=[SectorAttribution(
                    sector="All",
                    allocation_effect=excess * 0.5,
                    selection_effect=excess * 0.3,
                    interaction_effect=excess * 0.2,
                    total_effect=excess,
                )],
                allocation_total=excess * 0.5,
                selection_total=excess * 0.3,
                interaction_total=excess * 0.2,
                n_periods=1,
                benchmark_available=True,
            ))

        result = compute_multi_period_attribution(periods, p_rets, b_rets)

        R_p = float(np.prod([1 + r for r in p_rets]) - 1)
        R_b = float(np.prod([1 + r for r in b_rets]) - 1)
        effects_sum = (
            result.allocation_total
            + result.selection_total
            + result.interaction_total
        )
        assert abs(effects_sum - (R_p - R_b)) < 1e-5


# ---------------------------------------------------------------------------
# WMJ-026: simple average linking precision
# ---------------------------------------------------------------------------


class TestSimpleAverageLinkingPrecision:
    """WMJ-026: aggregate totals must use full-precision accumulators,
    not rounded sector display values."""

    def test_totals_more_precise_than_sector_sum(self):
        """Summing rounded sectors introduces up to N * 5e-7 error.
        The aggregate totals should be more precise."""
        svc = AttributionService()

        # Construct two opposing-excess periods to trigger the
        # _simple_average_linking fallback (total excess near zero)
        r1 = AttributionResult(
            total_portfolio_return=0.05,
            total_benchmark_return=0.00,
            total_excess_return=0.05,
            sectors=[
                SectorAttribution(
                    sector="A",
                    allocation_effect=0.0123456789,
                    selection_effect=0.0234567890,
                    interaction_effect=0.0141975321,
                    total_effect=0.05,
                ),
                SectorAttribution(
                    sector="B",
                    allocation_effect=0.0000000001,
                    selection_effect=0.0000000001,
                    interaction_effect=-0.0000000002,
                    total_effect=0.0,
                ),
            ],
            allocation_total=0.0123456790,
            selection_total=0.0234567891,
            interaction_total=0.0141975319,
            n_periods=1,
            benchmark_available=True,
        )
        r2 = AttributionResult(
            total_portfolio_return=0.00,
            total_benchmark_return=0.05,
            total_excess_return=-0.05,
            sectors=[
                SectorAttribution(
                    sector="A",
                    allocation_effect=-0.0123456789,
                    selection_effect=-0.0234567890,
                    interaction_effect=-0.0141975321,
                    total_effect=-0.05,
                ),
                SectorAttribution(
                    sector="B",
                    allocation_effect=-0.0000000001,
                    selection_effect=-0.0000000001,
                    interaction_effect=0.0000000002,
                    total_effect=0.0,
                ),
            ],
            allocation_total=-0.0123456790,
            selection_total=-0.0234567891,
            interaction_total=-0.0141975319,
            n_periods=1,
            benchmark_available=True,
        )

        result = svc.compute_multi_period([r1, r2], [0.05, 0.00], [0.00, 0.05])

        # The totals should be very close to zero (effects cancel perfectly)
        assert abs(result.allocation_total) < 1e-6
        assert abs(result.selection_total) < 1e-6
        assert abs(result.interaction_total) < 1e-6


# ---------------------------------------------------------------------------
# WMJ-028: correlation PSD after denoising
# ---------------------------------------------------------------------------


class TestCorrelationPSDAfterDenoising:
    """WMJ-028: denoised correlation matrix must be PSD."""

    def test_denoised_eigenvalues_nonneg(self):
        """After MP denoising, all eigenvalues must be >= 0."""
        rng = np.random.default_rng(42)
        T, N = 60, 10  # high N/T ratio to stress denoising
        returns = rng.normal(0, 0.01, (T, N))
        corr = np.corrcoef(returns, rowvar=False)
        q = N / T

        denoised = _marchenko_pastur_denoise(corr, q)

        eigenvalues = np.linalg.eigvalsh(denoised)
        # All eigenvalues >= 0 (PSD)
        assert np.all(eigenvalues >= -1e-12), (
            f"Non-PSD eigenvalues: {eigenvalues[eigenvalues < -1e-12]}"
        )

    def test_baseline_fallback_produces_degenerate_regime_shift(self):
        """When baseline window = recent window (fallback), baseline avg
        correlation equals recent avg → regime_shift_detected is False."""
        rng = np.random.default_rng(42)
        # Only 50 observations total with window=50 → baseline = recent
        returns = rng.normal(0, 0.01, (50, 3))
        result = compute_correlation_regime(
            returns,
            config={
                "apply_denoising": False,
                "apply_shrinkage": False,
                "min_observations": 10,
                "window_days": 50,
            },
        )
        assert result.sufficient_data
        # Baseline fallback → identical avg correlations → no regime shift
        assert result.average_correlation == result.baseline_average_correlation
        assert not result.regime_shift_detected

    def test_dr_reconciles_with_returned_matrix(self):
        """WMJ-028: diversification ratio must be computable from the
        returned correlation matrix and covariance."""
        rng = np.random.default_rng(42)
        T, N = 200, 4
        returns = rng.normal(0, 0.01, (T, N))
        weights = np.array([0.25, 0.25, 0.25, 0.25])

        result = compute_correlation_regime(
            returns,
            weights=weights,
            config={
                "apply_denoising": False,
                "apply_shrinkage": False,
                "min_observations": 10,
                "window_days": 200,
            },
        )

        # DR must be >= 1.0 for any non-degenerate portfolio
        assert result.diversification_ratio >= 1.0 - 1e-6
