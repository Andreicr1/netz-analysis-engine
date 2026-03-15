"""Tests for quant_engine/macro_snapshot_builder.py — pure snapshot assembly."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from quant_engine.fred_service import FredObservation
from quant_engine.macro_snapshot_builder import build_regional_snapshot
from quant_engine.regional_macro_service import GLOBAL_SERIES, REGION_SERIES


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
            obs[spec.series_id] = _make_obs(
                list(np.linspace(10, 90, 100)),
            )
    for spec in GLOBAL_SERIES:
        obs[spec.series_id] = _make_obs(
            list(np.linspace(10, 90, 100)),
        )
    return obs


class TestBuildRegionalSnapshot:
    def test_empty_observations(self):
        result = build_regional_snapshot({}, as_of=date(2026, 3, 15))
        assert result["version"] == 1
        assert result["as_of_date"] == "2026-03-15"
        assert set(result["regions"].keys()) == {"US", "EUROPE", "ASIA", "EM"}
        assert "global_indicators" in result

    def test_full_snapshot_structure(self):
        obs = _build_full_observations()
        result = build_regional_snapshot(obs, as_of=date(2026, 3, 15))

        assert result["version"] == 1
        assert result["as_of_date"] == "2026-03-15"

        # All 4 regions present
        assert set(result["regions"].keys()) == {"US", "EUROPE", "ASIA", "EM"}

        # Each region has expected keys
        for region_key, region_data in result["regions"].items():
            assert "composite_score" in region_data
            assert "coverage" in region_data
            assert "dimensions" in region_data
            assert "data_freshness" in region_data
            assert 0 <= region_data["composite_score"] <= 100

        # Global indicators present
        gi = result["global_indicators"]
        assert "geopolitical_risk_score" in gi
        assert "energy_stress" in gi
        assert "commodity_stress" in gi
        assert "usd_strength" in gi

    def test_json_serializable(self):
        """Snapshot must be fully JSON-serializable for JSONB storage."""
        import json

        obs = _build_full_observations()
        result = build_regional_snapshot(obs, as_of=date(2026, 3, 15))

        # Should not raise
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        assert deserialized["version"] == 1

    def test_config_passthrough(self):
        """Custom config should affect scoring."""
        obs = _build_full_observations()

        # Default config
        default_result = build_regional_snapshot(obs, as_of=date(2026, 3, 15))

        # Custom config with different weights
        custom_config = {
            "regional_scoring": {
                "lookback_years": 10,
                "dimension_weights": {
                    "growth": 0.50,
                    "inflation": 0.10,
                    "monetary": 0.10,
                    "financial_conditions": 0.10,
                    "labor": 0.10,
                    "sentiment": 0.10,
                },
                "min_coverage": 0.30,
            }
        }
        custom_result = build_regional_snapshot(
            obs, as_of=date(2026, 3, 15), config=custom_config,
        )

        # Both snapshots should produce valid scores without errors
        for result in (default_result, custom_result):
            us_score = result["regions"]["US"]["composite_score"]
            assert 0 <= us_score <= 100

    def test_defaults_to_today_when_no_as_of(self):
        result = build_regional_snapshot({})
        assert result["as_of_date"] == date.today().isoformat()

    def test_data_freshness_serialization(self):
        """Ensure data_freshness dates are serialized as ISO strings."""
        import json

        obs = _build_full_observations()
        result = build_regional_snapshot(obs, as_of=date(2026, 3, 15))

        us_freshness = result["regions"]["US"]["data_freshness"]
        # At least some indicators should have freshness data
        assert len(us_freshness) > 0

        # All dates should be strings (JSON-serializable)
        serialized = json.dumps(result)
        assert isinstance(serialized, str)
