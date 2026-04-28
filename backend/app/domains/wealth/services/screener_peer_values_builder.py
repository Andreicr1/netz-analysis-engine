"""Build peer_values cohorts for screener Layer 3.

Cohorts are formed by strategy_label (matches peer_group_service convention
post-Q60). For instruments without a strategy_label (e.g., bonds), fall back
to instrument_type cohort.

Pure logic — no DB. Caller provides instrument metadata + per-instrument
risk metrics.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


def build_peer_cohorts(
    instruments: list[dict[str, Any]],
) -> dict[str, list[uuid.UUID]]:
    """Group instruments into peer cohorts.

    Cohort key: strategy_label if present, else instrument_type.

    Returns:
        Dict of cohort_key -> list of instrument_id in that cohort.
    """
    cohorts: dict[str, list[uuid.UUID]] = defaultdict(list)
    for inst in instruments:
        attrs = inst.get("attributes", {}) or {}
        strategy = attrs.get("strategy_label")
        cohort_key = str(strategy) if strategy else f"type:{inst['instrument_type']}"
        cohorts[cohort_key].append(inst["instrument_id"])
    return dict(cohorts)


def build_peer_values_for_cohort(
    cohort_metrics: list[dict[str, float | None]],
    metric_names: list[str],
) -> dict[str, list[float]]:
    """Build peer_values dict for a single cohort.

    Args:
        cohort_metrics: List of metric dicts for all instruments in the cohort.
        metric_names: Metric names to extract.

    Returns:
        Dict of metric_name -> list of non-None values across cohort.
    """
    peer_values: dict[str, list[float]] = {name: [] for name in metric_names}
    for metrics in cohort_metrics:
        for name in metric_names:
            val = metrics.get(name)
            if val is not None:
                try:
                    fval = float(val)
                except (ValueError, TypeError):
                    continue
                # Skip NaN values
                if fval != fval:  # noqa: PLR0124
                    continue
                peer_values[name].append(fval)
    return peer_values


def build_per_instrument_peer_values(
    instruments: list[dict[str, Any]],
    instrument_metrics_by_id: dict[uuid.UUID, dict[str, float | None]],
    metric_names_by_type: dict[str, list[str]],
) -> dict[uuid.UUID, dict[str, list[float]]]:
    """Build per-instrument peer_values mapping.

    For each instrument, compute the peer_values dict from its cohort
    (strategy_label-based or fallback to instrument_type).

    Args:
        instruments: List of instrument dicts (with instrument_id, instrument_type, attributes).
        instrument_metrics_by_id: Map of instrument_id -> metric dict.
        metric_names_by_type: Map of instrument_type -> list of metric names to include.

    Returns:
        Dict of instrument_id -> peer_values dict (metric_name -> list of cohort values).
    """
    cohorts = build_peer_cohorts(instruments)
    inst_to_cohort: dict[uuid.UUID, str] = {}
    for cohort_key, inst_ids in cohorts.items():
        for inst_id in inst_ids:
            inst_to_cohort[inst_id] = cohort_key

    # Build lookup: instrument_id -> instrument dict
    inst_by_id: dict[uuid.UUID, dict[str, Any]] = {
        i["instrument_id"]: i for i in instruments
    }

    cohort_peer_values: dict[str, dict[str, list[float]]] = {}
    for cohort_key, cohort_inst_ids in cohorts.items():
        cohort_metrics = [
            instrument_metrics_by_id.get(iid, {}) for iid in cohort_inst_ids
        ]
        # Determine metric names from the first instrument's type in the cohort
        instrument_type = next(
            (inst_by_id[iid]["instrument_type"] for iid in cohort_inst_ids if iid in inst_by_id),
            "fund",
        )
        # Check for asset_class-specific metric names
        first_inst = next((inst_by_id[iid] for iid in cohort_inst_ids if iid in inst_by_id), None)
        if first_inst:
            attrs = first_inst.get("attributes", {}) or {}
            asset_class = attrs.get("asset_class", "")
            if asset_class == "fixed_income":
                instrument_type = "fund_fixed_income"
            elif asset_class == "cash":
                instrument_type = "fund_cash"
            elif asset_class == "alternatives":
                instrument_type = "fund_alternatives"

        metric_names = metric_names_by_type.get(instrument_type, [])
        cohort_peer_values[cohort_key] = build_peer_values_for_cohort(
            cohort_metrics, metric_names,
        )

    result: dict[uuid.UUID, dict[str, list[float]]] = {}
    for inst in instruments:
        inst_id = inst["instrument_id"]
        cohort_key = inst_to_cohort.get(inst_id)
        if cohort_key:
            result[inst_id] = cohort_peer_values[cohort_key]
        else:
            result[inst_id] = {}
    return result


# Metric names per instrument_type (matches ScreenerService._compute_layer3_score dispatch)
METRIC_NAMES_BY_TYPE: dict[str, list[str]] = {
    "fund": ["sharpe_ratio", "max_drawdown", "pct_positive_months", "annual_volatility_pct"],
    "equity": ["sharpe_ratio", "max_drawdown", "pct_positive_months", "annual_volatility_pct"],
    "bond": ["spread_vs_benchmark", "liquidity_score", "duration_efficiency"],
    "fund_fixed_income": [
        "empirical_duration", "credit_beta", "yield_proxy_12m",
        "duration_adj_drawdown", "sharpe_ratio",
    ],
    "fund_cash": [
        "yield_vs_risk_free", "nav_stability", "liquidity_quality",
        "maturity_discipline", "fee_efficiency",
    ],
    "fund_alternatives": [
        "diversification_value", "downside_protection", "crisis_alpha",
        "inflation_hedge", "risk_adjusted_return", "fee_efficiency",
    ],
}
