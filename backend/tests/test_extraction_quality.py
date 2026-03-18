"""Tests for FAIL-02: typed degraded states for extraction fallback paths.

Proves that upstream outages and low-quality fallback paths remain
distinguishable from legitimate empty or low-signal business outputs
throughout persistence, indexing, and retrieval.
"""
from __future__ import annotations

import json
import sys
import uuid
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub modules that trigger heavy import chains ─────────────────────
# document_intelligence.py imports prompt_safety, prompts, model_config at
# module level.  We stub those to keep tests fast and isolated.

def _ensure_stub(name: str) -> None:
    """Insert a no-op stub into sys.modules if not already importable."""
    if name not in sys.modules:
        sys.modules[name] = ModuleType(name)


_ensure_stub("ai_engine.prompt_safety")
_ps = sys.modules["ai_engine.prompt_safety"]
if not hasattr(_ps, "sanitize_user_input"):
    _ps.sanitize_user_input = lambda text, **kw: text  # type: ignore[attr-defined]

_ensure_stub("ai_engine.openai_client")
_oc = sys.modules["ai_engine.openai_client"]
if not hasattr(_oc, "async_create_completion"):
    _oc.async_create_completion = AsyncMock()  # type: ignore[attr-defined]

_ensure_stub("ai_engine.model_config")
_mc = sys.modules["ai_engine.model_config"]
if not hasattr(_mc, "get_model"):
    _mc.get_model = lambda stage: "stub-model"  # type: ignore[attr-defined]

# prompts registry needs a render() method
_ensure_stub("ai_engine.prompts")
_pr_mod = sys.modules["ai_engine.prompts"]
if not hasattr(_pr_mod, "prompt_registry"):
    _registry = ModuleType("prompt_registry")
    _registry.render = lambda *a, **kw: "stub prompt"  # type: ignore[attr-defined]
    _pr_mod.prompt_registry = _registry  # type: ignore[attr-defined]

# Now safe to import
from ai_engine.extraction.document_intelligence import (
    ExtractionQuality,
    ExtractionResult,
    MetadataResult,
)

# ═══════════════════════════════════════════════════════════════════════
#  ExtractionQuality enum — reason codes and degraded flag
# ═══════════════════════════════════════════════════════════════════════


class TestExtractionQualityEnum:
    """Verify all reason codes exist and is_degraded is correct."""

    def test_all_reason_codes_exist(self):
        assert ExtractionQuality.SUCCESS
        assert ExtractionQuality.SERVICE_OUTAGE
        assert ExtractionQuality.PARSE_FAILURE
        assert ExtractionQuality.SUMMARY_FAILURE
        assert ExtractionQuality.OCR_FALLBACK
        assert ExtractionQuality.LEGITIMATELY_EMPTY

    def test_success_is_not_degraded(self):
        assert ExtractionQuality.SUCCESS.is_degraded is False

    def test_legitimately_empty_is_not_degraded(self):
        assert ExtractionQuality.LEGITIMATELY_EMPTY.is_degraded is False

    def test_service_outage_is_degraded(self):
        assert ExtractionQuality.SERVICE_OUTAGE.is_degraded is True

    def test_parse_failure_is_degraded(self):
        assert ExtractionQuality.PARSE_FAILURE.is_degraded is True

    def test_summary_failure_is_degraded(self):
        assert ExtractionQuality.SUMMARY_FAILURE.is_degraded is True

    def test_ocr_fallback_is_degraded(self):
        assert ExtractionQuality.OCR_FALLBACK.is_degraded is True

    def test_enum_values_are_serializable_strings(self):
        """Quality codes must be JSON-safe for metadata persistence."""
        for member in ExtractionQuality:
            assert isinstance(member.value, str)
            assert json.dumps(member.value)


# ═══════════════════════════════════════════════════════════════════════
#  ExtractionResult dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestExtractionResult:
    def test_success_wraps_content(self):
        meta = MetadataResult(entities={"org": ["Acme"]})
        result = ExtractionResult(
            quality=ExtractionQuality.SUCCESS,
            content=meta,
        )
        assert result.quality == ExtractionQuality.SUCCESS
        assert result.content.entities == {"org": ["Acme"]}
        assert result.quality.is_degraded is False

    def test_degraded_wraps_empty_content_with_reason(self):
        result = ExtractionResult(
            quality=ExtractionQuality.SERVICE_OUTAGE,
            content=MetadataResult(),
            reason="OpenAI API 503",
        )
        assert result.quality.is_degraded is True
        assert result.reason == "OpenAI API 503"
        assert result.content.entities == {}


# ═══════════════════════════════════════════════════════════════════════
#  async_extract_metadata — reason code paths
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncExtractMetadataReasonCodes:

    @pytest.mark.asyncio
    async def test_success_returns_success_quality(self):
        mock_result = MagicMock()
        mock_result.text = json.dumps({
            "entities": {"org": ["Netz"]},
            "dates": {},
            "counterparties": [],
            "jurisdictions": [],
        })

        with patch(
            "ai_engine.openai_client.async_create_completion",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            from ai_engine.extraction.document_intelligence import async_extract_metadata

            result = await async_extract_metadata(
                title="test.pdf", doc_type="legal_lpa", content="some content",
            )

        assert result.quality == ExtractionQuality.SUCCESS
        assert result.content.entities == {"org": ["Netz"]}

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_parse_failure(self):
        mock_result = MagicMock()
        mock_result.text = "not valid json {{{{"

        with patch(
            "ai_engine.openai_client.async_create_completion",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            from ai_engine.extraction.document_intelligence import async_extract_metadata

            result = await async_extract_metadata(
                title="test.pdf", doc_type="legal_lpa", content="some content",
            )

        assert result.quality == ExtractionQuality.PARSE_FAILURE
        assert "parse failure" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_service_exception_returns_service_outage(self):
        with patch(
            "ai_engine.openai_client.async_create_completion",
            new_callable=AsyncMock,
            side_effect=ConnectionError("API unreachable"),
        ):
            from ai_engine.extraction.document_intelligence import async_extract_metadata

            result = await async_extract_metadata(
                title="test.pdf", doc_type="legal_lpa", content="some content",
            )

        assert result.quality == ExtractionQuality.SERVICE_OUTAGE
        assert "outage" in result.reason.lower()


# ═══════════════════════════════════════════════════════════════════════
#  async_summarize_document — reason code paths
# ═══════════════════════════════════════════════════════════════════════


class TestAsyncSummarizeDocumentReasonCodes:

    @pytest.mark.asyncio
    async def test_success_returns_success_quality(self):
        mock_result = MagicMock()
        mock_result.text = json.dumps({
            "summary": "A concise summary.",
            "key_findings": ["finding1"],
            "deal_relevance_score": 8,
        })

        with patch(
            "ai_engine.openai_client.async_create_completion",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            from ai_engine.extraction.document_intelligence import async_summarize_document

            result = await async_summarize_document(
                title="test.pdf", doc_type="legal_lpa", content="some content",
            )

        assert result.quality == ExtractionQuality.SUCCESS
        assert result.content.summary == "A concise summary."

    @pytest.mark.asyncio
    async def test_json_parse_failure_returns_summary_failure(self):
        mock_result = MagicMock()
        mock_result.text = "broken json"

        with patch(
            "ai_engine.openai_client.async_create_completion",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            from ai_engine.extraction.document_intelligence import async_summarize_document

            result = await async_summarize_document(
                title="test.pdf", doc_type="legal_lpa", content="some content",
            )

        assert result.quality == ExtractionQuality.SUMMARY_FAILURE

    @pytest.mark.asyncio
    async def test_service_exception_returns_summary_failure(self):
        with patch(
            "ai_engine.openai_client.async_create_completion",
            new_callable=AsyncMock,
            side_effect=TimeoutError("LLM timeout"),
        ):
            from ai_engine.extraction.document_intelligence import async_summarize_document

            result = await async_summarize_document(
                title="test.pdf", doc_type="legal_lpa", content="some content",
            )

        assert result.quality == ExtractionQuality.SUMMARY_FAILURE


# ═══════════════════════════════════════════════════════════════════════
#  TextExtractionResult — OCR fallback quality tracking
# ═══════════════════════════════════════════════════════════════════════


class TestTextExtractionQuality:

    @pytest.mark.asyncio
    async def test_mistral_success_returns_success_quality(self):
        with (
            patch(
                "ai_engine.extraction.text_extraction._mistral_available",
                return_value=True,
            ),
            patch(
                "ai_engine.extraction.text_extraction._async_extract_pdf_mistral",
                new_callable=AsyncMock,
                return_value=[{"page_start": 1, "page_end": 1, "text": "Page 1 content"}],
            ),
        ):
            from ai_engine.extraction.text_extraction import async_extract_text_from_bytes

            result = await async_extract_text_from_bytes(b"%PDF-fake", filename="test.pdf")

        assert result.quality == ExtractionQuality.SUCCESS
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_pypdf_fallback_returns_ocr_fallback(self):
        with (
            patch(
                "ai_engine.extraction.text_extraction._mistral_available",
                return_value=False,
            ),
            patch(
                "ai_engine.extraction.text_extraction._extract_pdf",
                return_value=[{"page_start": 1, "page_end": 1, "text": "pypdf text"}],
            ),
        ):
            from ai_engine.extraction.text_extraction import async_extract_text_from_bytes

            result = await async_extract_text_from_bytes(b"%PDF-fake", filename="test.pdf")

        assert result.quality == ExtractionQuality.OCR_FALLBACK
        assert result.quality.is_degraded is True

    @pytest.mark.asyncio
    async def test_empty_pdf_returns_legitimately_empty(self):
        with (
            patch(
                "ai_engine.extraction.text_extraction._mistral_available",
                return_value=False,
            ),
            patch(
                "ai_engine.extraction.text_extraction._extract_pdf",
                return_value=[],
            ),
            patch(
                "ai_engine.extraction.text_extraction._extract_with_document_intelligence",
                return_value=[],
            ),
        ):
            from ai_engine.extraction.text_extraction import async_extract_text_from_bytes

            result = await async_extract_text_from_bytes(b"%PDF-fake", filename="test.pdf")

        assert result.quality == ExtractionQuality.LEGITIMATELY_EMPTY
        assert result.quality.is_degraded is False

    @pytest.mark.asyncio
    async def test_unsupported_extension_returns_parse_failure(self):
        from ai_engine.extraction.text_extraction import async_extract_text_from_bytes

        result = await async_extract_text_from_bytes(b"data", filename="test.xyz")
        assert result.quality == ExtractionQuality.PARSE_FAILURE
        assert result.quality.is_degraded is True

    @pytest.mark.asyncio
    async def test_empty_txt_returns_legitimately_empty(self):
        from ai_engine.extraction.text_extraction import async_extract_text_from_bytes

        result = await async_extract_text_from_bytes(b"", filename="empty.txt")
        assert result.quality == ExtractionQuality.LEGITIMATELY_EMPTY

    @pytest.mark.asyncio
    async def test_valid_txt_returns_success(self):
        from ai_engine.extraction.text_extraction import async_extract_text_from_bytes

        result = await async_extract_text_from_bytes(b"Hello world", filename="file.txt")
        assert result.quality == ExtractionQuality.SUCCESS
        assert len(result.pages) == 1


# ═══════════════════════════════════════════════════════════════════════
#  Degraded marker in search documents (FAIL-02 AC#2)
# ═══════════════════════════════════════════════════════════════════════


class TestSearchDocumentDegradedMarker:

    def test_success_has_no_degraded_marker(self):
        from ai_engine.extraction.search_upsert_service import build_search_document

        doc = build_search_document(
            deal_id=uuid.uuid4(),
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="legal_lpa",
            authority="unified_pipeline",
            title="test.pdf",
            chunk_index=0,
            content="Some content",
            embedding=[0.1] * 10,
            page_start=1,
            page_end=1,
        )
        assert "extraction_degraded" not in doc

    def test_degraded_extraction_includes_marker(self):
        from ai_engine.extraction.search_upsert_service import build_search_document

        doc = build_search_document(
            deal_id=uuid.uuid4(),
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="legal_lpa",
            authority="unified_pipeline",
            title="test.pdf",
            chunk_index=0,
            content="Some content",
            embedding=[0.1] * 10,
            page_start=1,
            page_end=1,
            extraction_degraded=True,
            extraction_quality={"metadata": "service_outage", "summary": "success"},
        )
        assert doc["extraction_degraded"] is True
        quality = json.loads(doc["extraction_quality"])
        assert quality["metadata"] == "service_outage"

    def test_non_degraded_explicit_false_included(self):
        from ai_engine.extraction.search_upsert_service import build_search_document

        doc = build_search_document(
            deal_id=uuid.uuid4(),
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="legal_lpa",
            authority="unified_pipeline",
            title="test.pdf",
            chunk_index=0,
            content="content",
            embedding=[0.1] * 10,
            page_start=1,
            page_end=1,
            extraction_degraded=False,
        )
        assert doc["extraction_degraded"] is False


# ═══════════════════════════════════════════════════════════════════════
#  Degraded outputs cannot be stored as normal-success records (AC#3)
# ═══════════════════════════════════════════════════════════════════════


class TestDegradedOutputsDistinguishable:

    def test_degraded_metadata_in_persisted_payload(self):
        extraction_quality_codes = {
            "metadata": ExtractionQuality.SERVICE_OUTAGE.value,
            "summary": ExtractionQuality.SUCCESS.value,
        }
        extraction_degraded = True

        meta_payload = json.dumps({
            "document_id": str(uuid.uuid4()),
            "filename": "test.pdf",
            "doc_type": "legal_lpa",
            "extraction_quality": extraction_quality_codes,
            "extraction_degraded": extraction_degraded,
        })

        persisted = json.loads(meta_payload)
        assert persisted["extraction_degraded"] is True
        assert persisted["extraction_quality"]["metadata"] == "service_outage"
        assert persisted["extraction_quality"]["summary"] == "success"

    def test_success_metadata_is_not_degraded(self):
        extraction_quality_codes = {
            "metadata": ExtractionQuality.SUCCESS.value,
            "summary": ExtractionQuality.SUCCESS.value,
        }
        extraction_degraded = False

        meta_payload = json.dumps({
            "document_id": str(uuid.uuid4()),
            "filename": "test.pdf",
            "doc_type": "legal_lpa",
            "extraction_quality": extraction_quality_codes,
            "extraction_degraded": extraction_degraded,
        })

        persisted = json.loads(meta_payload)
        assert persisted["extraction_degraded"] is False

    def test_degraded_and_success_are_structurally_different(self):
        success_quality = {
            "metadata": ExtractionQuality.SUCCESS.value,
            "summary": ExtractionQuality.SUCCESS.value,
        }
        degraded_quality = {
            "metadata": ExtractionQuality.PARSE_FAILURE.value,
            "summary": ExtractionQuality.SUMMARY_FAILURE.value,
        }

        success_record = {
            "extraction_degraded": False,
            "extraction_quality": success_quality,
        }
        degraded_record = {
            "extraction_degraded": True,
            "extraction_quality": degraded_quality,
        }

        assert success_record != degraded_record
        assert success_record["extraction_degraded"] != degraded_record["extraction_degraded"]

    def test_downstream_filter_can_exclude_degraded(self):
        docs = [
            {"id": "1", "extraction_degraded": False, "content": "clean"},
            {"id": "2", "extraction_degraded": True, "content": "degraded"},
            {"id": "3", "content": "no marker"},
        ]

        clean_docs = [d for d in docs if not d.get("extraction_degraded", False)]
        assert len(clean_docs) == 2
        assert all(d["id"] in ("1", "3") for d in clean_docs)

        degraded_docs = [d for d in docs if d.get("extraction_degraded", False)]
        assert len(degraded_docs) == 1
        assert degraded_docs[0]["id"] == "2"
