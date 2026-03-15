"""Tests for quant_engine/regional_macro_service.py — pure sync scoring functions."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from quant_engine.fred_service import FredObservation
from quant_engine.regional_macro_service import (
    MIN_HISTORY_OBS,
    GlobalIndicatorsResult,
    RegionalMacroResult,
    build_fetch_configs,
    compute_staleness_weight,
    get_all_series_ids,
    percentile_rank_score,
    resolve_scoring_config,
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


def _make_history(n: int, low: float = 0.0, high: float = 100.0) -> np.ndarray:
    """Create evenly spaced history array."""
    return np.linspace(low, high, n)


# ---------------------------------------------------------------------------
#  percentile_rank_score
# ---------------------------------------------------------------------------


class TestPercentileRankScore:
    def test_median_value(self):
        history = _make_history(100)
        score = percentile_rank_score(50.0, history)
        assert 45 <= score <= 55  # should be near 50

    def test_minimum_value(self):
        history = _make_history(100)
        score = percentile_rank_score(0.0, history)
        assert score <= 5

    def test_maximum_value(self):
        history = _make_history(100)
        score = percentile_rank_score(100.0, history)
        assert score >= 95

    def test_insufficient_history_returns_50(self):
        history = _make_history(MIN_HISTORY_OBS - 1)
        score = percentile_rank_score(50.0, history)
        assert score == 50.0

    def test_exactly_minimum_history(self):
        history = _make_history(MIN_HISTORY_OBS)
        # Use 90.0 (not median) to ensure computed rank differs from default 50.0
        score = percentile_rank_score(90.0, history)
        assert 0 <= score <= 100
        assert score > 80  # 90 is in the upper range of linspace(0, 100, 60)

    def test_invert(self):
        history = _make_history(100)
        normal = percentile_rank_score(90.0, history)
        inverted = percentile_rank_score(90.0, history, invert=True)
        assert abs(normal + inverted - 100.0) < 1.0

    def test_all_same_values(self):
        history = np.full(100, 42.0)
        score = percentile_rank_score(42.0, history)
        assert score == 100.0  # all values <= current


# ---------------------------------------------------------------------------
#  compute_staleness_weight
# ---------------------------------------------------------------------------


class TestStalenessWeight:
    def setup_method(self):
        self.config = {
            "daily": {"fresh_days": 3, "max_useful_days": 10, "floor": 0.30},
            "weekly": {"fresh_days": 10, "max_useful_days": 30, "floor": 0.40},
            "monthly": {"fresh_days": 45, "max_useful_days": 90, "floor": 0.50},
            "quarterly": {"fresh_days": 100, "max_useful_days": 180, "floor": 0.50},
        }

    def test_fresh_daily(self):
        as_of = date(2026, 3, 15)
        last = date(2026, 3, 14)  # 1 day ago
        f = compute_staleness_weight(last, as_of, "daily", self.config)
        assert f.weight == 1.0
        assert f.status == "fresh"

    def test_decaying_daily(self):
        as_of = date(2026, 3, 15)
        last = date(2026, 3, 8)  # 7 days ago
        f = compute_staleness_weight(last, as_of, "daily", self.config)
        assert 0.30 < f.weight < 1.0
        assert f.status == "decaying"

    def test_stale_daily(self):
        as_of = date(2026, 3, 15)
        last = date(2026, 2, 1)  # 42 days ago
        f = compute_staleness_weight(last, as_of, "daily", self.config)
        assert f.weight == 0.0
        assert f.status == "stale"

    def test_none_date(self):
        as_of = date(2026, 3, 15)
        f = compute_staleness_weight(None, as_of, "daily", self.config)
        assert f.weight == 0.0
        assert f.status == "stale"

    def test_fresh_monthly(self):
        as_of = date(2026, 3, 15)
        last = date(2026, 2, 15)  # 28 days ago (within 45-day fresh window)
        f = compute_staleness_weight(last, as_of, "monthly", self.config)
        assert f.weight == 1.0
        assert f.status == "fresh"

    def test_floor_is_respected(self):
        as_of = date(2026, 3, 15)
        # Just before max_useful for daily (10 days)
        last = date(2026, 3, 6)  # 9 days ago
        f = compute_staleness_weight(last, as_of, "daily", self.config)
        assert f.weight >= 0.30  # floor


# ---------------------------------------------------------------------------
#  resolve_scoring_config
# ---------------------------------------------------------------------------


class TestResolveScoringConfig:
    def test_none_returns_defaults(self):
        cfg = resolve_scoring_config(None)
        assert cfg["lookback_years"] == 10
        assert cfg["min_coverage"] == 0.50

    def test_empty_dict_returns_defaults(self):
        cfg = resolve_scoring_config({})
        assert cfg["lookback_years"] == 10

    def test_custom_config(self):
        cfg = resolve_scoring_config({
            "regional_scoring": {
                "lookback_years": 5,
                "min_coverage": 0.30,
            }
        })
        assert cfg["lookback_years"] == 5
        assert cfg["min_coverage"] == 0.30


# ---------------------------------------------------------------------------
#  score_region
# ---------------------------------------------------------------------------


class TestScoreRegion:
    def test_empty_observations_returns_neutral(self):
        cfg = resolve_scoring_config(None)
        result = score_region("US", {}, date(2026, 3, 15), cfg)
        assert isinstance(result, RegionalMacroResult)
        assert result.composite_score == 50.0
        assert result.coverage < 0.50

    def test_with_sufficient_data(self):
        """Score region with enough data for all US dimensions."""
        from quant_engine.regional_macro_service import REGION_SERIES

        cfg = resolve_scoring_config(None)
        obs = {}
        as_of = date(2026, 3, 15)
        # Provide 100 observations ending near as_of_date (not stale)
        # Start date: ~100 months before as_of = ~2017-11-15
        start = str(as_of - timedelta(days=100 * 30))
        for spec in REGION_SERIES["US"]:
            obs[spec.series_id] = _make_obs(
                list(np.linspace(10, 90, 100)),
                start_date=start,
            )

        result = score_region("US", obs, as_of, cfg)
        assert result.region == "US"
        assert 0 < result.composite_score < 100
        assert result.coverage > 0.50
        assert len(result.dimensions) > 0

    def test_unknown_region_returns_neutral(self):
        cfg = resolve_scoring_config(None)
        result = score_region("MARS", {}, date(2026, 3, 15), cfg)
        assert result.composite_score == 50.0
        assert result.coverage == 0.0

    def test_partial_data_below_coverage(self):
        """When only one dimension has data, coverage should be below threshold."""
        cfg = resolve_scoring_config(None)
        # Only provide VIX data (financial_conditions = 0.20 weight, below 0.50)
        obs = {
            "VIXCLS": _make_obs(list(np.linspace(10, 30, 100))),
        }
        result = score_region("US", obs, date(2026, 3, 15), cfg)
        # Coverage is only ~0.20 (financial_conditions weight) < 0.50 min
        assert result.composite_score == 50.0  # insufficient coverage → neutral


# ---------------------------------------------------------------------------
#  score_global_indicators
# ---------------------------------------------------------------------------


class TestScoreGlobalIndicators:
    def test_empty_observations(self):
        result = score_global_indicators({}, date(2026, 3, 15))
        assert isinstance(result, GlobalIndicatorsResult)
        assert result.geopolitical_risk_score == 50.0
        assert result.energy_stress == 50.0

    def test_with_data(self):
        obs = {
            "GPRH": _make_obs(list(np.linspace(50, 200, 100))),
            "USEPUINDXD": _make_obs(list(np.linspace(50, 300, 100))),
            "DCOILWTICO": _make_obs(list(np.linspace(30, 120, 100))),
            "DCOILBRENTEU": _make_obs(list(np.linspace(30, 120, 100))),
            "DHHNGSP": _make_obs(list(np.linspace(1, 10, 100))),
            "DTWEXBGS": _make_obs(list(np.linspace(80, 120, 100))),
        }
        result = score_global_indicators(obs, date(2026, 3, 15))
        assert 0 <= result.geopolitical_risk_score <= 100
        assert 0 <= result.energy_stress <= 100
        assert 0 <= result.usd_strength <= 100


# ---------------------------------------------------------------------------
#  Registry helpers
# ---------------------------------------------------------------------------


class TestRegistryHelpers:
    def test_get_all_series_ids(self):
        ids = get_all_series_ids()
        assert len(ids) == 45  # 14 + 6 + 7 + 7 + 11
        assert "VIXCLS" in ids
        assert "DTWEXBGS" in ids
        assert len(set(ids)) == len(ids)  # no duplicates

    def test_build_fetch_configs(self):
        batches = build_fetch_configs("2016-01-01")
        assert set(batches.keys()) == {"US", "EUROPE", "ASIA", "EM", "GLOBAL"}
        assert len(batches["US"]) == 14
        assert len(batches["GLOBAL"]) == 11

        # Verify limit is set per frequency
        for domain_configs in batches.values():
            for cfg in domain_configs:
                assert "limit" in cfg
                assert cfg["limit"] >= 40  # minimum for quarterly
