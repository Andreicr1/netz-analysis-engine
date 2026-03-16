"""Tests for ConfigWriter — guardrails, optimistic locking, cache invalidation."""

from __future__ import annotations

from app.core.config.config_writer import ConfigWriter, GuardrailViolation, StaleVersionError


class TestGuardrailViolation:
    def test_error_message_includes_errors(self):
        err = GuardrailViolation(["field 'x' is required", "type must be string"])
        assert "field 'x' is required" in str(err)
        assert "type must be string" in str(err)
        assert len(err.errors) == 2

    def test_single_error(self):
        err = GuardrailViolation(["invalid value"])
        assert err.errors == ["invalid value"]


class TestStaleVersionError:
    def test_error_includes_current_version(self):
        err = StaleVersionError(current_version=5)
        assert err.current_version == 5
        assert "5" in str(err)


class TestCacheInvalidation:
    def test_invalidate_specific_cache_key(self):
        """Test that _invalidate_cache removes the correct key."""
        from app.core.config.config_service import _config_cache

        # Populate cache
        _config_cache["config:credit:branding:org-123"] = {"test": True}
        assert "config:credit:branding:org-123" in _config_cache

        ConfigWriter._invalidate_cache("credit", "branding", "org-123")  # type: ignore[arg-type]
        assert "config:credit:branding:org-123" not in _config_cache

    def test_invalidate_cache_prefix(self):
        """Test that _invalidate_cache_prefix removes all matching keys."""
        from app.core.config.config_service import _config_cache

        # Populate cache with multiple orgs
        _config_cache["config:credit:branding:org-1"] = {"a": 1}
        _config_cache["config:credit:branding:org-2"] = {"b": 2}
        _config_cache["config:credit:scoring:org-1"] = {"c": 3}

        ConfigWriter._invalidate_cache_prefix("credit", "branding")

        assert "config:credit:branding:org-1" not in _config_cache
        assert "config:credit:branding:org-2" not in _config_cache
        # Other config_type should be untouched
        assert "config:credit:scoring:org-1" in _config_cache

        # Cleanup
        _config_cache.pop("config:credit:scoring:org-1", None)

    def test_invalidate_nonexistent_key_does_not_raise(self):
        """Invalidating a key that doesn't exist should not raise."""
        ConfigWriter._invalidate_cache("nonexistent", "type", "org")  # type: ignore[arg-type]
