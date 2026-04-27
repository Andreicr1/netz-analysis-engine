"""Regression tests for PR-Q55 micro-fixes: CFNAI dimension + energy stress sign."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from quant_engine.fred_service import FredObservation
from quant_engine.regional_macro_service import (
    _DEFAULT_CONFIG,
    REGION_SERIES,
    score_global_indicators,
    score_region,
)

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _make_obs(values: list[float], start_date: str = "2016-01-01") -> list[FredObservation]:
    """Create ascending-order FredObservation list from values."""
    base = date.fromisoformat(start_date)
    return [
        FredObservation(date=str(base + timedelta(days=i * 30)), value=v)
        for i, v in enumerate(values)
    ]


# ---------------------------------------------------------------------------
#  F02 regression: CFNAI in growth dimension
# ---------------------------------------------------------------------------


class TestCFNAIDimension:
    def test_cfnai_dimension_is_growth_not_activity(self):
        """CFNAI must be in 'growth' dimension to contribute non-zero weight."""
        us_series = REGION_SERIES["US"]
        cfnai_spec = next((s for s in us_series if s.series_id == "CFNAI"), None)
        assert cfnai_spec is not None
        assert cfnai_spec.dimension == "growth"

    def test_cfnai_contributes_to_us_composite_score(self):
        """CFNAI must appear as a scored indicator in the growth dimension."""
        cfg = _DEFAULT_CONFIG
        as_of = date(2026, 3, 15)
        recent_start = "2023-04-01"

        us_specs = REGION_SERIES["US"]
        obs: dict[str, list[FredObservation]] = {}
        for spec in us_specs:
            obs[spec.series_id] = _make_obs(
                list(np.linspace(0, 100, 120)), start_date=recent_start,
            )

        result = score_region("US", obs, as_of, cfg)

        assert "growth" in result.dimensions
        growth_dim = result.dimensions["growth"]
        # CFNAI must be one of the scored indicators in growth
        assert "CFNAI" in growth_dim.indicators, (
            f"CFNAI not in growth indicators: {list(growth_dim.indicators.keys())}"
        )
        # Should have 4 growth indicators (GDP, INDPRO, PAYEMS, CFNAI)
        assert growth_dim.n_indicators == 4

    def test_all_us_dimensions_have_weight(self):
        """Every dimension used in US REGION_SERIES should have a non-zero weight."""
        dim_weights = _DEFAULT_CONFIG["dimension_weights"]
        us_dimensions = {s.dimension for s in REGION_SERIES["US"]}
        for dim in us_dimensions:
            assert dim_weights.get(dim, 0) > 0, (
                f"US dimension '{dim}' has zero weight in _DEFAULT_CONFIG"
            )


# ---------------------------------------------------------------------------
#  F12 regression: energy stress sign
# ---------------------------------------------------------------------------


class TestEnergyStressSign:
    def _build_energy_obs(
        self,
        oil_ascending: bool = True,
        reserves_ascending: bool = True,
    ) -> dict[str, list[FredObservation]]:
        """Build observations for energy stress computation.

        oil_ascending=True → current oil at max (expensive in real terms).
        reserves_ascending=True → current reserves at max (full).
        """
        n = 100
        if oil_ascending:
            oil_vals = list(np.linspace(20, 120, n))  # current = 120 (expensive)
        else:
            oil_vals = list(np.linspace(120, 20, n))  # current = 20 (cheap)

        if reserves_ascending:
            res_vals = list(np.linspace(200, 600, n))  # current = 600 (full)
        else:
            res_vals = list(np.linspace(600, 200, n))  # current = 200 (depleted)

        return {
            "DCOILWTICO": _make_obs(oil_vals),
            "DCOILBRENTEU": _make_obs(oil_vals),
            "DHHNGSP": _make_obs(oil_vals),
            "WCSSTUS1": _make_obs(res_vals),
            "WCESTUS1": _make_obs(res_vals),
            # Also provide geopolitical/commodity/usd so function doesn't crash
            "GPRH": _make_obs([50.0] * n),
            "USEPUINDXD": _make_obs([50.0] * n),
            "PCOPPUSDM": _make_obs([50.0] * n),
            "GOLDAMGBD228NLBM": _make_obs([50.0] * n),
            "PFERTINDEXM": _make_obs([50.0] * n),
            "DTWEXBGS": _make_obs([50.0] * n),
        }

    def test_energy_stress_high_for_expensive_oil_depleted_reserves(self):
        """Oil at max percentile (expensive) + reserves depleted → high stress."""
        obs = self._build_energy_obs(oil_ascending=True, reserves_ascending=False)
        result = score_global_indicators(obs, date(2026, 3, 15))
        assert result.energy_stress >= 60, (
            f"Expected high energy stress for expensive oil + depleted reserves, "
            f"got {result.energy_stress}"
        )

    def test_energy_stress_low_for_cheap_oil_full_reserves(self):
        """Oil at min percentile (cheap) + reserves full → low stress."""
        obs = self._build_energy_obs(oil_ascending=False, reserves_ascending=True)
        result = score_global_indicators(obs, date(2026, 3, 15))
        assert result.energy_stress <= 40, (
            f"Expected low energy stress for cheap oil + full reserves, "
            f"got {result.energy_stress}"
        )

    def test_energy_stress_monotonic_with_oil_price(self):
        """As oil becomes more expensive, energy_stress should increase."""
        as_of = date(2026, 3, 15)
        n = 100

        def _scenario(oil_current_pct: float) -> float:
            """Create scenario where oil is at given percentile of history."""
            # Linspace 0-100; insert current value at that percentile position
            oil_vals = list(np.linspace(20, 120, n))
            # Shift current (last) to desired percentile position
            current_val = 20 + (120 - 20) * oil_current_pct / 100.0
            oil_vals[-1] = current_val

            obs = {
                "DCOILWTICO": _make_obs(oil_vals),
                "DCOILBRENTEU": _make_obs(oil_vals),
                "DHHNGSP": _make_obs(oil_vals),
                # Neutral reserves
                "WCSSTUS1": _make_obs([400.0] * n),
                "WCESTUS1": _make_obs([400.0] * n),
                "GPRH": _make_obs([50.0] * n),
                "USEPUINDXD": _make_obs([50.0] * n),
                "PCOPPUSDM": _make_obs([50.0] * n),
                "GOLDAMGBD228NLBM": _make_obs([50.0] * n),
                "PFERTINDEXM": _make_obs([50.0] * n),
                "DTWEXBGS": _make_obs([50.0] * n),
            }
            return score_global_indicators(obs, as_of).energy_stress

        stress_cheap = _scenario(5)
        stress_mid = _scenario(50)
        stress_expensive = _scenario(95)

        assert stress_cheap < stress_mid < stress_expensive, (
            f"Energy stress not monotonic: cheap={stress_cheap}, "
            f"mid={stress_mid}, expensive={stress_expensive}"
        )
