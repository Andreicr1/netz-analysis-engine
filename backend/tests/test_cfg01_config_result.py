"""Tests for CFG-01 — required vs optional config miss semantics.

Acceptance criteria:
1. Required config miss (DB + YAML) raises ConfigMissError.
2. Optional config miss returns ConfigResult with MISSING_OPTIONAL state + warning.
3. No required-config caller receives a plain {} indistinguishable from valid config.
4. Valid empty config (found in DB) returns FOUND state.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config.config_service import ConfigService
from app.core.config.registry import ConfigDomain, ConfigRegistry
from app.core.config.schemas import ConfigResult, ConfigResultState
from app.shared.exceptions import ConfigMissError

# ── ConfigResult dataclass tests ─────────────────────────────────────────────


class TestConfigResult:
    def test_found_state(self):
        r = ConfigResult(value={"key": "val"}, state=ConfigResultState.FOUND, source="db_default")
        assert r.is_found is True
        assert r.is_missing is False
        assert r.value == {"key": "val"}
        assert r.source == "db_default"

    def test_missing_optional_state(self):
        r = ConfigResult(value={}, state=ConfigResultState.MISSING_OPTIONAL, source="miss")
        assert r.is_found is False
        assert r.is_missing is True
        assert r.value == {}

    def test_missing_required_state(self):
        r = ConfigResult(value={}, state=ConfigResultState.MISSING_REQUIRED, source="miss")
        assert r.is_found is False
        assert r.is_missing is True

    def test_frozen(self):
        r = ConfigResult(value={"a": 1})
        with pytest.raises(AttributeError):
            r.value = {}  # type: ignore[misc]

    def test_default_values(self):
        r = ConfigResult()
        assert r.value == {}
        assert r.state is ConfigResultState.FOUND
        assert r.source == "unknown"


# ── ConfigMissError tests ────────────────────────────────────────────────────


class TestConfigMissError:
    def test_message_includes_vertical_and_type(self):
        err = ConfigMissError("private_credit", "chapters")
        assert "private_credit" in str(err)
        assert "chapters" in str(err)
        assert "Required config missing" in str(err)

    def test_has_status_500(self):
        err = ConfigMissError("liquid_funds", "calibration")
        assert err.status_code == 500

    def test_attrs_preserved(self):
        err = ConfigMissError("liquid_funds", "calibration")
        assert err.vertical == "liquid_funds"
        assert err.config_type == "calibration"


# ── Registry required/optional field tests ───────────────────────────────────


class TestRegistryRequiredField:
    def test_required_defaults_to_true(self):
        domain = ConfigDomain(
            vertical="test",
            config_type="test",
            ownership="config_service",
            client_visible=False,
            description="test",
        )
        assert domain.required is True

    def test_optional_field(self):
        domain = ConfigDomain(
            vertical="test",
            config_type="test",
            ownership="config_service",
            client_visible=False,
            description="test",
            required=False,
        )
        assert domain.required is False

    def test_screening_layers_are_optional(self):
        for layer in ("screening_layer1", "screening_layer2", "screening_layer3"):
            domain = ConfigRegistry.get("liquid_funds", layer)
            assert domain is not None, f"{layer} not registered"
            assert domain.required is False, f"{layer} should be optional"

    def test_branding_is_optional(self):
        domain = ConfigRegistry.get("_admin", "branding")
        assert domain is not None
        assert domain.required is False

    def test_calibration_is_required(self):
        domain = ConfigRegistry.get("liquid_funds", "calibration")
        assert domain is not None
        assert domain.required is True

    def test_chapters_is_required(self):
        domain = ConfigRegistry.get("private_credit", "chapters")
        assert domain is not None
        assert domain.required is True

    def test_scoring_is_required(self):
        domain = ConfigRegistry.get("liquid_funds", "scoring")
        assert domain is not None
        assert domain.required is True


# ── ConfigService._handle_miss tests ─────────────────────────────────────────


class TestHandleMiss:
    def test_required_miss_raises(self):
        """Required config miss raises ConfigMissError (AC#1)."""
        with pytest.raises(ConfigMissError) as exc_info:
            ConfigService._handle_miss("liquid_funds", "calibration", "cache:key")
        assert exc_info.value.vertical == "liquid_funds"
        assert exc_info.value.config_type == "calibration"

    def test_optional_miss_returns_typed_result(self):
        """Optional config miss returns ConfigResult with MISSING_OPTIONAL state (AC#2)."""
        result = ConfigService._handle_miss("liquid_funds", "screening_layer1", "cache:key")
        assert isinstance(result, ConfigResult)
        assert result.state is ConfigResultState.MISSING_OPTIONAL
        assert result.value == {}
        assert result.source == "miss"

    def test_required_miss_emits_error_log(self, caplog):
        """Required miss emits structured ERROR telemetry."""
        with caplog.at_level(logging.ERROR, logger="app.core.config.config_service"):
            with pytest.raises(ConfigMissError):
                ConfigService._handle_miss("liquid_funds", "calibration", "cache:key")
        assert "Required config miss" in caplog.text

    def test_optional_miss_emits_warning_log(self, caplog):
        """Optional miss emits structured WARNING telemetry (AC#2)."""
        with caplog.at_level(logging.WARNING, logger="app.core.config.config_service"):
            ConfigService._handle_miss("liquid_funds", "screening_layer1", "cache:key")
        assert "Optional config miss" in caplog.text

    def test_unregistered_domain_treated_as_required(self):
        """Unregistered domain defaults to required (fail-safe)."""
        with pytest.raises(ConfigMissError):
            ConfigService._handle_miss("unknown_vertical", "unknown_type", "cache:key")


# ── ConfigService.get integration tests (mocked DB) ─────────────────────────


class TestConfigServiceGetIntegration:
    """Test get() returns ConfigResult, not plain dict."""

    @pytest.fixture
    def mock_db(self):
        """Mock AsyncSession that returns None for all queries (total miss)."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        return db

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear config cache before each test."""
        from app.core.config.config_service import _config_cache
        _config_cache.clear()
        yield
        _config_cache.clear()

    @pytest.mark.asyncio
    async def test_required_miss_raises_config_miss_error(self, mock_db):
        """Required config total miss raises ConfigMissError (AC#1, AC#3)."""
        svc = ConfigService(mock_db)
        # Patch YAML fallback to also return None (simulates no YAML file)
        with patch.object(ConfigService, "_yaml_fallback", return_value=None):
            with pytest.raises(ConfigMissError):
                await svc.get("liquid_funds", "calibration")

    @pytest.mark.asyncio
    async def test_optional_miss_returns_config_result(self, mock_db):
        """Optional config total miss returns ConfigResult.MISSING_OPTIONAL (AC#2)."""
        svc = ConfigService(mock_db)
        result = await svc.get("liquid_funds", "screening_layer1")
        assert isinstance(result, ConfigResult)
        assert result.state is ConfigResultState.MISSING_OPTIONAL
        assert result.value == {}

    @pytest.mark.asyncio
    async def test_found_config_returns_config_result(self):
        """Found config returns ConfigResult.FOUND with value (AC#3)."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {"leverage_limits": {"max": 5.0}}
        db.execute.return_value = mock_result

        svc = ConfigService(db)
        result = await svc.get("liquid_funds", "calibration")
        assert isinstance(result, ConfigResult)
        assert result.state is ConfigResultState.FOUND
        assert result.value == {"leverage_limits": {"max": 5.0}}
        assert "db_default" in result.source

    @pytest.mark.asyncio
    async def test_valid_empty_config_is_found(self):
        """A valid empty dict in DB returns FOUND, not MISSING (AC#3)."""
        db = AsyncMock()
        mock_result = MagicMock()
        # DB returns {} — this is valid config, not a miss
        mock_result.scalar_one_or_none.return_value = {}
        db.execute.return_value = mock_result

        svc = ConfigService(db)
        # Use an optional type since required would raise on miss
        result = await svc.get("liquid_funds", "calibration")
        assert isinstance(result, ConfigResult)
        # Empty dict from DB is FOUND — distinguishable from miss
        assert result.state is ConfigResultState.FOUND
        assert result.value == {}

    @pytest.mark.asyncio
    async def test_cache_stores_config_result(self):
        """Cache stores ConfigResult, not plain dict."""
        from app.core.config.config_service import _config_cache

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = {"key": "val"}
        db.execute.return_value = mock_result

        svc = ConfigService(db)
        result = await svc.get("liquid_funds", "calibration")

        # Verify cache has ConfigResult
        cache_key = "config:liquid_funds:calibration:default"
        cached = _config_cache.get(cache_key)
        assert isinstance(cached, ConfigResult)
        assert cached.value == {"key": "val"}
        assert cached.state is ConfigResultState.FOUND

    @pytest.mark.asyncio
    async def test_optional_miss_cached(self):
        """Optional miss result is cached so subsequent calls don't re-query."""

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        svc = ConfigService(db)
        r1 = await svc.get("liquid_funds", "screening_layer1")
        assert r1.state is ConfigResultState.MISSING_OPTIONAL

        # Second call should hit cache (no additional DB query)
        call_count_before = db.execute.call_count
        r2 = await svc.get("liquid_funds", "screening_layer1")
        assert db.execute.call_count == call_count_before
        assert r2.state is ConfigResultState.MISSING_OPTIONAL
