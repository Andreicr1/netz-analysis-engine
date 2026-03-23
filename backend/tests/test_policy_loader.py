"""Tests for ai_engine.governance.policy_loader — policy threshold resolution."""
from __future__ import annotations

import pytest

from ai_engine.governance.policy_loader import (
    PolicyThresholds,
    ThresholdEntry,
    _DEFAULTS,
    _build_context,
    _dedup_chunks,
    _first_source,
    invalidate_cache,
    resolve_governance_policy,
)


# ── PolicyThresholds defaults ────────────────────────────────────


class TestPolicyThresholdsDefaults:
    def test_defaults_are_populated(self):
        t = PolicyThresholds()
        assert t.single_manager_pct.value == 35.0
        assert t.single_manager_pct.source == "DEFAULT"

    def test_all_default_fields_exist(self):
        t = PolicyThresholds()
        for field_name in _DEFAULTS:
            assert hasattr(t, field_name), f"Missing field: {field_name}"
            entry = getattr(t, field_name)
            assert isinstance(entry, ThresholdEntry)

    def test_summary_returns_subset(self):
        t = PolicyThresholds()
        s = t.summary()
        assert "single_manager_pct" in s
        assert s["single_manager_pct"]["limit"] == 35.0
        assert s["single_manager_pct"]["source"] == "DEFAULT"

    def test_hard_limits_dict_returns_numeric(self):
        t = PolicyThresholds()
        d = t.hard_limits_dict()
        assert isinstance(d["single_manager_pct"], float)
        assert d["single_manager_pct"] == 35.0
        assert len(d) == 8  # 8 hard limits

    def test_to_dict_returns_full_dict(self):
        t = PolicyThresholds()
        d = t.to_dict()
        assert "single_manager_pct" in d
        assert "raw_policy" in d
        assert "load_errors" in d

    def test_list_type_defaults(self):
        t = PolicyThresholds()
        assert isinstance(t.board_override_triggers.value, list)
        assert "single_manager" in t.board_override_triggers.value
        assert isinstance(t.watchlist_triggers.value, list)
        assert "covenant_breach" in t.watchlist_triggers.value


# ── resolve_governance_policy ────────────────────────────────────


class TestResolveGovernancePolicy:
    def test_none_config_returns_defaults(self):
        t = resolve_governance_policy(None)
        assert t.single_manager_pct.source == "DEFAULT"
        assert t.single_manager_pct.value == 35.0

    def test_override_numeric_field(self):
        config = {"single_manager_pct": 25.0}
        t = resolve_governance_policy(config)
        assert t.single_manager_pct.value == 25.0
        assert t.single_manager_pct.source == "ConfigService"

    def test_override_string_numeric(self):
        config = {"single_manager_pct": "20"}
        t = resolve_governance_policy(config)
        assert t.single_manager_pct.value == 20.0

    def test_override_list_field(self):
        config = {"board_override_triggers": ["foo", "bar"]}
        t = resolve_governance_policy(config)
        assert t.board_override_triggers.value == ["foo", "bar"]
        assert t.board_override_triggers.source == "ConfigService"

    def test_boolean_value_rejected(self):
        config = {"single_manager_pct": True}
        t = resolve_governance_policy(config)
        # Boolean rejected — falls back to default
        assert t.single_manager_pct.source == "DEFAULT"

    def test_invalid_value_rejected(self):
        config = {"single_manager_pct": "not_a_number"}
        t = resolve_governance_policy(config)
        assert t.single_manager_pct.source == "DEFAULT"

    def test_unknown_fields_ignored(self):
        config = {"unknown_field": 42}
        t = resolve_governance_policy(config)
        assert t.single_manager_pct.source == "DEFAULT"

    def test_raw_policy_preserved(self):
        config = {"single_manager_pct": 20.0}
        t = resolve_governance_policy(config)
        assert t.raw_policy == config

    def test_list_with_non_string_filtered(self):
        config = {"watchlist_triggers": ["valid", 123, "also_valid"]}
        t = resolve_governance_policy(config)
        assert t.watchlist_triggers.value == ["valid", "also_valid"]

    def test_multiple_overrides(self):
        config = {
            "single_manager_pct": 30.0,
            "single_investment_pct": 40.0,
            "review_frequency_days": 60,
        }
        t = resolve_governance_policy(config)
        assert t.single_manager_pct.value == 30.0
        assert t.single_investment_pct.value == 40.0
        assert t.review_frequency_days.value == 60.0
        # Non-overridden fields stay default
        assert t.single_sector_pct.source == "DEFAULT"


# ── Utility functions ────────────────────────────────────────────


class TestUtilityFunctions:
    def test_dedup_chunks_removes_duplicates(self):
        chunks = [
            {"id": "a", "content": "first"},
            {"id": "b", "content": "second"},
            {"id": "a", "content": "duplicate"},
        ]
        result = _dedup_chunks(chunks)
        assert len(result) == 2
        assert result[0]["content"] == "first"

    def test_dedup_chunks_empty(self):
        assert _dedup_chunks([]) == []

    def test_build_context_joins_chunks(self):
        chunks = [
            {"title": "Doc A", "content": "Content A"},
            {"title": "Doc B", "content": "Content B"},
        ]
        result = _build_context(chunks)
        assert "[SOURCE: Doc A]" in result
        assert "Content A" in result
        assert "---" in result

    def test_first_source_returns_title_and_id(self):
        chunks = [{"title": "My Doc", "id": "chunk-1"}]
        title, chunk_id = _first_source(chunks)
        assert title == "My Doc"
        assert chunk_id == "chunk-1"

    def test_first_source_empty_returns_empty(self):
        title, chunk_id = _first_source([])
        assert title == ""
        assert chunk_id == ""


# ── Cache ─────────────────────────────────────────────────────────


class TestCache:
    def test_invalidate_cache_resets(self):
        import ai_engine.governance.policy_loader as pl
        pl._cache = PolicyThresholds()
        assert pl._cache is not None
        invalidate_cache()
        assert pl._cache is None
