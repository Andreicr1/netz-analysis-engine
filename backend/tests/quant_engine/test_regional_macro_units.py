"""Regression tests for S06-F10 (Tier 1) — FRED units transform on non-stationary level series.

Regional macro percentile-rank was computed against raw monotonically-growing
series (CPI level, Payrolls, Industrial Production, GDP levels), permanently
saturating their percentile at 100 → with invert=True → score 0 (max stress).

Fix: SeriesSpec.units field, REGION_SERIES updated with units="pc1" for
non-stationary level series, build_fetch_configs passes spec.units through.
"""

from __future__ import annotations

import numpy as np

from quant_engine.regional_macro_service import (
    REGION_SERIES,
    SeriesSpec,
    build_fetch_configs,
    percentile_rank_score,
)

# ── Regression tests for S06-F10 (Tier 1) ──────────────────────────────────


def test_seriesspec_has_units_field():
    """SeriesSpec must accept units field with default 'lin'."""
    spec = SeriesSpec("TEST", "growth", "Test", "monthly")
    assert spec.units == "lin"

    spec_pc1 = SeriesSpec("TEST", "growth", "Test", "monthly", units="pc1")
    assert spec_pc1.units == "pc1"


def test_non_stationary_us_series_use_pc1_transform():
    """US level series must specify units='pc1' to avoid percentile saturation."""
    us_series = REGION_SERIES["US"]
    by_id = {s.series_id: s for s in us_series}

    # CPI is a level series (monotonic growth) — must use pc1
    assert by_id["CPIAUCSL"].units == "pc1", "CPIAUCSL is a level series; must use pc1"
    # Core PCE same
    assert by_id["PCEPILFE"].units == "pc1", "PCEPILFE is a level series; must use pc1"
    # Payrolls is a count level (monotonic) — must use pc1
    assert by_id["PAYEMS"].units == "pc1", "PAYEMS is a level series; must use pc1"
    # Industrial Production is a level index (monotonic) — must use pc1
    assert by_id["INDPRO"].units == "pc1", "INDPRO is a level series; must use pc1"


def test_stationary_us_series_keep_lin_transform():
    """Already-stationary series (rates, indices, spreads) must keep units='lin'."""
    us_series = REGION_SERIES["US"]
    by_id = {s.series_id: s for s in us_series}

    # Rates and spreads are already stationary
    assert by_id["DFF"].units == "lin"  # Fed Funds Rate (already %)
    assert by_id["VIXCLS"].units == "lin"  # VIX (level index, stationary)
    assert by_id["NFCI"].units == "lin"  # Financial Conditions (stationary)
    assert by_id["UNRATE"].units == "lin"  # Unemployment Rate (already %)
    assert by_id["A191RL1Q225SBEA"].units == "lin"  # Real GDP Growth (already rate)
    assert by_id["CFNAI"].units == "lin"  # Activity index (0-centered, stationary)
    assert by_id["UMCSENT"].units == "lin"  # Sentiment (stationary)
    assert by_id["SAHMREALTIME"].units == "lin"  # Sahm Rule (difference, stationary)


def test_europe_non_stationary_series_use_pc1():
    """Apply same transform to EU GDP level and CPI."""
    eu_series = REGION_SERIES["EUROPE"]
    by_id = {s.series_id: s for s in eu_series}

    assert by_id["CP0000EZ19M086NEST"].units == "pc1", "HICP is a level index; must use pc1"
    assert by_id["CLVMNACSCAB1GQEA19"].units == "pc1", "Euro GDP level; must use pc1"

    # Stationary EU series stay lin
    assert by_id["ECBDFR"].units == "lin"
    assert by_id["IRLTLT01DEM156N"].units == "lin"
    assert by_id["BAMLHE00EHYIEY"].units == "lin"
    assert by_id["CSCICP02EZM460S"].units == "lin"


def test_asia_non_stationary_series_use_pc1():
    """Apply to Japan/China CPI and Japan GDP level."""
    asia_series = REGION_SERIES["ASIA"]
    by_id = {s.series_id: s for s in asia_series}

    assert by_id["JPNCPIALLMINMEI"].units == "pc1", "Japan CPI is a level; must use pc1"
    assert by_id["CHNCPIALLMINMEI"].units == "pc1", "China CPI is a level; must use pc1"
    assert by_id["JPNRGDPEXP"].units == "pc1", "Japan GDP level; must use pc1"

    # CLI amplitude-adjusted = stationary by construction
    assert by_id["CHNLOLITOAASTSAM"].units == "lin"
    assert by_id["JPNLOLITOAASTSAM"].units == "lin"


def test_em_non_stationary_series_use_pc1():
    """Apply to Brazil/India CPI."""
    em_series = REGION_SERIES["EM"]
    by_id = {s.series_id: s for s in em_series}

    assert by_id["BRACPIALLMINMEI"].units == "pc1", "Brazil CPI is a level; must use pc1"
    assert by_id["INDCPIALLMINMEI"].units == "pc1", "India CPI is a level; must use pc1"

    # CLI amplitude-adjusted / normalized = stationary
    assert by_id["BRALOLITOAASTSAM"].units == "lin"
    assert by_id["INDLOLITOAASTSAM"].units == "lin"
    assert by_id["MEXLOLITONOSTSAM"].units == "lin"


def test_build_fetch_configs_passes_units():
    """build_fetch_configs must include units in the config dict for FredService."""
    batches = build_fetch_configs("2016-01-01")

    # Find CPI config in US batch
    us_configs = {cfg["series_id"]: cfg for cfg in batches["US"]}
    assert us_configs["CPIAUCSL"]["units"] == "pc1"
    assert us_configs["PAYEMS"]["units"] == "pc1"
    assert us_configs["INDPRO"]["units"] == "pc1"
    assert us_configs["PCEPILFE"]["units"] == "pc1"

    # Stationary series keep lin
    assert us_configs["DFF"]["units"] == "lin"
    assert us_configs["VIXCLS"]["units"] == "lin"

    # EU batch
    eu_configs = {cfg["series_id"]: cfg for cfg in batches["EUROPE"]}
    assert eu_configs["CP0000EZ19M086NEST"]["units"] == "pc1"
    assert eu_configs["CLVMNACSCAB1GQEA19"]["units"] == "pc1"
    assert eu_configs["ECBDFR"]["units"] == "lin"

    # Credit batch should have units key too
    if "CREDIT" in batches:
        for cfg in batches["CREDIT"]:
            assert "units" in cfg, f"Credit config for {cfg['series_id']} missing 'units'"


# ── Math invariant: pc1-transformed series can produce non-saturated percentile ──


def test_percentile_rank_on_yoy_change_is_not_saturated():
    """With pc1 transform, monthly CPI year-over-year change varies in [-2, +15]
    range historically. Recent CPI YoY (post-2022 spike) should rank near the
    middle, not saturated — variable signal."""
    # Synthetic 10-year YoY history (e.g., 2015-2024 monthly):
    # Pre-2021 CPI YoY ~ 2%; 2021-22 spike to ~9%; 2023-24 declining 3-4%
    history = np.array(
        [2.0] * 72  # 2015-2020: stable ~2%
        + [3.0, 4.5, 6.5, 8.0, 9.0, 8.5]  # 2021 H1
        + [9.5, 9.0, 8.5, 7.5, 7.0, 6.5]  # 2021 H2
        + [6.0] * 12  # 2022
        + [4.0] * 12  # 2023
        + [3.0] * 6  # 2024 H1
    )
    # Current: 3.0 (recent observation)
    rank = percentile_rank_score(3.0, history, invert=False)
    # Should be neither 0 nor 100 — varies meaningfully
    assert 30 < rank < 80


def test_percentile_rank_on_raw_level_pre_fix_saturates():
    """Demonstration: percentile rank on monotonic increasing raw levels
    saturates at 100 — pre-fix behavior. Useful as regression guard."""
    history = np.arange(100, 200, dtype=float)  # 100 strictly increasing values
    current = 199.0  # max
    rank = percentile_rank_score(current, history, invert=False)
    assert rank == 100.0  # Confirms the saturation pattern
    # With invert: score becomes 0 (max stress), permanent
    rank_inverted = percentile_rank_score(current, history, invert=True)
    assert rank_inverted == 0.0
