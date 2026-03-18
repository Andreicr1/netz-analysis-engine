"""Tests for SR-6: Search index graceful degradation for RAG queries.

When Azure Search is unavailable, RAG queries should return empty results
with structured warnings instead of crashing.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

# ── PipelineKBAdapter graceful degradation ─────────────────────────────


class TestPipelineKBAdapterDegradation:
    """PipelineKBAdapter.search_live returns [] on search failure."""

    def test_returns_empty_on_connection_error(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("Azure Search unavailable")

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ), patch(
            "app.services.azure.search_client.resolve_chunks_index_name",
            return_value="dev-global-vector-chunks-v2",
        ):
            from app.domains.credit.global_agent.pipeline_kb_adapter import (
                PipelineKBAdapter,
            )

            result = PipelineKBAdapter.search_live(
                query="test query",
                organization_id=uuid.uuid4(),
                top=10,
            )

        assert result == []

    def test_returns_empty_on_timeout(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = TimeoutError("Request timed out")

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ), patch(
            "app.services.azure.search_client.resolve_chunks_index_name",
            return_value="dev-global-vector-chunks-v2",
        ):
            from app.domains.credit.global_agent.pipeline_kb_adapter import (
                PipelineKBAdapter,
            )

            result = PipelineKBAdapter.search_live(
                query="test query",
                organization_id=uuid.uuid4(),
                top=10,
            )

        assert result == []

    def test_logs_structured_warning_on_failure(self, caplog):
        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("Service unavailable")

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ), patch(
            "app.services.azure.search_client.resolve_chunks_index_name",
            return_value="dev-global-vector-chunks-v2",
        ):
            import logging

            from app.domains.credit.global_agent.pipeline_kb_adapter import (
                PipelineKBAdapter,
            )

            with caplog.at_level(logging.WARNING):
                PipelineKBAdapter.search_live(
                    query="test",
                    organization_id=uuid.uuid4(),
                    top=5,
                )

        assert any(
            "SEARCH_INDEX_UNAVAILABLE" in record.message
            for record in caplog.records
        )


# ── AzureComplianceKBAdapter graceful degradation ──────────────────────


class TestComplianceKBAdapterDegradation:
    """AzureComplianceKBAdapter.search_live returns [] on search failure."""

    def test_returns_empty_on_connection_error(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("Azure Search unavailable")

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ):
            from ai_engine.extraction.azure_kb_adapter import (
                AzureComplianceKBAdapter,
            )

            result = AzureComplianceKBAdapter.search_live(
                query="test query",
                domain="REGULATORY",
                organization_id=uuid.uuid4(),
                top=10,
            )

        assert result == []


# ── AzureSearchMetadataClient graceful degradation ─────────────────────


class TestMetadataClientDegradation:
    """AzureSearchMetadataClient.search returns [] on search failure."""

    def test_returns_empty_on_connection_error(self):
        mock_client = MagicMock()
        mock_client.search.side_effect = ConnectionError("Azure Search unavailable")

        with patch(
            "app.services.search_index.AzureSearchMetadataClient._client",
            return_value=mock_client,
        ):
            from app.services.search_index import AzureSearchMetadataClient

            client = AzureSearchMetadataClient(caller="test")
            result = client.search(
                q="test query",
                fund_id=uuid.uuid4(),
                organization_id=uuid.uuid4(),
                top=5,
            )

        assert result == []

    def test_logs_structured_warning_on_failure(self, caplog):
        mock_client = MagicMock()
        mock_client.search.side_effect = TimeoutError("Request timed out")

        with patch(
            "app.services.search_index.AzureSearchMetadataClient._client",
            return_value=mock_client,
        ):
            import logging

            from app.services.search_index import AzureSearchMetadataClient

            with caplog.at_level(logging.WARNING):
                client = AzureSearchMetadataClient(caller="test")
                client.search(
                    q="test query",
                    fund_id=uuid.uuid4(),
                    organization_id=uuid.uuid4(),
                    top=5,
                )

        assert any(
            "SEARCH_INDEX_UNAVAILABLE" in record.message
            for record in caplog.records
        )


# ── NetzGlobalAgent degradation propagation ────────────────────────────


class TestGlobalAgentDegradation:
    """NetzGlobalAgent.answer propagates search_degraded flag."""

    def test_search_degraded_flag_on_retrieval_failure(self):
        from app.domains.credit.global_agent.agent import NetzGlobalAgent

        agent = NetzGlobalAgent()

        # Mock _parallel_retrieve to simulate degraded state
        agent._parallel_retrieve = MagicMock(  # type: ignore[method-assign]
            return_value=([], ["PIPELINE"]),
        )

        result = agent.answer(
            question="What is the pipeline status?",
            organization_id=uuid.uuid4(),
        )

        assert result["search_degraded"] is True
        assert "PIPELINE" in result["search_degraded_domains"]
        assert "temporarily unavailable" in result["answer"].lower()

    def test_search_degraded_false_on_normal_empty(self):
        from app.domains.credit.global_agent.agent import NetzGlobalAgent

        agent = NetzGlobalAgent()

        agent._parallel_retrieve = MagicMock(  # type: ignore[method-assign]
            return_value=([], []),
        )

        result = agent.answer(
            question="What is the pipeline status?",
            organization_id=uuid.uuid4(),
        )

        assert result["search_degraded"] is False
        assert result["search_degraded_domains"] == []
        assert "insufficient evidence" in result["answer"].lower()

    def test_partial_degradation_with_results(self):
        """When some domains fail but others return results, the answer
        should still include a degradation warning."""
        from ai_engine.extraction.kb_schema import ComplianceChunk
        from app.domains.credit.global_agent.agent import NetzGlobalAgent

        agent = NetzGlobalAgent()

        mock_chunk = ComplianceChunk(
            chunk_id="test-1",
            doc_id="doc-1",
            domain="PIPELINE",
            doc_type="OTHER",
            source_blob="test.pdf",
            chunk_text="Some evidence text here.",
            obligation_candidate=False,
            extraction_confidence=0.9,
            search_score=0.9,
        )

        agent._parallel_retrieve = MagicMock(  # type: ignore[method-assign]
            return_value=([mock_chunk], ["REGULATORY"]),
        )

        # Mock the LLM call and prompt rendering so we don't need
        # OpenAI or prompt templates
        agent._call_llm = MagicMock(return_value="Here is the analysis.")  # type: ignore[method-assign]

        with patch("ai_engine.prompts.prompt_registry.render", return_value="mocked prompt"):
            result = agent.answer(
                question="What is the pipeline status?",
                organization_id=uuid.uuid4(),
            )

        assert result["search_degraded"] is True
        assert "REGULATORY" in result["search_degraded_domains"]
        assert result["chunks_used"] == 1
        # The answer should contain the LLM response plus a degradation note
        assert "partially unavailable" in result["answer"].lower()
