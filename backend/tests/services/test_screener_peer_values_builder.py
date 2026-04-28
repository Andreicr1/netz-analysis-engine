"""Unit tests for the peer cohort builder (S08-F04 wiring helper)."""

from __future__ import annotations

import uuid

from app.domains.wealth.services.screener_peer_values_builder import (
    METRIC_NAMES_BY_TYPE,
    build_peer_cohorts,
    build_peer_values_for_cohort,
    build_per_instrument_peer_values,
)


def test_build_peer_cohorts_groups_by_strategy_label() -> None:
    instruments = [
        {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
         "attributes": {"strategy_label": "Long/Short Equity"}},
        {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
         "attributes": {"strategy_label": "Long/Short Equity"}},
        {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
         "attributes": {"strategy_label": "Private Credit"}},
    ]
    cohorts = build_peer_cohorts(instruments)
    assert "Long/Short Equity" in cohorts
    assert "Private Credit" in cohorts
    assert len(cohorts["Long/Short Equity"]) == 2
    assert len(cohorts["Private Credit"]) == 1


def test_build_peer_cohorts_falls_back_to_instrument_type() -> None:
    instruments = [
        {"instrument_id": uuid.uuid4(), "instrument_type": "bond",
         "attributes": {}},
        {"instrument_id": uuid.uuid4(), "instrument_type": "bond",
         "attributes": {}},
    ]
    cohorts = build_peer_cohorts(instruments)
    assert "type:bond" in cohorts
    assert len(cohorts["type:bond"]) == 2


def test_build_peer_cohorts_none_attributes() -> None:
    instruments = [
        {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
         "attributes": None},
    ]
    cohorts = build_peer_cohorts(instruments)
    assert "type:fund" in cohorts


def test_build_peer_values_for_cohort_filters_none_and_nan() -> None:
    cohort_metrics = [
        {"sharpe_ratio": 1.5, "max_drawdown": -0.1},
        {"sharpe_ratio": None, "max_drawdown": -0.05},
        {"sharpe_ratio": 2.0, "max_drawdown": float("nan")},
    ]
    result = build_peer_values_for_cohort(cohort_metrics, ["sharpe_ratio", "max_drawdown"])
    assert result["sharpe_ratio"] == [1.5, 2.0]
    assert -0.1 in result["max_drawdown"] and -0.05 in result["max_drawdown"]
    # NaN excluded
    assert len(result["max_drawdown"]) == 2


def test_metric_names_by_type_covers_all_dispatch_branches() -> None:
    """Confirm METRIC_NAMES_BY_TYPE matches ScreenerService._compute_layer3_score dispatch."""
    expected_types = {"fund", "equity", "bond", "fund_fixed_income", "fund_cash", "fund_alternatives"}
    assert expected_types.issubset(METRIC_NAMES_BY_TYPE.keys())


def test_per_instrument_mapping_complete() -> None:
    """Every instrument should get a peer_values entry."""
    inst_a = {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
              "attributes": {"strategy_label": "EM Equity"}}
    inst_b = {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
              "attributes": {"strategy_label": "EM Equity"}}
    metrics = {
        inst_a["instrument_id"]: {"sharpe_ratio": 1.5, "max_drawdown": -0.10,
                                   "pct_positive_months": 0.65, "annual_volatility_pct": 14.0},
        inst_b["instrument_id"]: {"sharpe_ratio": 1.2, "max_drawdown": -0.15,
                                   "pct_positive_months": 0.55, "annual_volatility_pct": 16.0},
    }
    result = build_per_instrument_peer_values(
        [inst_a, inst_b], metrics, METRIC_NAMES_BY_TYPE,
    )
    assert inst_a["instrument_id"] in result
    assert inst_b["instrument_id"] in result
    # Both share the EM Equity cohort -> identical peer_values
    assert result[inst_a["instrument_id"]] == result[inst_b["instrument_id"]]
    # Cohort has 2 funds -> 2 values per metric
    assert len(result[inst_a["instrument_id"]]["sharpe_ratio"]) == 2


def test_per_instrument_empty_metrics() -> None:
    """Instruments with no risk metrics get empty peer_values."""
    inst_a = {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
              "attributes": {}}
    result = build_per_instrument_peer_values(
        [inst_a], {}, METRIC_NAMES_BY_TYPE,
    )
    assert inst_a["instrument_id"] in result
    # All metric lists should be empty
    for values in result[inst_a["instrument_id"]].values():
        assert values == []


def test_fi_cohort_uses_correct_metric_names() -> None:
    """FI instruments should use fund_fixed_income metric names."""
    inst_a = {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
              "attributes": {"asset_class": "fixed_income", "strategy_label": "FI Core"}}
    inst_b = {"instrument_id": uuid.uuid4(), "instrument_type": "fund",
              "attributes": {"asset_class": "fixed_income", "strategy_label": "FI Core"}}
    metrics = {
        inst_a["instrument_id"]: {"empirical_duration": 5.2, "credit_beta": 0.8,
                                   "yield_proxy_12m": 0.04, "duration_adj_drawdown": -0.02,
                                   "sharpe_ratio": 1.1},
        inst_b["instrument_id"]: {"empirical_duration": 3.1, "credit_beta": 0.5,
                                   "yield_proxy_12m": 0.03, "duration_adj_drawdown": -0.01,
                                   "sharpe_ratio": 0.9},
    }
    result = build_per_instrument_peer_values(
        [inst_a, inst_b], metrics, METRIC_NAMES_BY_TYPE,
    )
    peer_vals = result[inst_a["instrument_id"]]
    assert "empirical_duration" in peer_vals
    assert "credit_beta" in peer_vals
    assert len(peer_vals["empirical_duration"]) == 2
