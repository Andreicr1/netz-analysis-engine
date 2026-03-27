"""Macro snapshot builder — pure function assembling regional snapshots.

Receives raw FRED observations from the worker and computes:
- Regional macro scores for US, Europe, Asia, EM
- Global indicator scores (geopolitical, energy, commodity, USD)

No I/O, no DB, no async.  Worker handles all data fetching and persistence.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from quant_engine.fred_service import FredObservation
from quant_engine.regional_macro_service import (
    BisDataPoint,
    GlobalIndicatorsResult,
    ImfDataPoint,
    RegionalMacroResult,
    RegionalScoringConfig,
    enrich_region_score,
    resolve_scoring_config,
    score_global_indicators,
    score_region,
)


def build_regional_snapshot(
    raw_observations: dict[str, list[FredObservation]],
    *,
    as_of: date | None = None,
    config: dict[str, Any] | None = None,
    bis_data: list[BisDataPoint] | None = None,
    imf_data: list[ImfDataPoint] | None = None,
) -> dict[str, Any]:
    """Build v1 regional macro snapshot from raw FRED data.

    Args:
        raw_observations: Mapping series_id → list[FredObservation] (asc order).
            Produced by FredService.fetch_batch_concurrent().
        as_of: Reference date (defaults to today).
        config: Raw config dict from ConfigService (contains regional_scoring key).
        bis_data: Optional BIS credit cycle data for 7th dimension enrichment.
        imf_data: Optional IMF WEO forecasts for growth score blending.

    Returns:
        Snapshot dict suitable for storing in macro_regional_snapshots.data_json.
        Structure:
        {
            "version": 1,
            "as_of_date": "2026-03-15",
            "regions": {
                "US": { "composite_score": 62.5, "dimensions": {...}, ... },
                "EUROPE": { ... },
                ...
            },
            "global_indicators": {
                "geopolitical_risk_score": 45.2,
                "energy_stress": 55.1,
                ...
            },
        }

    """
    if as_of is None:
        as_of = date.today()

    scoring_config: RegionalScoringConfig = resolve_scoring_config(config)

    # Score each region
    regions: dict[str, dict[str, Any]] = {}
    for region in ("US", "EUROPE", "ASIA", "EM"):
        result: RegionalMacroResult = score_region(
            region, raw_observations, as_of, scoring_config,
        )
        # Enrich with BIS credit cycle + IMF growth blend (no-op if data is None)
        result = enrich_region_score(result, bis_data=bis_data, imf_data=imf_data)
        regions[region] = _serialize_regional_result(result)

    # Score global indicators
    global_result: GlobalIndicatorsResult = score_global_indicators(
        raw_observations, as_of,
    )

    return {
        "version": 1,
        "as_of_date": as_of.isoformat(),
        "regions": regions,
        "global_indicators": {
            "geopolitical_risk_score": global_result.geopolitical_risk_score,
            "energy_stress": global_result.energy_stress,
            "commodity_stress": global_result.commodity_stress,
            "usd_strength": global_result.usd_strength,
        },
    }


def _serialize_regional_result(result: RegionalMacroResult) -> dict[str, Any]:
    """Serialize a RegionalMacroResult to a JSON-safe dict."""
    return {
        "composite_score": result.composite_score,
        "coverage": result.coverage,
        "dimensions": {
            dim: {
                "score": ds.score,
                "n_indicators": ds.n_indicators,
                "indicators": ds.indicators,
            }
            for dim, ds in result.dimensions.items()
        },
        "data_freshness": {
            sid: {
                "last_date": df.last_date.isoformat() if df.last_date else None,
                "days_stale": df.days_stale,
                "weight": df.weight,
                "status": df.status,
            }
            for sid, df in result.data_freshness.items()
        },
    }
