"""Tests for ProfileLoader — profile resolution and registry."""

from __future__ import annotations

import builtins
import importlib
import sys
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_engine.profile_loader import AnalysisProfile, ChapterConfig, ProfileLoader
from ai_engine.vertical_registry import (
    available_profiles,
    get_vertical_entry,
    import_vertical_module,
)
from app.core.config.schemas import ConfigResult, ConfigResultState


@pytest.fixture
def mock_config_service():
    """Mock ConfigService with async get() returning test data."""
    service = AsyncMock()

    # Return profile.yaml-like data for chapters
    service.get.side_effect = _mock_config_get
    return service


def _wrap(value: dict) -> ConfigResult:
    return ConfigResult(value=value, state=ConfigResultState.FOUND, source="mock")


async def _mock_config_get(vertical: str, config_type: str, org_id=None):
    if vertical == "private_credit" and config_type == "chapters":
        return _wrap({
            "name": "private_credit",
            "display_name": "Private Credit IC Memo",
            "version": 1,
            "chapters": [
                {"id": "ch01_exec", "title": "Executive Summary", "type": "ANALYTICAL",
                 "max_tokens": 4000, "chunk_budget": [20, 4000]},
                {"id": "ch02_macro", "title": "Macro & Market Context", "type": "ANALYTICAL",
                 "max_tokens": 3000, "chunk_budget": [10, 3000]},
            ],
            "tone_normalization": {"descriptive_max_chars": 10000},
            "recommendation_chapter": "ch13_recommendation",
            "evidence_law_template": "evidence_law.j2",
        })
    if vertical == "private_credit" and config_type == "calibration":
        return _wrap({"confidence_threshold": 0.7, "max_retries": 3})
    return _wrap({})


class TestProfileLoader:
    @pytest.mark.asyncio
    async def test_load_private_credit(self, mock_config_service):
        loader = ProfileLoader(mock_config_service)
        profile = await loader.load("private_credit")

        assert isinstance(profile, AnalysisProfile)
        assert profile.name == "private_credit"
        assert profile.display_name == "Private Credit IC Memo"
        assert profile.version == 1
        assert profile.vertical == "private_credit"
        assert len(profile.chapters) == 2
        assert profile.chapters[0].id == "ch01_exec"
        assert profile.chapters[0].max_tokens == 4000
        assert profile.recommendation_chapter == "ch13_recommendation"
        assert profile.config == {"confidence_threshold": 0.7, "max_retries": 3}

    @pytest.mark.asyncio
    async def test_load_with_org_id(self, mock_config_service):
        loader = ProfileLoader(mock_config_service)
        org_id = uuid4()
        await loader.load("private_credit", org_id=org_id)

        # Verify ConfigService was called with org_id
        calls = mock_config_service.get.call_args_list
        assert any(call.args == ("private_credit", "chapters", org_id) for call in calls)

    @pytest.mark.asyncio
    async def test_load_unknown_profile_raises(self, mock_config_service):
        loader = ProfileLoader(mock_config_service)
        with pytest.raises(ValueError, match="Unknown profile"):
            await loader.load("nonexistent_vertical")

    def test_chapter_config_frozen(self):
        ch = ChapterConfig(id="ch01", title="Test", type="ANALYTICAL")
        with pytest.raises(AttributeError):
            ch.id = "changed"  # type: ignore[misc]

    def test_analysis_profile_frozen(self):
        profile = AnalysisProfile(
            name="test", display_name="Test", version=1,
            vertical="test", chapters=(),
        )
        with pytest.raises(AttributeError):
            profile.name = "changed"  # type: ignore[misc]


class TestVerticalRegistry:
    def test_get_vertical_entry_private_credit(self):
        entry = get_vertical_entry("private_credit")
        assert entry.profile_name == "private_credit"
        assert entry.vertical_name == "private_credit"
        assert entry.module_path == "vertical_engines.credit"

    def test_get_engine_module_credit(self):
        mod = ProfileLoader.get_engine_module("private_credit")
        assert mod.__name__ == "vertical_engines.credit"

    def test_get_engine_module_unknown_raises(self):
        with pytest.raises(ValueError, match="No vertical engine registered"):
            ProfileLoader.get_engine_module("nonexistent")

    def test_available_profiles(self):
        profiles = ProfileLoader.available_profiles()
        assert "private_credit" in profiles
        assert "liquid_funds" in profiles
        assert profiles == sorted(profiles)  # sorted

    def test_registry_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="No vertical engine registered"):
            get_vertical_entry("nonexistent")

    def test_registry_imports_only_requested_vertical(self, monkeypatch):
        imported_paths: list[str] = []

        def _fake_import_module(module_path: str):
            imported_paths.append(module_path)
            return object()

        monkeypatch.setattr("ai_engine.vertical_registry.importlib.import_module", _fake_import_module)

        import_vertical_module("liquid_funds")

        assert imported_paths == ["vertical_engines.wealth"]

    def test_available_profiles_does_not_import_vertical_modules(self, monkeypatch):
        def _unexpected_import(_module_path: str):
            raise AssertionError("profile listing must not import vertical modules")

        monkeypatch.setattr("ai_engine.vertical_registry.importlib.import_module", _unexpected_import)

        assert available_profiles() == ["liquid_funds", "private_credit"]

    def test_ai_engine_import_does_not_load_credit_module(self, monkeypatch):
        original_import = builtins.__import__
        attempted_credit_imports: list[str] = []

        for module_name in list(sys.modules):
            if module_name == "ai_engine" or module_name.startswith("ai_engine."):
                sys.modules.pop(module_name, None)

        def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("vertical_engines.credit"):
                attempted_credit_imports.append(name)
                raise AssertionError("ai_engine import should not load credit modules")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", _guarded_import)

        module = importlib.import_module("ai_engine")

        assert module.__name__ == "ai_engine"
        assert attempted_credit_imports == []


class TestChapterConfigDefaults:
    def test_default_values(self):
        ch = ChapterConfig(id="ch01", title="Test", type="ANALYTICAL")
        assert ch.max_tokens == 4000
        assert ch.chunk_budget == (20, 4000)
