"""Tests for PgNotifyListener — DSN conversion, notification handling."""

from __future__ import annotations

import json
from uuid import UUID

from app.core.config.config_service import ConfigService, _config_cache
from app.core.config.pg_notify import PgNotifyListener, _asyncpg_dsn


class TestAsyncpgDsn:
    def test_converts_sqlalchemy_url(self):
        """asyncpg DSN strips +asyncpg from scheme."""
        from unittest.mock import patch

        with patch("app.core.config.pg_notify.settings") as mock_settings:
            mock_settings.database_url = "postgresql+asyncpg://user:pass@host:5432/dbname"
            dsn = _asyncpg_dsn()
            assert dsn == "postgresql://user:pass@host:5432/dbname"
            assert "+asyncpg" not in dsn

    def test_preserves_path_and_query(self):
        from unittest.mock import patch

        with patch("app.core.config.pg_notify.settings") as mock_settings:
            mock_settings.database_url = "postgresql+asyncpg://u:p@h:5432/db?sslmode=require"
            dsn = _asyncpg_dsn()
            assert dsn.startswith("postgresql://")
            assert "sslmode=require" in dsn


class TestNotificationHandler:
    def test_on_notification_invalidates_cache(self):
        """pg_notify callback should invalidate specific cache key."""
        # Pre-populate cache
        _config_cache["config:credit:branding:abc-123"] = {"old": True}
        assert "config:credit:branding:abc-123" in _config_cache

        listener = PgNotifyListener()
        payload = json.dumps({
            "vertical": "credit",
            "config_type": "branding",
            "org_id": "abc-123",
        })
        listener._on_notification(None, 0, "netz_config_changed", payload)

        assert "config:credit:branding:abc-123" not in _config_cache

    def test_on_notification_global_invalidates_all_orgs(self):
        """Global config change (org_id=None) should invalidate all matching keys."""
        _config_cache["config:wealth:scoring:org-1"] = {"a": 1}
        _config_cache["config:wealth:scoring:org-2"] = {"b": 2}
        _config_cache["config:wealth:scoring:default"] = {"c": 3}

        listener = PgNotifyListener()
        payload = json.dumps({
            "vertical": "wealth",
            "config_type": "scoring",
            "org_id": None,
        })
        listener._on_notification(None, 0, "netz_config_changed", payload)

        assert "config:wealth:scoring:org-1" not in _config_cache
        assert "config:wealth:scoring:org-2" not in _config_cache
        assert "config:wealth:scoring:default" not in _config_cache

    def test_on_notification_invalid_payload_does_not_raise(self):
        """Malformed payload should log warning but not crash."""
        listener = PgNotifyListener()
        listener._on_notification(None, 0, "netz_config_changed", "invalid json{{{")
        # Should not raise

    def test_on_notification_missing_keys_does_not_raise(self):
        """Payload missing required keys should not crash."""
        listener = PgNotifyListener()
        listener._on_notification(None, 0, "netz_config_changed", '{"foo": "bar"}')
        # Should not raise


class TestConfigServiceInvalidate:
    def test_invalidate_specific_org(self):
        _config_cache["config:credit:branding:org-42"] = {"x": 1}
        ConfigService.invalidate("credit", "branding", UUID("00000000-0000-0000-0000-000000000042"))
        assert "config:credit:branding:00000000-0000-0000-0000-000000000042" not in _config_cache

    def test_invalidate_global_removes_all_for_config_type(self):
        _config_cache["config:wealth:calibration:org-a"] = {"a": 1}
        _config_cache["config:wealth:calibration:default"] = {"b": 2}

        ConfigService.invalidate("wealth", "calibration", None)

        assert "config:wealth:calibration:org-a" not in _config_cache
        assert "config:wealth:calibration:default" not in _config_cache
