"""Tests for the sanitise helpers in ``wealth.schemas.sanitized``.

These exercise the pure functions used by the construction_run_executor
sanitise retrofit (Phase 2 Session C commit 1) and by the
``RiskTimeseriesOut`` retrofit (commit 2). No DB — pure input/output.
"""
from __future__ import annotations

from app.domains.wealth.schemas.sanitized import (
    EVENT_TYPE_LABELS,
    METRIC_LABELS,
    REGIME_LABELS,
    humanize_event_type,
    sanitize_payload,
)


def test_humanize_event_type_known_mapping() -> None:
    assert humanize_event_type("optimizer_started") == "Optimizer started"
    assert humanize_event_type("narrative_started") == "Narrative generation started"
    assert humanize_event_type("run_failed") == "Construction failed"


def test_humanize_event_type_unknown_passes_through() -> None:
    assert humanize_event_type("some_new_event") == "some_new_event"


def test_event_type_labels_covers_all_worker_emitted_types() -> None:
    """The executor emits these raw types — every one must have a label."""
    emitted = {
        "run_started",
        "run_succeeded",
        "run_failed",
        "run_cancelled",
        "optimizer_started",
        "stress_started",
        "advisor_started",
        "validation_started",
        "narrative_started",
    }
    missing = emitted - EVENT_TYPE_LABELS.keys()
    assert not missing, f"Missing labels for emitted event types: {missing}"


def test_sanitize_payload_translates_metric_keys() -> None:
    raw = {
        "cvar_95": 0.042,
        "volatility_garch": 0.18,
        "max_drawdown": -0.22,
        "unknown_key": 7,
    }
    out = sanitize_payload(raw)
    assert out[METRIC_LABELS["cvar_95"]] == 0.042
    assert out[METRIC_LABELS["volatility_garch"]] == 0.18
    assert out[METRIC_LABELS["max_drawdown"]] == -0.22
    assert out["unknown_key"] == 7


def test_sanitize_payload_translates_regime_string_values() -> None:
    raw = {"global_regime": "RISK_ON", "regional_regimes": {"US": "RISK_OFF"}}
    out = sanitize_payload(raw)
    assert out["global_regime"] == REGIME_LABELS["RISK_ON"] == "Expansion"
    assert out["regional_regimes"]["US"] == REGIME_LABELS["RISK_OFF"] == "Cautious"


def test_sanitize_payload_walks_nested_dicts_and_lists() -> None:
    raw = {
        "phase": "optimizer",
        "results": [
            {"cvar_95": 0.05, "regime": "CRISIS"},
            {"cvar_95": 0.07, "regime": "EXPANSION"},
        ],
    }
    out = sanitize_payload(raw)
    assert out["phase"] == "optimizer"
    # Both the key (regime → "Market Regime") AND the value (CRISIS → Stress)
    # get translated in a single recursive walk.
    regime_key = METRIC_LABELS["regime"]
    cvar_key = METRIC_LABELS["cvar_95"]
    assert out["results"][0][regime_key] == "Stress"
    assert out["results"][0][cvar_key] == 0.05
    assert out["results"][1][regime_key] == "Expansion"


def test_sanitize_payload_is_non_mutating() -> None:
    raw = {"cvar_95": 0.05, "global_regime": "RISK_ON"}
    sanitize_payload(raw)
    # Original keys still intact
    assert "cvar_95" in raw
    assert raw["global_regime"] == "RISK_ON"


def test_sanitize_payload_primitives_pass_through() -> None:
    assert sanitize_payload(42) == 42
    assert sanitize_payload(3.14) == 3.14
    assert sanitize_payload(None) is None
    assert sanitize_payload(True) is True
    assert sanitize_payload("arbitrary string") == "arbitrary string"


def test_sanitize_payload_empty_container() -> None:
    assert sanitize_payload({}) == {}
    assert sanitize_payload([]) == []
