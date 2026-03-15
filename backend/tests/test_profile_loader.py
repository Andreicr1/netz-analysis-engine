"""Tests for ProfileLoader — profile resolution and registry."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_engine.profile_loader import AnalysisProfile, ChapterConfig, ProfileLoader


@pytest.fixture
def mock_config_service():
    """Mock ConfigService with async get() returning test data."""
    service = AsyncMock()

    # Return profile.yaml-like data for chapters
    service.get.side_effect = _mock_config_get
    return service


async def _mock_config_get(vertical: str, config_type: str, org_id=None):
    if vertical == "private_credit" and config_type == "chapters":
        return {
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
        }
    if vertical == "private_credit" and config_type == "calibration":
        return {"confidence_threshold": 0.7, "max_retries": 3}
    return {}


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


class TestChapterConfigDefaults:
    def test_default_values(self):
        ch = ChapterConfig(id="ch01", title="Test", type="ANALYTICAL")
        assert ch.max_tokens == 4000
        assert ch.chunk_budget == (20, 4000)
