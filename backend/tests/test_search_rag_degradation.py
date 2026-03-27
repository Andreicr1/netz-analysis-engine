"""Tests for SR-6: Search graceful degradation for RAG queries.

When pgvector search is unavailable, RAG queries should return empty results
with structured warnings instead of crashing.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

# ── PipelineKBAdapter graceful degradation ─────────────────────────────


class TestPipelineKBAdapterDegradation:
    """PipelineKBAdapter.search_live returns [] on search failure."""

    def test_returns_empty_on_connection_error(self):
        with patch(
            "ai_engine.extraction.embedding_service.generate_embeddings",
            side_effect=ConnectionError("pgvector unavailable"),
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
        with patch(
            "ai_engine.extraction.embedding_service.generate_embeddings",
            side_effect=TimeoutError("Request timed out"),
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
        with patch(
            "ai_engine.extraction.embedding_service.generate_embeddings",
            side_effect=ConnectionError("Service unavailable"),
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
        should still include a degradation warning.
        """
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
