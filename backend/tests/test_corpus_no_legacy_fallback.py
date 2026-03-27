"""Tests verifying legacy blob fallback has been removed from corpus assembly."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _fake_deal():
    deal = MagicMock()
    deal.id = uuid.uuid4()
    deal.deal_name = "Test Deal"
    deal.title = "Test Deal"
    deal.deal_folder_path = "org/fund/Test Deal"
    return deal


@pytest.fixture
def _fake_investment():
    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.deal_id = uuid.uuid4()
    inv.investment_name = "Test Investment"
    inv.source_container = "container"
    inv.source_folder = "folder"
    return inv


class TestDealEmptyCorpusOnNoChunks:
    """When RAG returns no/insufficient chunks, corpus_text must be empty."""

    @patch("vertical_engines.credit.retrieval.build_retrieval_audit")
    @patch("vertical_engines.credit.retrieval.enforce_evidence_saturation")
    @patch("vertical_engines.credit.retrieval.build_ic_corpus")
    @patch("vertical_engines.credit.retrieval.gather_chapter_evidence")
    @patch("vertical_engines.credit.memo.CHAPTER_REGISTRY", [(0, "ch1", "Chapter 1")])
    def test_deal_empty_corpus_on_no_chunks(
        self,
        mock_gather,
        mock_build_corpus,
        mock_saturation,
        mock_audit,
        _fake_deal,
    ):
        from vertical_engines.credit.deep_review.corpus import _gather_deal_texts

        mock_gather.return_value = {
            "coverage_status": "EMPTY",
            "stats": {"chunk_count": 0, "unique_docs": 0},
        }
        mock_build_corpus.return_value = {
            "corpus_text": "",
            "evidence_map": [],
            "raw_chunks": [],
            "chapter_stats": {},
        }
        sat_mock = MagicMock()
        sat_mock.to_dict.return_value = {"all_saturated": False}
        mock_saturation.return_value = sat_mock
        mock_audit.return_value = {"policy": "test"}

        db = MagicMock()
        result = _gather_deal_texts(
            db,
            fund_id=uuid.uuid4(),
            deal=_fake_deal,
            organization_id=uuid.uuid4(),
        )

        assert result["corpus_text"] == ""
        assert result["evidence_map"] == []
        assert result["raw_chunks"] == []


class TestInvestmentEmptyStringOnNoChunks:
    """When RAG returns no chunks for investment, return empty string."""

    @patch("ai_engine.extraction.pgvector_search_service.search_and_rerank_deal_sync")
    @patch("ai_engine.extraction.embedding_service.generate_embeddings")
    def test_investment_empty_string_on_no_chunks(
        self,
        mock_embed,
        mock_search,
        _fake_investment,
    ):
        from vertical_engines.credit.deep_review.corpus import _gather_investment_texts

        emb_result = MagicMock()
        emb_result.vectors = [[0.1] * 10]
        mock_embed.return_value = emb_result

        search_result = MagicMock()
        search_result.chunks = []
        mock_search.return_value = search_result

        db = MagicMock()
        result = _gather_investment_texts(
            db,
            fund_id=uuid.uuid4(),
            investment=_fake_investment,
            organization_id=uuid.uuid4(),
        )

        assert result == ""


class TestNoBlobStorageInGatherDealTexts:
    """_gather_deal_texts must NOT call download_bytes (blob fallback removed)."""

    @patch("vertical_engines.credit.retrieval.build_retrieval_audit")
    @patch("vertical_engines.credit.retrieval.enforce_evidence_saturation")
    @patch("vertical_engines.credit.retrieval.build_ic_corpus")
    @patch("vertical_engines.credit.retrieval.gather_chapter_evidence")
    @patch("vertical_engines.credit.memo.CHAPTER_REGISTRY", [(0, "ch1", "Chapter 1")])
    @patch("vertical_engines.credit.deep_review.corpus._read_storage_sync")
    def test_no_blob_storage_calls_in_gather(
        self,
        mock_download,
        mock_gather,
        mock_build_corpus,
        mock_saturation,
        mock_audit,
        _fake_deal,
    ):
        from vertical_engines.credit.deep_review.corpus import _gather_deal_texts

        mock_gather.return_value = {
            "coverage_status": "EMPTY",
            "stats": {"chunk_count": 0, "unique_docs": 0},
        }
        mock_build_corpus.return_value = {
            "corpus_text": "",
            "evidence_map": [],
            "raw_chunks": [],
            "chapter_stats": {},
        }
        sat_mock = MagicMock()
        sat_mock.to_dict.return_value = {"all_saturated": False}
        mock_saturation.return_value = sat_mock
        mock_audit.return_value = {"policy": "test"}

        db = MagicMock()
        _gather_deal_texts(
            db,
            fund_id=uuid.uuid4(),
            deal=_fake_deal,
            organization_id=uuid.uuid4(),
        )

        mock_download.assert_not_called()
