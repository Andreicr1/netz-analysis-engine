"""Tests for ConfigWriter — unit tests for validation and hashing logic."""

from __future__ import annotations

import pytest

from app.domains.admin.services.config_writer import _hash_config, _validate_against_guardrails


class TestHashConfig:
    def test_deterministic(self):
        config = {"a": 1, "b": 2}
        assert _hash_config(config) == _hash_config(config)

    def test_different_configs_different_hashes(self):
        assert _hash_config({"a": 1}) != _hash_config({"a": 2})

    def test_key_order_invariant(self):
        """sort_keys ensures order doesn't matter."""
        assert _hash_config({"b": 2, "a": 1}) == _hash_config({"a": 1, "b": 2})

    def test_returns_16_char_hex(self):
        result = _hash_config({"x": 1})
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_nested_config(self):
        config = {"outer": {"inner": [1, 2, 3]}}
        h = _hash_config(config)
        assert isinstance(h, str)
        assert len(h) == 16

    def test_empty_config(self):
        h = _hash_config({})
        assert isinstance(h, str)
        assert len(h) == 16


class TestGuardrailValidation:
    def test_no_guardrails(self):
        """No guardrails (None) -> no errors."""
        assert _validate_against_guardrails({"any": "thing"}, None) == []

    def test_empty_guardrails(self):
        """Empty dict guardrails -> no errors."""
        assert _validate_against_guardrails({"any": "thing"}, {}) == []

    def test_valid_config(self):
        guardrails = {
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "minimum": 0, "maximum": 100},
            },
        }
        errors = _validate_against_guardrails({"threshold": 50}, guardrails)
        # If jsonschema is installed, should pass with no errors
        # If not installed, may return a warning — either way, should not crash
        assert isinstance(errors, list)

    def test_invalid_config(self):
        guardrails = {
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "minimum": 0, "maximum": 100},
            },
        }
        errors = _validate_against_guardrails({"threshold": 200}, guardrails)
        # jsonschema should catch the maximum violation
        assert isinstance(errors, list)
        # If jsonschema is available, we expect an error
        try:
            import jsonschema  # noqa: F401
            assert len(errors) >= 1
        except ImportError:
            pass  # graceful degradation

    def test_type_mismatch(self):
        guardrails = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }
        errors = _validate_against_guardrails({"name": 12345}, guardrails)
        assert isinstance(errors, list)
        try:
            import jsonschema  # noqa: F401
            assert len(errors) >= 1
        except ImportError:
            pass


class TestConfigServiceDeepMerge:
    """Test deep_merge depth guard."""

    def test_deep_merge_basic(self):
        from app.core.config.config_service import ConfigService

        result = ConfigService.deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_deep_merge_override(self):
        from app.core.config.config_service import ConfigService

        result = ConfigService.deep_merge({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_deep_merge_nested(self):
        from app.core.config.config_service import ConfigService

        base = {"nested": {"a": 1, "b": 2}}
        override = {"nested": {"b": 3, "c": 4}}
        result = ConfigService.deep_merge(base, override)
        assert result == {"nested": {"a": 1, "b": 3, "c": 4}}

    def test_deep_merge_list_replaced(self):
        """Lists are REPLACED, not appended."""
        from app.core.config.config_service import ConfigService

        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = ConfigService.deep_merge(base, override)
        assert result == {"items": [4, 5]}

    def test_deep_merge_depth_limit(self):
        from app.core.config.config_service import ConfigService

        # Build deeply nested dict > 20 levels — both base and override
        # must have dicts at the same keys to trigger recursive merging
        def _build_nested(depth: int) -> dict:
            d = {"leaf": "val"}
            for i in range(depth):
                d = {"n": d}
            return d

        deep = _build_nested(22)
        with pytest.raises(ValueError, match="depth"):
            ConfigService.deep_merge(deep, deep)

    def test_deep_merge_base_unchanged(self):
        """deep_merge should not mutate the base dict."""
        from app.core.config.config_service import ConfigService

        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"c": 3, "d": 4}}
        ConfigService.deep_merge(base, override)
        assert base == {"a": 1, "b": {"c": 2}}
