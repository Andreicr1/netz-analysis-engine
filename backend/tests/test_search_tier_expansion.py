"""Tests for Phase 5 — signal-based search tier expansion."""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ──────────────────────────────────────────────────────────

_DEAL_ID = "deal-1"
_FUND_ID = "fund-1"


@dataclass
class _FakeHit:
    """Minimal hit object matching searcher.search_institutional_hybrid()."""

    chunk_id: str = "c1"
    title: str = "doc.pdf"
    blob_name: str = "doc.pdf"
    doc_type: str = "fund_doc"
    authority: str = "manager"
    page_start: int = 1
    page_end: int = 2
    chunk_index: int = 0
    content_text: str = "content"
    score: float = 0.8
    reranker_score: float = 5.0
    container_name: str = ""
    retrieval_timestamp: str = ""
    fund_id: str = _FUND_ID
    deal_id: str = _DEAL_ID
    section_type: str | None = None
    vehicle_type: str | None = None
    governance_critical: bool = False
    governance_flags: list = field(default_factory=list)
    breadcrumb: str | None = None


def _make_high_confidence_hits(n: int = 6) -> list[_FakeHit]:
    """Hits with large delta between top1 and top2 → HIGH confidence."""
    hits = [_FakeHit(chunk_id="c0", chunk_index=0, reranker_score=10.0, score=0.95)]
    for i in range(1, n):
        hits.append(
            _FakeHit(
                chunk_id=f"c{i}",
                chunk_index=i,
                reranker_score=5.0 - i * 0.1,
                score=0.8 - i * 0.01,
            )
        )
    return hits


def _make_low_confidence_hits(n: int = 2) -> list[_FakeHit]:
    """Too few results → LOW confidence."""
    return [
        _FakeHit(
            chunk_id=f"c{i}",
            chunk_index=i,
            reranker_score=3.0 - i * 0.1,
            score=0.7 - i * 0.01,
        )
        for i in range(n)
    ]


def _make_moderate_confidence_hits(n: int = 5) -> list[_FakeHit]:
    """Delta between MODERATE thresholds → MODERATE confidence."""
    hits = [_FakeHit(chunk_id="c0", chunk_index=0, reranker_score=6.0)]
    for i in range(1, n):
        hits.append(
            _FakeHit(
                chunk_id=f"c{i}",
                chunk_index=i,
                reranker_score=5.0 - i * 0.05,
            )
        )
    return hits


def _make_ambiguous_hits(n: int = 6) -> list[_FakeHit]:
    """Tight score band with many results → AMBIGUOUS confidence."""
    return [
        _FakeHit(
            chunk_id=f"c{i}",
            chunk_index=i,
            reranker_score=5.0 + 0.01 * (n - i),
            score=0.8,
        )
        for i in range(n)
    ]


@pytest.fixture()
def mock_searcher():
    return MagicMock()


@pytest.fixture(autouse=True)
def _patch_dependencies():
    """Patch query map and doc_type filters to isolate search tier logic."""
    with (
        patch(
            "vertical_engines.credit.retrieval.evidence.build_chapter_query_map",
            return_value={"ch01_exec": ["test query"]},
        ),
        patch(
            "vertical_engines.credit.retrieval.evidence.CHAPTER_DOC_TYPE_FILTERS",
            {"ch01_exec": None},
        ),
    ):
        yield


def _call_gather(mock_searcher):
    from vertical_engines.credit.retrieval.evidence import gather_chapter_evidence

    return gather_chapter_evidence(
        chapter_key="ch01_exec",
        deal_name=_DEAL_ID,  # must match chunk deal_id for contamination filter
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        searcher=mock_searcher,
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestSignalBasedExpansion:
    """Search tier expansion triggered by LOW/AMBIGUOUS confidence."""

    def test_low_confidence_triggers_expansion(self, mock_searcher):
        """LOW confidence should trigger expansion with EXPANDED_SEARCH_TIER."""
        from vertical_engines.credit.retrieval.models import EXPANDED_SEARCH_TIER

        low_hits = _make_low_confidence_hits(2)
        expanded_hits = _make_high_confidence_hits(8)

        def _side_effect(**kwargs):
            top = kwargs.get("top")
            if top == EXPANDED_SEARCH_TIER[0]:
                return expanded_hits
            return low_hits

        mock_searcher.search_institutional_hybrid.side_effect = _side_effect

        result = _call_gather(mock_searcher)

        assert result["search_expanded"] is True
        assert mock_searcher.search_institutional_hybrid.call_count >= 2

    def test_high_confidence_no_expansion(self, mock_searcher):
        """HIGH confidence should NOT trigger expansion."""
        high_hits = _make_high_confidence_hits(8)
        mock_searcher.search_institutional_hybrid.return_value = high_hits

        result = _call_gather(mock_searcher)

        assert result["search_expanded"] is False
        assert mock_searcher.search_institutional_hybrid.call_count == 1

    def test_moderate_confidence_no_expansion(self, mock_searcher):
        """MODERATE confidence should NOT trigger expansion."""
        moderate_hits = _make_moderate_confidence_hits(5)
        mock_searcher.search_institutional_hybrid.return_value = moderate_hits

        result = _call_gather(mock_searcher)

        assert result["search_expanded"] is False

    def test_ambiguous_triggers_expansion(self, mock_searcher):
        """AMBIGUOUS confidence should trigger expansion."""
        from vertical_engines.credit.retrieval.models import EXPANDED_SEARCH_TIER

        ambiguous_hits = _make_ambiguous_hits(6)
        expanded_hits = _make_high_confidence_hits(10)

        def _side_effect(**kwargs):
            top = kwargs.get("top")
            if top == EXPANDED_SEARCH_TIER[0]:
                return expanded_hits
            return ambiguous_hits

        mock_searcher.search_institutional_hybrid.side_effect = _side_effect

        result = _call_gather(mock_searcher)

        assert result["search_expanded"] is True

    def test_missing_no_expansion(self, mock_searcher):
        """COVERAGE_MISSING should NOT trigger expansion even with LOW confidence."""
        mock_searcher.search_institutional_hybrid.return_value = []

        result = _call_gather(mock_searcher)

        assert result["search_expanded"] is False
        assert result["coverage_status"] == "MISSING_EVIDENCE"
        assert mock_searcher.search_institutional_hybrid.call_count == 1
