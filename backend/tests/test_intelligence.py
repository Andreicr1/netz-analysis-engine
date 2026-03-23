"""Tests for vertical_engines.credit.pipeline.intelligence — pipeline intelligence generation."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from vertical_engines.credit.pipeline.intelligence import _call_gpt_json
from vertical_engines.credit.pipeline.models import (
    DOC_TYPE_MAP,
    RISK_BAND_ORDER,
    RISK_ORDER,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_READY,
)


# ── Pipeline status constants ────────────────────────────────────


class TestPipelineConstants:
    def test_status_values(self):
        assert STATUS_PENDING == "PENDING"
        assert STATUS_PROCESSING == "PROCESSING"
        assert STATUS_READY == "READY"
        assert STATUS_FAILED == "FAILED"

    def test_risk_order(self):
        assert RISK_ORDER["LOW"] < RISK_ORDER["MEDIUM"] < RISK_ORDER["HIGH"]

    def test_risk_band_order(self):
        assert RISK_BAND_ORDER["LOW"] < RISK_BAND_ORDER["HIGH"]
        assert RISK_BAND_ORDER["MODERATE"] < RISK_BAND_ORDER["HIGH"]

    def test_doc_type_map_has_confidence(self):
        for doc_type, (label, confidence) in DOC_TYPE_MAP.items():
            assert isinstance(label, str)
            assert isinstance(confidence, int)
            assert 0 <= confidence <= 100


# ── _call_gpt_json ──────────────────────────────────────────────


class TestCallGptJson:
    def _mock_completion(self, text: str, model: str = "gpt-4.1-mini"):
        result = MagicMock()
        result.text = text
        result.model = model
        return result

    @patch("vertical_engines.credit.pipeline.intelligence.create_completion")
    def test_basic_json_response(self, mock_completion):
        mock_completion.return_value = self._mock_completion(
            '{"deal_overview": "Test deal", "key_risks": []}'
        )
        result = _call_gpt_json("system", "user", model="gpt-4.1-mini")
        assert result["deal_overview"] == "Test deal"
        assert "_meta" in result
        assert result["_meta"]["engine"] == "pipeline_engine"

    @patch("vertical_engines.credit.pipeline.intelligence.create_completion")
    def test_strips_markdown_fences(self, mock_completion):
        mock_completion.return_value = self._mock_completion(
            '```json\n{"value": 42}\n```'
        )
        result = _call_gpt_json("system", "user", model="gpt-4.1-mini")
        assert result["value"] == 42

    @patch("vertical_engines.credit.pipeline.intelligence.create_completion")
    def test_meta_defaults_populated(self, mock_completion):
        mock_completion.return_value = self._mock_completion('{"data": true}')
        result = _call_gpt_json("system", "user", model="gpt-4.1-mini")
        meta = result["_meta"]
        assert meta["engine"] == "pipeline_engine"
        assert meta["call"] == "structured"
        assert "generatedAt" in meta

    @patch("vertical_engines.credit.pipeline.intelligence.create_completion")
    def test_custom_call_label(self, mock_completion):
        mock_completion.return_value = self._mock_completion('{"data": true}')
        result = _call_gpt_json(
            "system", "user", model="gpt-4.1-mini", call_label="memo"
        )
        assert result["_meta"]["call"] == "memo"

    @patch("vertical_engines.credit.pipeline.intelligence.create_completion")
    def test_existing_meta_preserved(self, mock_completion):
        mock_completion.return_value = self._mock_completion(
            '{"data": true, "_meta": {"custom_field": "keep"}}'
        )
        result = _call_gpt_json("system", "user", model="gpt-4.1-mini")
        assert result["_meta"]["custom_field"] == "keep"
        assert result["_meta"]["engine"] == "pipeline_engine"

    @patch("vertical_engines.credit.pipeline.intelligence.create_completion")
    def test_invalid_json_raises(self, mock_completion):
        mock_completion.return_value = self._mock_completion("not json at all")
        with pytest.raises(json.JSONDecodeError):
            _call_gpt_json("system", "user", model="gpt-4.1-mini")

    @patch("vertical_engines.credit.pipeline.intelligence.create_completion")
    def test_max_tokens_passed(self, mock_completion):
        mock_completion.return_value = self._mock_completion('{"ok": true}')
        _call_gpt_json(
            "system", "user", model="gpt-4.1-mini", max_tokens=5000
        )
        call_kwargs = mock_completion.call_args
        assert call_kwargs.kwargs.get("max_tokens") == 5000 or \
               call_kwargs[1].get("max_tokens") == 5000
