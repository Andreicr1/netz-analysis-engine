"""Tests for governance policy ConfigService alignment.

Covers: resolve_governance_policy, PolicyThresholds (Pydantic),
load_policy_thresholds with config parameter, YAML seed parity.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ai_engine.governance.policy_loader import (
    _DEFAULTS,
    _KNOWN_THRESHOLD_FIELDS,
    PolicyThresholds,
    ThresholdEntry,
    invalidate_cache,
    load_policy_thresholds,
    resolve_governance_policy,
)

# ── Fixtures ────────────────────────────────────────────────────────


def _valid_config() -> dict:
    return {
        "single_manager_pct": 25.0,
        "single_investment_pct": 30.0,
        "board_override_triggers": ["single_manager", "hard_lockup"],
        "review_frequency_days": 60,
    }


# ── Test 1: resolve_governance_policy(None) returns defaults ────────


def test_resolve_none_returns_defaults():
    policy = resolve_governance_policy(None)
    assert isinstance(policy, PolicyThresholds)
    assert policy.single_manager_pct.value == 35.0
    assert policy.single_manager_pct.source == "DEFAULT"
    assert policy.raw_policy == {}


# ── Test 2: resolve with valid config ───────────────────────────────


def test_resolve_valid_config():
    config = _valid_config()
    policy = resolve_governance_policy(config)

    # Overridden fields
    assert policy.single_manager_pct.value == 25.0
    assert policy.single_manager_pct.source == "ConfigService"
    assert policy.single_investment_pct.value == 30.0
    assert policy.board_override_triggers.value == ["single_manager", "hard_lockup"]
    assert policy.review_frequency_days.value == 60.0

    # raw_policy stores the full original config
    assert policy.raw_policy == config

    # Non-overridden fields still at DEFAULT
    assert policy.single_sector_pct.value == 35.0
    assert policy.single_sector_pct.source == "DEFAULT"


# ── Test 3: partial config merges with defaults ─────────────────────


def test_resolve_partial_config():
    config = {"single_manager_pct": 20.0}
    policy = resolve_governance_policy(config)

    assert policy.single_manager_pct.value == 20.0
    assert policy.single_manager_pct.source == "ConfigService"

    # All other fields keep defaults
    for field_name in _KNOWN_THRESHOLD_FIELDS:
        if field_name == "single_manager_pct":
            continue
        entry = getattr(policy, field_name)
        assert entry.source == "DEFAULT", f"{field_name} should be DEFAULT"


# ── Test 4: bad values + booleans log error and fall back ───────────


def test_resolve_bad_value_and_bool():
    config = {
        "single_manager_pct": True,  # boolean — rejected
        "max_lockup_years": "not_a_number",  # string — rejected
        "single_sector_pct": 40.0,  # valid — accepted
    }
    policy = resolve_governance_policy(config)

    # Boolean and bad string: fall back to defaults
    assert policy.single_manager_pct.source == "DEFAULT"
    assert policy.max_lockup_years.source == "DEFAULT"

    # Valid override accepted
    assert policy.single_sector_pct.value == 40.0
    assert policy.single_sector_pct.source == "ConfigService"


# ── Test 5: unknown fields preserved in raw_policy ──────────────────


def test_resolve_unknown_fields_in_raw_policy():
    config = {
        "single_manager_pct": 25.0,
        "custom_future_field": 42,
        "another_unknown": "hello",
    }
    policy = resolve_governance_policy(config)

    assert policy.raw_policy == config
    assert policy.raw_policy["custom_future_field"] == 42
    assert policy.raw_policy["another_unknown"] == "hello"


# ── Test 6: load_policy_thresholds with config bypasses module cache ─


def test_load_with_config_bypasses_module_cache():
    invalidate_cache()
    config = {"single_manager_pct": 15.0}
    policy = load_policy_thresholds(config=config, org_id="org-123")

    assert policy.single_manager_pct.value == 15.0
    assert policy.single_manager_pct.source == "ConfigService"

    # Second call with different config for different org
    config2 = {"single_manager_pct": 10.0}
    policy2 = load_policy_thresholds(config=config2, org_id="org-456")
    assert policy2.single_manager_pct.value == 10.0

    # Cached: same org returns cached value
    policy3 = load_policy_thresholds(config=config, org_id="org-123")
    assert policy3.single_manager_pct.value == 15.0

    invalidate_cache()


# ── Test 7: YAML seed values match _DEFAULTS exactly ───────────────


def test_yaml_seed_matches_defaults():
    yaml_path = Path(__file__).resolve().parents[2] / "calibration" / "seeds" / "private_credit" / "governance_policy.yaml"
    assert yaml_path.exists(), f"YAML seed not found at {yaml_path}"

    with open(yaml_path) as f:
        seed = yaml.safe_load(f)

    for field_name, default in _DEFAULTS.items():
        expected = default["value"]
        actual = seed.get(field_name)
        assert actual is not None, f"Missing field {field_name} in YAML seed"
        if isinstance(expected, list):
            assert actual == expected, f"{field_name}: {actual} != {expected}"
        else:
            assert float(actual) == float(expected), f"{field_name}: {actual} != {expected}"

    # No extra fields in YAML beyond _DEFAULTS
    for key in seed:
        assert key in _DEFAULTS, f"Unexpected field {key} in YAML seed"


# ── Test 8: to_dict / summary / hard_limits_dict work with Pydantic ─


def test_pydantic_methods():
    policy = PolicyThresholds()

    # to_dict
    d = policy.to_dict()
    assert isinstance(d, dict)
    assert "single_manager_pct" in d
    assert d["single_manager_pct"]["value"] == 35.0
    assert d["single_manager_pct"]["source"] == "DEFAULT"

    # summary
    s = policy.summary()
    assert "single_manager_pct" in s
    assert s["single_manager_pct"]["limit"] == 35.0
    assert s["single_manager_pct"]["source"] == "DEFAULT"

    # hard_limits_dict
    h = policy.hard_limits_dict()
    assert h["single_manager_pct"] == 35.0
    assert h["max_lockup_years"] == 2.0
    assert len(h) == 8


# ── Test 9: ThresholdEntry is a Pydantic BaseModel ──────────────────


def test_threshold_entry_pydantic():
    entry = ThresholdEntry(value=42.0, source="test", rationale="test rationale")
    assert entry.value == 42.0
    d = entry.model_dump()
    assert d["value"] == 42.0
    assert d["source"] == "test"
