"""Tests for ConfigWriter — guardrails, optimistic locking, cache invalidation."""

from __future__ import annotations

from uuid import UUID

from app.core.config.config_service import ConfigService
from app.core.config.config_writer import GuardrailViolation, StaleVersionError


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
    """Cache invalidation is handled by ConfigService.invalidate(), called by
    PgNotifyListener after the DB transaction commits.  ConfigWriter no longer
    touches the cache directly — it only emits pg_notify.
    """

    def test_invalidate_specific_cache_key(self):
        """ConfigService.invalidate() removes the correct key."""
        from app.core.config.config_service import _config_cache

        org = UUID("00000000-0000-0000-0000-000000000123")
        cache_key = f"config:credit:branding:{org}"

        _config_cache[cache_key] = {"test": True}
        assert cache_key in _config_cache

        ConfigService.invalidate("credit", "branding", org)
        assert cache_key not in _config_cache

    def test_invalidate_prefix_clears_all_orgs(self):
        """ConfigService.invalidate(org_id=None) removes all orgs for that config."""
        from app.core.config.config_service import _config_cache

        org1 = UUID("00000000-0000-0000-0000-000000000001")
        org2 = UUID("00000000-0000-0000-0000-000000000002")

        _config_cache[f"config:credit:branding:{org1}"] = {"a": 1}
        _config_cache[f"config:credit:branding:{org2}"] = {"b": 2}
        _config_cache[f"config:credit:scoring:{org1}"] = {"c": 3}

        ConfigService.invalidate("credit", "branding", org_id=None)

        assert f"config:credit:branding:{org1}" not in _config_cache
        assert f"config:credit:branding:{org2}" not in _config_cache
        # Other config_type should be untouched
        assert f"config:credit:scoring:{org1}" in _config_cache

        # Cleanup
        _config_cache.pop(f"config:credit:scoring:{org1}", None)

    def test_invalidate_nonexistent_key_does_not_raise(self):
        """Invalidating a key that doesn't exist should not raise."""
        org = UUID("00000000-0000-0000-0000-ffffffffffff")
        ConfigService.invalidate("nonexistent", "type", org)
