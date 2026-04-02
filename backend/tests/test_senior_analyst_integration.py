"""Integration tests for Senior Analyst Engines (Sprint 6).

Verifies Phase 3-5 components work together:
- Attribution service → quant_engine attribution
- Correlation service → quant_engine correlation regime
- Import-linter contracts hold
- Schemas serialize correctly from engine results
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from app.domains.wealth.schemas.attribution import AttributionRead, SectorAttributionRead
from app.domains.wealth.schemas.correlation_regime import (
    ConcentrationRead,
    CorrelationRegimeRead,
)
from quant_engine.correlation_regime_service import compute_correlation_regime
from vertical_engines.wealth.attribution.service import AttributionService
from vertical_engines.wealth.correlation.service import CorrelationService


class TestAttributionEndToEnd:
    """Full pipeline: strategic allocations → attribution → schema."""

    def test_full_attribution_pipeline(self):
        """3 blocks with benchmark data → full Brinson breakdown → schema."""
        svc = AttributionService()
        result = svc.compute_portfolio_attribution(
            strategic_allocations=[
                {"block_id": "equity_us", "target_weight": 0.6},
                {"block_id": "fixed_income_us", "target_weight": 0.3},
                {"block_id": "alternatives", "target_weight": 0.1},
            ],
            fund_returns_by_block={
                "equity_us": 0.08,
                "fixed_income_us": 0.03,
                "alternatives": 0.05,
            },
            benchmark_returns_by_block={
                "equity_us": 0.07,
                "fixed_income_us": 0.025,
                "alternatives": 0.04,
            },
            block_labels={
                "equity_us": "US Equities",
                "fixed_income_us": "US Fixed Income",
                "alternatives": "Alternatives",
            },
        )

        assert result.benchmark_available
        assert result.n_periods == 1

        # Brinson identity: effects sum = excess return
        effects_sum = result.allocation_total + result.selection_total + result.interaction_total
        assert abs(effects_sum - result.total_excess_return) < 1e-6

        # Serialize to schema
        sectors = [
            SectorAttributionRead(
                sector=s.sector,
                block_id=s.sector,
                allocation_effect=s.allocation_effect,
                selection_effect=s.selection_effect,
                interaction_effect=s.interaction_effect,
                total_effect=s.total_effect,
            )
            for s in result.sectors
        ]
        schema = AttributionRead(
            profile="moderate",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            granularity="monthly",
            total_portfolio_return=result.total_portfolio_return,
            total_benchmark_return=result.total_benchmark_return,
            total_excess_return=result.total_excess_return,
            allocation_total=result.allocation_total,
            selection_total=result.selection_total,
            interaction_total=result.interaction_total,
            total_allocation_combined=result.allocation_total + result.interaction_total,
            sectors=sectors,
            n_periods=result.n_periods,
            benchmark_available=result.benchmark_available,
        )
        assert schema.benchmark_approach == "policy"
        assert len(schema.sectors) == 3


class TestCorrelationEndToEnd:
    """Full pipeline: returns → correlation regime → schema."""

    def test_full_correlation_pipeline(self):
        """3 instruments → correlation analysis → schema."""
        rng = np.random.default_rng(42)
        T, N = 200, 3
        returns = rng.normal(0, 0.01, (T, N))

        svc = CorrelationService(config={
            "apply_denoising": False,
            "apply_shrinkage": False,
            "min_observations": 10,
            "window_days": 60,
        })
        result = svc.analyze_portfolio_correlation(
            instrument_ids=("id-1", "id-2", "id-3"),
            instrument_names=("Fund A", "Fund B", "Fund C"),
            returns_matrix=returns,
            profile="moderate",
        )

        assert result.instrument_count == 3
        assert result.profile == "moderate"
        assert len(result.contagion_pairs) == 3  # C(3,2) = 3 pairs

        # Serialize to schema
        schema = CorrelationRegimeRead(
            profile=result.profile,
            instrument_count=result.instrument_count,
            window_days=result.window_days,
            correlation_matrix=[list(row) for row in result.correlation_matrix],
            instrument_labels=list(result.instrument_labels),
            contagion_pairs=[],
            concentration=ConcentrationRead(
                eigenvalues=list(result.concentration.eigenvalues),
                explained_variance_ratios=list(result.concentration.explained_variance_ratios),
                first_eigenvalue_ratio=result.concentration.first_eigenvalue_ratio,
                concentration_status=result.concentration.concentration_status,
                diversification_ratio=result.concentration.diversification_ratio,
                dr_alert=result.concentration.dr_alert,
                absorption_ratio=result.concentration.absorption_ratio,
                absorption_status=result.concentration.absorption_status,
            ),
            average_correlation=result.average_correlation,
            baseline_average_correlation=result.baseline_average_correlation,
            regime_shift_detected=result.regime_shift_detected,
            computed_at=result.computed_at if isinstance(result.computed_at, datetime) else datetime.fromisoformat(result.computed_at),
        )
        assert schema.instrument_count == 3


class TestCrossEngineIntegration:
    """Verify engines don't have circular imports and work together."""

    def test_attribution_and_correlation_independent(self):
        """Both engines can be used in same test without conflicts."""
        # Attribution
        attr_svc = AttributionService()
        attr_result = attr_svc.compute_portfolio_attribution(
            strategic_allocations=[
                {"block_id": "a", "target_weight": 0.5},
                {"block_id": "b", "target_weight": 0.5},
            ],
            fund_returns_by_block={"a": 0.05, "b": 0.03},
            benchmark_returns_by_block={"a": 0.04, "b": 0.02},
            block_labels={"a": "Block A", "b": "Block B"},
        )
        assert attr_result.benchmark_available

        # Correlation
        rng = np.random.default_rng(42)
        corr_result = compute_correlation_regime(
            rng.normal(0, 0.01, (100, 3)),
            config={"apply_denoising": False, "apply_shrinkage": False, "min_observations": 10, "window_days": 100},
        )
        assert corr_result.sufficient_data

    def test_quant_engine_services_are_vertical_agnostic(self):
        """quant_engine services have no wealth imports."""
        import quant_engine.attribution_service as attr_mod
        import quant_engine.correlation_regime_service as corr_mod

        # Verify no wealth domain imports
        for mod in [attr_mod, corr_mod]:
            source = mod.__file__
            assert source is not None
            with open(source) as f:
                content = f.read()
            assert "app.domains.wealth" not in content
            assert "vertical_engines.wealth" not in content


class TestMultiPeriodFullPipeline:
    """End-to-end multi-period attribution with Carino linking."""

    def test_multi_period_produces_valid_result(self):
        svc = AttributionService()

        # Period 1
        r1 = svc.compute_portfolio_attribution(
            strategic_allocations=[
                {"block_id": "eq", "target_weight": 0.6},
                {"block_id": "fi", "target_weight": 0.4},
            ],
            fund_returns_by_block={"eq": 0.02, "fi": 0.01},
            benchmark_returns_by_block={"eq": 0.015, "fi": 0.008},
            block_labels={"eq": "Equity", "fi": "Fixed Income"},
        )

        # Period 2
        r2 = svc.compute_portfolio_attribution(
            strategic_allocations=[
                {"block_id": "eq", "target_weight": 0.6},
                {"block_id": "fi", "target_weight": 0.4},
            ],
            fund_returns_by_block={"eq": 0.03, "fi": -0.005},
            benchmark_returns_by_block={"eq": 0.025, "fi": -0.003},
            block_labels={"eq": "Equity", "fi": "Fixed Income"},
        )

        # Multi-period
        multi = svc.compute_multi_period(
            period_results=[r1, r2],
            portfolio_period_returns=[
                0.6 * 0.02 + 0.4 * 0.01,
                0.6 * 0.03 + 0.4 * (-0.005),
            ],
            benchmark_period_returns=[
                0.6 * 0.015 + 0.4 * 0.008,
                0.6 * 0.025 + 0.4 * (-0.003),
            ],
        )

        assert multi.n_periods == 2
        assert multi.benchmark_available
        # Effects still sum to excess
        effects = multi.allocation_total + multi.selection_total + multi.interaction_total
        assert abs(effects - multi.total_excess_return) < 1e-4
