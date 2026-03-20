"""Tests for Phase 5 — signal-based search tier expansion."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ai_engine.extraction.pgvector_search_service import RerankedResult
from ai_engine.extraction.retrieval_signal import RetrievalSignal

# ── Helpers ──────────────────────────────────────────────────────────

_DEAL_ID = "00000000-0000-0000-0000-000000000001"
_FUND_ID = "00000000-0000-0000-0000-000000000002"
_ORG_ID = "00000000-0000-0000-0000-000000000003"


def _make_chunk(
    chunk_id: str = "c1",
    chunk_index: int = 0,
    score: float = 0.8,
    reranker_score: float = 5.0,
    deal_id: str = _DEAL_ID,
) -> dict:
    return {
        "id": chunk_id,
        "title": "doc.pdf",
        "doc_type": "fund_doc",
        "page_start": 1,
        "page_end": 2,
        "chunk_index": chunk_index,
        "content": "content",
        "score": score,
        "reranker_score": reranker_score,
        "fund_id": _FUND_ID,
        "deal_id": deal_id,
        "section_type": None,
        "governance_critical": False,
        "breadcrumb": None,
    }


def _make_high_confidence_chunks(n: int = 6) -> list[dict]:
    """Chunks with large delta between top1 and top2 → HIGH confidence."""
    chunks = [_make_chunk(chunk_id="c0", chunk_index=0, reranker_score=10.0, score=0.95)]
    for i in range(1, n):
        chunks.append(
            _make_chunk(
                chunk_id=f"c{i}",
                chunk_index=i,
                reranker_score=5.0 - i * 0.1,
                score=0.8 - i * 0.01,
            )
        )
    return chunks


def _make_low_confidence_chunks(n: int = 2) -> list[dict]:
    """Too few results → LOW confidence."""
    return [
        _make_chunk(
            chunk_id=f"c{i}",
            chunk_index=i,
            reranker_score=3.0 - i * 0.1,
            score=0.7 - i * 0.01,
        )
        for i in range(n)
    ]


def _make_moderate_confidence_chunks(n: int = 5) -> list[dict]:
    """Delta between MODERATE thresholds → MODERATE confidence."""
    chunks = [_make_chunk(chunk_id="c0", chunk_index=0, reranker_score=6.0)]
    for i in range(1, n):
        chunks.append(
            _make_chunk(
                chunk_id=f"c{i}",
                chunk_index=i,
                reranker_score=5.0 - i * 0.05,
            )
        )
    return chunks


def _make_ambiguous_chunks(n: int = 6) -> list[dict]:
    """Tight score band with many results → AMBIGUOUS confidence."""
    return [
        _make_chunk(
            chunk_id=f"c{i}",
            chunk_index=i,
            reranker_score=5.0 + 0.01 * (n - i),
            score=0.8,
        )
        for i in range(n)
    ]


def _make_reranked_result(chunks: list[dict]) -> RerankedResult:
    return RerankedResult(chunks=chunks, signal=RetrievalSignal.from_results(chunks))


@pytest.fixture(autouse=True)
def _patch_dependencies():
    """Patch query map to isolate search tier logic."""
    with patch(
        "vertical_engines.credit.retrieval.evidence.build_chapter_query_map",
        return_value={"ch01_exec": ["test query"]},
    ):
        yield


@pytest.fixture()
def mock_embeddings():
    """Patch embedding service to return a dummy vector."""
    emb_result = MagicMock()
    emb_result.vectors = [[0.1] * 10]
    with patch(
        "ai_engine.extraction.embedding_service.generate_embeddings",
        return_value=emb_result,
    ) as mock:
        yield mock


def _call_gather(mock_search):
    from vertical_engines.credit.retrieval.evidence import gather_chapter_evidence

    return gather_chapter_evidence(
        chapter_key="ch01_exec",
        deal_name=_DEAL_ID,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        organization_id=_ORG_ID,
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestSignalBasedExpansion:
    """Search tier expansion triggered by LOW/AMBIGUOUS confidence."""

    def test_low_confidence_triggers_expansion(self, mock_embeddings):
        """LOW confidence should trigger expansion with EXPANDED_SEARCH_TIER."""
        from vertical_engines.credit.retrieval.models import EXPANDED_SEARCH_TIER

        low_chunks = _make_low_confidence_chunks(2)
        expanded_chunks = _make_high_confidence_chunks(8)

        def _side_effect(*, deal_id, organization_id, query_text, query_vector, top, candidates, **kw):
            if candidates == EXPANDED_SEARCH_TIER[1]:
                return _make_reranked_result(expanded_chunks)
            return _make_reranked_result(low_chunks)

        with patch(
            "ai_engine.extraction.pgvector_search_service.search_and_rerank_deal_sync",
            side_effect=_side_effect,
        ) as mock_search:
            result = _call_gather(mock_search)

        assert result["search_expanded"] is True
        assert mock_search.call_count >= 2

    def test_high_confidence_no_expansion(self, mock_embeddings):
        """HIGH confidence should NOT trigger expansion."""
        high_chunks = _make_high_confidence_chunks(8)

        with patch(
            "ai_engine.extraction.pgvector_search_service.search_and_rerank_deal_sync",
            return_value=_make_reranked_result(high_chunks),
        ) as mock_search:
            result = _call_gather(mock_search)

        assert result["search_expanded"] is False
        assert mock_search.call_count == 1

    def test_moderate_confidence_no_expansion(self, mock_embeddings):
        """MODERATE confidence should NOT trigger expansion."""
        moderate_chunks = _make_moderate_confidence_chunks(5)

        with patch(
            "ai_engine.extraction.pgvector_search_service.search_and_rerank_deal_sync",
            return_value=_make_reranked_result(moderate_chunks),
        ) as mock_search:
            result = _call_gather(mock_search)

        assert result["search_expanded"] is False

    def test_ambiguous_triggers_expansion(self, mock_embeddings):
        """AMBIGUOUS confidence should trigger expansion."""
        from vertical_engines.credit.retrieval.models import EXPANDED_SEARCH_TIER

        ambiguous_chunks = _make_ambiguous_chunks(6)
        expanded_chunks = _make_high_confidence_chunks(10)

        def _side_effect(*, deal_id, organization_id, query_text, query_vector, top, candidates, **kw):
            if candidates == EXPANDED_SEARCH_TIER[1]:
                return _make_reranked_result(expanded_chunks)
            return _make_reranked_result(ambiguous_chunks)

        with patch(
            "ai_engine.extraction.pgvector_search_service.search_and_rerank_deal_sync",
            side_effect=_side_effect,
        ) as mock_search:
            result = _call_gather(mock_search)

        assert result["search_expanded"] is True

    def test_missing_no_expansion(self, mock_embeddings):
        """COVERAGE_MISSING should NOT trigger expansion even with LOW confidence."""
        with patch(
            "ai_engine.extraction.pgvector_search_service.search_and_rerank_deal_sync",
            return_value=_make_reranked_result([]),
        ) as mock_search:
            result = _call_gather(mock_search)

        assert result["search_expanded"] is False
        assert result["coverage_status"] == "MISSING_EVIDENCE"
        assert mock_search.call_count == 1
