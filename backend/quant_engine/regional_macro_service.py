"""Regional macro scoring service — percentile-rank composites for 4 regions + global indicators.

Pure sync functions — no DB, no async, no I/O.  Config injected as parameter.
All result types are frozen dataclasses for thread safety across async/sync boundary.

Normalization: expanding-window percentile rank over full available history.
Each indicator maps to 0-100 where 50 = historical median.
Source: Macrosynergy Research (2024) — institutional standard for macro scorecards.

Staleness: linear weight decay with per-frequency config.
Composite: weighted average of dimension scores; dimensions with no data excluded
from denominator.  Coverage threshold: min 50% of total weight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

import numpy as np
import structlog

from quant_engine.fred_service import FredObservation

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
#  Configuration types
# ---------------------------------------------------------------------------


class StalenessConfig(TypedDict):
    fresh_days: int
    max_useful_days: int
    floor: float


class RegionalScoringConfig(TypedDict, total=False):
    lookback_years: int
    dimension_weights: dict[str, float]
    min_coverage: float
    staleness: dict[str, StalenessConfig]


_DEFAULT_CONFIG: RegionalScoringConfig = {
    "lookback_years": 10,
    "dimension_weights": {
        "growth": 0.20,
        "inflation": 0.20,
        "monetary": 0.15,
        "financial_conditions": 0.20,
        "labor": 0.15,
        "sentiment": 0.10,
    },
    "min_coverage": 0.50,
    "staleness": {
        "daily": {"fresh_days": 3, "max_useful_days": 10, "floor": 0.30},
        "weekly": {"fresh_days": 10, "max_useful_days": 30, "floor": 0.40},
        "monthly": {"fresh_days": 45, "max_useful_days": 90, "floor": 0.50},
        "quarterly": {"fresh_days": 100, "max_useful_days": 180, "floor": 0.50},
    },
}

# Minimum observations for percentile rank to be meaningful (10yr of monthly data)
MIN_HISTORY_OBS = 60


def resolve_scoring_config(config: dict[str, Any] | None) -> RegionalScoringConfig:
    """Extract regional scoring config from ConfigService dict, with defaults."""
    if config is None:
        return _DEFAULT_CONFIG
    raw = config.get("regional_scoring", {})
    if not raw:
        return _DEFAULT_CONFIG
    try:
        return RegionalScoringConfig(
            lookback_years=int(raw.get("lookback_years", 10)),
            dimension_weights=raw.get("dimension_weights", _DEFAULT_CONFIG["dimension_weights"]),
            min_coverage=float(raw.get("min_coverage", 0.50)),
            staleness=raw.get("staleness", _DEFAULT_CONFIG["staleness"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Malformed regional scoring config, using defaults", error=str(e))
        return _DEFAULT_CONFIG


# ---------------------------------------------------------------------------
#  FRED Series Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeriesSpec:
    """Specification for a single FRED series."""

    series_id: str
    dimension: str
    label: str
    frequency: str  # "daily", "weekly", "monthly", "quarterly"
    invert: bool = False  # True = higher value means worse conditions


# Limit per frequency for 10yr lookback
FREQUENCY_LIMITS: dict[str, int] = {
    "daily": 2520,
    "weekly": 520,
    "monthly": 120,
    "quarterly": 40,
}


REGION_SERIES: dict[str, list[SeriesSpec]] = {
    "US": [
        SeriesSpec("A191RL1Q225SBEA", "growth", "Real GDP Growth", "quarterly"),
        SeriesSpec("INDPRO", "growth", "Industrial Production", "monthly"),
        SeriesSpec("PAYEMS", "growth", "Nonfarm Payrolls", "monthly"),
        SeriesSpec("CPIAUCSL", "inflation", "CPI All Urban", "monthly", invert=True),
        SeriesSpec("PCEPILFE", "inflation", "Core PCE", "monthly", invert=True),
        SeriesSpec("DFF", "monetary", "Fed Funds Rate", "daily", invert=True),
        SeriesSpec("DGS10", "monetary", "10Y Treasury", "daily"),
        SeriesSpec("DGS2", "monetary", "2Y Treasury", "daily"),
        SeriesSpec("NFCI", "financial_conditions", "Chicago Fed Financial Conditions", "weekly", invert=True),
        SeriesSpec("VIXCLS", "financial_conditions", "VIX", "daily", invert=True),
        SeriesSpec("UNRATE", "labor", "Unemployment Rate", "monthly", invert=True),
        SeriesSpec("JTSJOL", "labor", "JOLTS Openings", "monthly"),
        SeriesSpec("SAHMREALTIME", "labor", "Sahm Rule", "monthly", invert=True),
        SeriesSpec("UMCSENT", "sentiment", "Michigan Consumer Sentiment", "monthly"),
    ],
    "EUROPE": [
        SeriesSpec("CLVMNACSCAB1GQEA19", "growth", "Euro Area Real GDP", "quarterly"),
        SeriesSpec("CP0000EZ19M086NEST", "inflation", "Eurostat HICP EA19", "monthly", invert=True),
        SeriesSpec("ECBDFR", "monetary", "ECB Deposit Facility Rate", "daily", invert=True),
        SeriesSpec("IRLTLT01DEM156N", "monetary", "German 10Y Bund", "monthly"),
        SeriesSpec("BAMLHE00EHYIEY", "financial_conditions", "Euro HY Effective Yield", "daily", invert=True),
        SeriesSpec("CSCICP02EZM460S", "sentiment", "Consumer Confidence EA19", "monthly"),
    ],
    "ASIA": [
        SeriesSpec("JPNRGDPEXP", "growth", "Japan Real GDP", "quarterly"),
        SeriesSpec("CHNLOLITOAASTSAM", "growth", "China CLI Amplitude-Adjusted", "monthly"),
        SeriesSpec("JPNLOLITOAASTSAM", "growth", "Japan CLI Amplitude-Adjusted", "monthly"),
        SeriesSpec("JPNCPIALLMINMEI", "inflation", "Japan CPI", "monthly", invert=True),
        SeriesSpec("CHNCPIALLMINMEI", "inflation", "China CPI", "monthly", invert=True),
        SeriesSpec("IRLTLT01JPM156N", "monetary", "10Y JGB Yield", "monthly"),
        SeriesSpec("BAMLEMRACRPIASIAOAS", "financial_conditions", "Asia EM Corp OAS", "daily", invert=True),
    ],
    "EM": [
        SeriesSpec("BRALOLITOAASTSAM", "growth", "Brazil CLI Amplitude-Adjusted", "monthly"),
        SeriesSpec("INDLOLITOAASTSAM", "growth", "India CLI Amplitude-Adjusted", "monthly"),
        SeriesSpec("MEXLOLITONOSTSAM", "growth", "Mexico CLI Normalized", "monthly"),
        SeriesSpec("BRACPIALLMINMEI", "inflation", "Brazil CPI", "monthly", invert=True),
        SeriesSpec("INDCPIALLMINMEI", "inflation", "India CPI", "monthly", invert=True),
        SeriesSpec("INTDSRBRM193N", "monetary", "Brazil SELIC", "monthly", invert=True),
        SeriesSpec("BAMLEMCBPIOAS", "financial_conditions", "EM Corp OAS", "daily", invert=True),
    ],
}


@dataclass(frozen=True)
class GlobalSeriesSpec:
    """Specification for a global indicator series."""

    series_id: str
    category: str
    label: str
    frequency: str
    invert: bool = False


GLOBAL_SERIES: list[GlobalSeriesSpec] = [
    GlobalSeriesSpec("GPRH", "geopolitical", "Geopolitical Risk Index", "monthly", invert=True),
    GlobalSeriesSpec("USEPUINDXD", "geopolitical", "Economic Policy Uncertainty", "daily", invert=True),
    GlobalSeriesSpec("DCOILWTICO", "energy", "WTI Crude Oil", "daily", invert=True),
    GlobalSeriesSpec("DCOILBRENTEU", "energy", "Brent Crude Oil", "daily", invert=True),
    GlobalSeriesSpec("DHHNGSP", "energy", "Henry Hub Natural Gas", "daily", invert=True),
    GlobalSeriesSpec("WCSSTUS1", "reserves", "US Strategic Petroleum Reserve", "weekly"),
    GlobalSeriesSpec("WCESTUS1", "reserves", "US Crude Oil Inventories", "weekly"),
    GlobalSeriesSpec("PCOPPUSDM", "metals", "Global Copper Price", "monthly"),
    GlobalSeriesSpec("GOLDAMGBD228NLBM", "metals", "London Gold Price", "daily"),
    GlobalSeriesSpec("PFERTINDEXM", "agriculture", "Fertilizer Price Index", "monthly", invert=True),
    GlobalSeriesSpec("DTWEXBGS", "currency", "USD Trade-Weighted Index", "daily"),
]


def get_all_series_ids() -> list[str]:
    """Return flat list of all FRED series IDs across regions + global."""
    ids: list[str] = []
    for specs in REGION_SERIES.values():
        ids.extend(s.series_id for s in specs)
    ids.extend(s.series_id for s in GLOBAL_SERIES)
    return ids


def build_fetch_configs(
    observation_start: str,
) -> dict[str, list[dict[str, Any]]]:
    """Build domain-batched fetch configs for FredService.fetch_batch_concurrent().

    Returns dict keyed by domain name (US, EUROPE, ASIA, EM, GLOBAL)
    with list of fetch config dicts per domain.
    """
    batches: dict[str, list[dict[str, Any]]] = {}

    for region, specs in REGION_SERIES.items():
        configs: list[dict[str, Any]] = []
        for s in specs:
            configs.append({
                "series_id": s.series_id,
                "limit": FREQUENCY_LIMITS.get(s.frequency, 120),
                "observation_start": observation_start,
                "sort_order": "asc",
            })
        batches[region] = configs

    global_configs: list[dict[str, Any]] = []
    for s in GLOBAL_SERIES:
        global_configs.append({
            "series_id": s.series_id,
            "limit": FREQUENCY_LIMITS.get(s.frequency, 120),
            "observation_start": observation_start,
            "sort_order": "asc",
        })
    batches["GLOBAL"] = global_configs

    return batches


# ---------------------------------------------------------------------------
#  Result types (frozen for thread safety)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataFreshness:
    """Staleness metadata for a single indicator."""

    series_id: str
    last_date: date | None
    days_stale: int | None
    weight: float  # 0.0-1.0 staleness-adjusted weight
    status: str  # "fresh", "decaying", "stale"


@dataclass(frozen=True)
class DimensionScore:
    """Score for a single macro dimension (e.g. growth, inflation)."""

    dimension: str
    score: float  # 0-100 composite of indicators in this dimension
    n_indicators: int
    indicators: dict[str, float] = field(default_factory=dict)  # series_id → score


@dataclass(frozen=True)
class RegionalMacroResult:
    """Complete macro scoring result for a single region."""

    region: str
    composite_score: float  # 0-100
    dimensions: dict[str, DimensionScore]
    data_freshness: dict[str, DataFreshness]
    as_of_date: date
    coverage: float  # 0-1, fraction of total weight with data


@dataclass(frozen=True)
class GlobalIndicatorsResult:
    """Global macro risk indicators."""

    geopolitical_risk_score: float  # GPR + EPU composite (0-100)
    energy_stress: float  # oil, gas, reserves (0-100, higher = more stress)
    commodity_stress: float  # copper, gold, fertilizer (0-100)
    usd_strength: float  # trade-weighted index percentile (0-100)
    as_of_date: date


# ---------------------------------------------------------------------------
#  Scoring functions
# ---------------------------------------------------------------------------


def percentile_rank_score(
    current: float,
    history: np.ndarray,
    *,
    invert: bool = False,
) -> float:
    """0-100 percentile rank.  Returns 50.0 if insufficient history (<60 obs).

    Args:
        current: Current observation value.
        history: Full available history as numpy array.
        invert: If True, higher raw values map to lower scores
                (e.g. VIX=80 → score ~5, meaning "very bad conditions").
    """
    if len(history) < MIN_HISTORY_OBS:
        return 50.0

    rank = float(np.sum(history <= current) / len(history) * 100)
    if invert:
        rank = 100.0 - rank
    return round(rank, 2)


def compute_staleness_weight(
    last_obs_date: date | None,
    as_of: date,
    frequency: str,
    staleness_config: dict[str, StalenessConfig],
) -> DataFreshness:
    """Compute staleness-adjusted weight for a single indicator.

    Linear decay from 1.0 (within fresh window) to floor (at max_useful_days).
    Beyond max_useful_days → weight = 0.0 (effectively excluded).
    """
    if last_obs_date is None:
        return DataFreshness(
            series_id="",
            last_date=None,
            days_stale=None,
            weight=0.0,
            status="stale",
        )

    days_stale = (as_of - last_obs_date).days
    freq_config = staleness_config.get(frequency, staleness_config.get("monthly", {
        "fresh_days": 45, "max_useful_days": 90, "floor": 0.50,
    }))

    fresh_days = freq_config["fresh_days"]
    max_useful = freq_config["max_useful_days"]
    floor = freq_config["floor"]

    if days_stale <= fresh_days:
        weight = 1.0
        status = "fresh"
    elif days_stale <= max_useful:
        decay_range = max_useful - fresh_days
        decay_progress = (days_stale - fresh_days) / decay_range
        weight = max(floor, 1.0 - decay_progress * (1.0 - floor))
        status = "decaying"
    else:
        weight = 0.0
        status = "stale"

    return DataFreshness(
        series_id="",
        last_date=last_obs_date,
        days_stale=days_stale,
        weight=round(weight, 4),
        status=status,
    )


def _extract_history(
    observations: list[FredObservation],
) -> tuple[np.ndarray, date | None]:
    """Extract numeric values and latest date from observations."""
    values: list[float] = []
    latest_date: date | None = None

    for obs in observations:
        if obs.value is not None:
            values.append(obs.value)
            obs_date = date.fromisoformat(obs.date)
            if latest_date is None or obs_date > latest_date:
                latest_date = obs_date

    return np.array(values, dtype=np.float64), latest_date


def score_region(
    region: str,
    raw_observations: dict[str, list[FredObservation]],
    as_of: date,
    config: RegionalScoringConfig,
) -> RegionalMacroResult:
    """Compute composite macro score for a single region.

    Args:
        region: Region key (US, EUROPE, ASIA, EM).
        raw_observations: Mapping series_id → observations (asc order).
        as_of: Reference date for staleness computation.
        config: Scoring configuration.
    """
    specs = REGION_SERIES.get(region, [])
    if not specs:
        return RegionalMacroResult(
            region=region,
            composite_score=50.0,
            dimensions={},
            data_freshness={},
            as_of_date=as_of,
            coverage=0.0,
        )

    dim_weights = config.get("dimension_weights", _DEFAULT_CONFIG["dimension_weights"])
    staleness_cfg = config.get("staleness", _DEFAULT_CONFIG["staleness"])
    min_coverage = config.get("min_coverage", 0.50)

    # Score each indicator
    indicator_scores: dict[str, float] = {}
    freshness_map: dict[str, DataFreshness] = {}

    for spec in specs:
        obs = raw_observations.get(spec.series_id, [])
        history, last_date = _extract_history(obs)

        if len(history) == 0:
            freshness = DataFreshness(
                series_id=spec.series_id,
                last_date=None,
                days_stale=None,
                weight=0.0,
                status="stale",
            )
            freshness_map[spec.series_id] = freshness
            continue

        current = float(history[-1])  # observations in asc order
        score = percentile_rank_score(current, history, invert=spec.invert)
        indicator_scores[spec.series_id] = score

        freshness = compute_staleness_weight(last_date, as_of, spec.frequency, staleness_cfg)
        freshness_map[spec.series_id] = DataFreshness(
            series_id=spec.series_id,
            last_date=freshness.last_date,
            days_stale=freshness.days_stale,
            weight=freshness.weight,
            status=freshness.status,
        )

    # Group by dimension
    dim_indicator_map: dict[str, list[tuple[str, float, float]]] = {}
    for spec in specs:
        if spec.series_id not in indicator_scores:
            continue
        score = indicator_scores[spec.series_id]
        weight = freshness_map[spec.series_id].weight
        if weight <= 0:
            continue
        dim_indicator_map.setdefault(spec.dimension, []).append(
            (spec.series_id, score, weight)
        )

    # Compute dimension scores (staleness-weighted average within dimension)
    dimensions: dict[str, DimensionScore] = {}
    for dim, indicators in dim_indicator_map.items():
        total_w = sum(w for _, _, w in indicators)
        if total_w <= 0:
            continue
        weighted_score = sum(s * w for _, s, w in indicators) / total_w
        dimensions[dim] = DimensionScore(
            dimension=dim,
            score=round(weighted_score, 2),
            n_indicators=len(indicators),
            indicators={sid: s for sid, s, _ in indicators},
        )

    # Compute composite (dimension-weight-weighted average)
    active_weight = sum(dim_weights.get(d, 0) for d in dimensions)
    total_possible_weight = sum(dim_weights.values())
    coverage = active_weight / total_possible_weight if total_possible_weight > 0 else 0.0

    if coverage < min_coverage:
        composite = 50.0  # insufficient coverage — return neutral
        logger.warning(
            "Insufficient macro data coverage for region",
            region=region,
            coverage=round(coverage, 2),
            min_coverage=min_coverage,
        )
    else:
        composite_sum = sum(
            dimensions[d].score * dim_weights.get(d, 0)
            for d in dimensions
        )
        composite = composite_sum / active_weight if active_weight > 0 else 50.0

    return RegionalMacroResult(
        region=region,
        composite_score=round(composite, 2),
        dimensions=dimensions,
        data_freshness=freshness_map,
        as_of_date=as_of,
        coverage=round(coverage, 4),
    )


def score_global_indicators(
    raw_observations: dict[str, list[FredObservation]],
    as_of: date,
) -> GlobalIndicatorsResult:
    """Compute global indicator scores from raw observations.

    Categories: geopolitical risk, energy stress, commodity stress, USD strength.
    Each is a percentile-rank composite of its constituent series.
    """
    # Build lookup for per-series invert flags from registry
    _global_invert: dict[str, bool] = {s.series_id: s.invert for s in GLOBAL_SERIES}

    def _avg_score(series_ids: list[str]) -> float:
        scores: list[float] = []
        for sid in series_ids:
            obs = raw_observations.get(sid, [])
            history, _ = _extract_history(obs)
            if len(history) == 0:
                continue
            current = float(history[-1])
            scores.append(percentile_rank_score(
                current, history, invert=_global_invert.get(sid, False),
            ))
        return round(sum(scores) / len(scores), 2) if scores else 50.0

    # Geopolitical: GPR + EPU (both inverted per registry)
    geopolitical = _avg_score(["GPRH", "USEPUINDXD"])

    # Energy stress: prices (inverted) + reserves (not inverted)
    energy_price = _avg_score(["DCOILWTICO", "DCOILBRENTEU", "DHHNGSP"])
    energy_reserves = _avg_score(["WCSSTUS1", "WCESTUS1"])
    # Low reserves + high prices = stress
    energy_stress = round((energy_price * 0.6 + (100.0 - energy_reserves) * 0.4), 2)

    # Commodity stress: per-series invert from registry
    commodity = _avg_score(["PCOPPUSDM", "GOLDAMGBD228NLBM", "PFERTINDEXM"])

    # USD strength: straight percentile (not inverted per registry)
    usd = _avg_score(["DTWEXBGS"])

    return GlobalIndicatorsResult(
        geopolitical_risk_score=geopolitical,
        energy_stress=energy_stress,
        commodity_stress=commodity,
        usd_strength=usd,
        as_of_date=as_of,
    )
