"""Tests for BIS/IMF enrichment wiring in macro ingestion + snapshot builder."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from quant_engine.fred_service import FredObservation
from quant_engine.macro_snapshot_builder import build_regional_snapshot
from quant_engine.regional_macro_service import (
    GLOBAL_SERIES,
    REGION_SERIES,
    BisDataPoint,
    ImfDataPoint,
    enrich_region_score,
    resolve_scoring_config,
    score_region,
)


def _make_obs(values: list[float], start_date: str = "2016-01-01") -> list[FredObservation]:
    """Create ascending-order FredObservation list from values."""
    base = date.fromisoformat(start_date)
    return [
        FredObservation(date=str(base + timedelta(days=i * 30)), value=v)
        for i, v in enumerate(values)
    ]


def _build_full_observations() -> dict[str, list[FredObservation]]:
    """Build observations for all series with synthetic data."""
    obs: dict[str, list[FredObservation]] = {}
    for region_specs in REGION_SERIES.values():
        for spec in region_specs:
            obs[spec.series_id] = _make_obs(list(np.linspace(10, 90, 100)))
    for spec in GLOBAL_SERIES:
        obs[spec.series_id] = _make_obs(list(np.linspace(10, 90, 100)))
    return obs


def _make_bis_data() -> list[BisDataPoint]:
    """Create synthetic BIS data for US and European countries."""
    today = date.today()
    points = []
    for cc in ("US", "GB", "DE", "FR", "JP", "BR"):
        points.append(BisDataPoint(cc, "credit_to_gdp_gap", 3.5, today - timedelta(days=30)))
        points.append(BisDataPoint(cc, "debt_service_ratio", 15.0, today - timedelta(days=30)))
        points.append(BisDataPoint(cc, "property_prices", 4.0, today - timedelta(days=30)))
    return points


def _make_imf_data() -> list[ImfDataPoint]:
    """Create synthetic IMF data for multiple countries."""
    current_year = date.today().year
    points = []
    for cc in ("US", "GB", "DE", "JP", "BR", "IN"):
        points.append(ImfDataPoint(cc, "NGDP_RPCH", current_year, 2.5))
        points.append(ImfDataPoint(cc, "NGDP_RPCH", current_year + 1, 2.8))
        points.append(ImfDataPoint(cc, "PCPIPCH", current_year, 3.0))
    return points


class TestEnrichRegionScoreIntegration:
    """Test that enrich_region_score is called when BIS+IMF data is available."""

    def test_snapshot_with_bis_imf_has_credit_cycle(self):
        """build_regional_snapshot with BIS data produces 7 dimensions."""
        obs = _build_full_observations()
        bis_data = _make_bis_data()
        imf_data = _make_imf_data()

        result = build_regional_snapshot(
            obs,
            as_of=date(2026, 3, 15),
            bis_data=bis_data,
            imf_data=imf_data,
        )

        # All regions should have credit_cycle dimension
        for region_name in ("US", "EUROPE", "ASIA", "EM"):
            dims = result["regions"][region_name]["dimensions"]
            assert "credit_cycle" in dims, f"{region_name} missing credit_cycle"
            assert dims["credit_cycle"]["score"] > 0

    def test_snapshot_without_bis_imf_has_6_dimensions(self):
        """build_regional_snapshot without BIS/IMF data produces standard 6 dimensions."""
        obs = _build_full_observations()

        result = build_regional_snapshot(
            obs,
            as_of=date(2026, 3, 15),
            bis_data=None,
            imf_data=None,
        )

        for region_name in ("US", "EUROPE", "ASIA", "EM"):
            dims = result["regions"][region_name]["dimensions"]
            assert "credit_cycle" not in dims

    def test_snapshot_with_bis_only(self):
        """BIS data alone adds credit_cycle dimension."""
        obs = _build_full_observations()
        bis_data = _make_bis_data()

        result = build_regional_snapshot(
            obs,
            as_of=date(2026, 3, 15),
            bis_data=bis_data,
            imf_data=None,
        )

        us_dims = result["regions"]["US"]["dimensions"]
        assert "credit_cycle" in us_dims

    def test_snapshot_with_imf_only(self):
        """IMF data alone blends growth score without adding credit_cycle."""
        obs = _build_full_observations()
        imf_data = _make_imf_data()

        result_imf = build_regional_snapshot(
            obs, as_of=date(2026, 3, 15), imf_data=imf_data,
        )

        # credit_cycle should NOT be added
        us_dims = result_imf["regions"]["US"]["dimensions"]
        assert "credit_cycle" not in us_dims

        # growth score should exist and be valid (if region has sufficient data)
        if "growth" in us_dims:
            assert isinstance(us_dims["growth"]["score"], (int, float))


class TestGracefulDegradation:
    """Test that enrichment degrades gracefully with empty or missing data."""

    def test_empty_bis_data_returns_unchanged(self):
        """Empty BIS list does not add credit_cycle."""
        obs = _build_full_observations()
        config = resolve_scoring_config(None)
        result = score_region("US", obs, date(2026, 3, 15), config)

        enriched = enrich_region_score(result, bis_data=[], imf_data=None)
        assert enriched.dimensions.keys() == result.dimensions.keys()
        assert enriched.composite_score == result.composite_score

    def test_none_bis_data_returns_unchanged(self):
        """None BIS data returns original result."""
        obs = _build_full_observations()
        config = resolve_scoring_config(None)
        result = score_region("US", obs, date(2026, 3, 15), config)

        enriched = enrich_region_score(result, bis_data=None, imf_data=None)
        assert enriched is result  # Same object, not a copy

    def test_empty_imf_data_preserves_scores(self):
        """Empty IMF list preserves original scores unchanged."""
        obs = _build_full_observations()
        config = resolve_scoring_config(None)
        result = score_region("US", obs, date(2026, 3, 15), config)

        enriched = enrich_region_score(result, bis_data=None, imf_data=[])
        # With None bis_data and empty imf_data, result should be identical
        assert enriched is result

    def test_bis_for_unknown_countries_returns_neutral(self):
        """BIS data for countries outside any region yields neutral credit_cycle."""
        obs = _build_full_observations()
        config = resolve_scoring_config(None)
        result = score_region("US", obs, date(2026, 3, 15), config)

        # Countries not mapped to any region
        bis_data = [
            BisDataPoint("XX", "credit_to_gdp_gap", 5.0, date(2026, 3, 1)),
        ]
        enriched = enrich_region_score(result, bis_data=bis_data, imf_data=None)
        # No US countries matched, so credit_cycle won't be added (n_countries=0)
        assert "credit_cycle" not in enriched.dimensions


class TestCreditCycleDimension:
    """Test that the 7th dimension (credit_cycle) is correctly computed."""

    def test_credit_cycle_score_range(self):
        """Credit cycle score should be in 0-100 range."""
        obs = _build_full_observations()
        bis_data = _make_bis_data()

        result = build_regional_snapshot(
            obs, as_of=date(2026, 3, 15), bis_data=bis_data,
        )

        for region_name in ("US", "EUROPE", "ASIA", "EM"):
            dims = result["regions"][region_name]["dimensions"]
            if "credit_cycle" in dims:
                score = dims["credit_cycle"]["score"]
                assert 0 <= score <= 100, f"{region_name} credit_cycle score out of range: {score}"

    def test_credit_cycle_has_sub_indicators(self):
        """Credit cycle dimension exposes credit_gap, debt_service, property_prices."""
        obs = _build_full_observations()
        bis_data = _make_bis_data()

        result = build_regional_snapshot(
            obs, as_of=date(2026, 3, 15), bis_data=bis_data,
        )

        us_cc = result["regions"]["US"]["dimensions"].get("credit_cycle")
        assert us_cc is not None
        assert "credit_gap" in us_cc["indicators"]
        assert "debt_service" in us_cc["indicators"]
        assert "property_prices" in us_cc["indicators"]

    def test_composite_reweighted_with_credit_cycle(self):
        """Composite score changes when credit_cycle is added."""
        obs = _build_full_observations()
        bis_data = _make_bis_data()

        result_base = build_regional_snapshot(
            obs, as_of=date(2026, 3, 15),
        )
        result_enriched = build_regional_snapshot(
            obs, as_of=date(2026, 3, 15), bis_data=bis_data,
        )

        # At least one region should have a different composite
        any_different = any(
            result_base["regions"][r]["composite_score"]
            != result_enriched["regions"][r]["composite_score"]
            for r in ("US", "EUROPE", "ASIA", "EM")
            if "credit_cycle" in result_enriched["regions"][r]["dimensions"]
        )
        assert any_different, "Composite should change when credit_cycle is added"
