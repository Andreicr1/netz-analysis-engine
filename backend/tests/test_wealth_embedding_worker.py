"""Tests for wealth_embedding_worker — unit tests with mocked DB + embeddings."""

from __future__ import annotations

import uuid  # noqa: I001
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.models.wealth_vector_chunk import WealthVectorChunk

# ── Model tests ──────────────────────────────────────────────────────


class TestWealthVectorChunkModel:
    def test_tablename(self):
        assert WealthVectorChunk.__tablename__ == "wealth_vector_chunks"

    def test_no_organization_scoped_mixin(self):
        """Model must NOT use OrganizationScopedMixin (org_id is nullable)."""
        from app.core.db.base import OrganizationScopedMixin

        assert not issubclass(WealthVectorChunk, OrganizationScopedMixin)

    def test_org_id_nullable(self):
        col = WealthVectorChunk.__table__.c.organization_id
        assert col.nullable is True

    def test_entity_type_not_nullable(self):
        col = WealthVectorChunk.__table__.c.entity_type
        assert col.nullable is False


# ── Worker function tests ────────────────────────────────────────────


def _fake_embedding_batch(n: int, model: str = "text-embedding-3-large"):
    """Create a fake EmbeddingBatch."""
    from ai_engine.extraction.embedding_service import EmbeddingBatch

    return EmbeddingBatch(
        vectors=[[0.1] * 3072 for _ in range(n)],
        model=model,
        count=n,
    )


def _make_row(**kwargs):
    """Create a mock row with attribute access."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestEmbedBrochureSections:
    @pytest.mark.asyncio
    async def test_no_rows_returns_zero(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_brochure_sections,
        )

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_db.execute.return_value = result_mock

        result = await _embed_brochure_sections(mock_db)
        assert result == {"embedded": 0}

    @pytest.mark.asyncio
    async def test_embeds_with_firm_entity_type(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_brochure_sections,
        )

        rows = [
            _make_row(
                crd_number="12345",
                section="investment_philosophy",
                content="We invest in value stocks...",
                filing_date=date(2026, 1, 15),
            ),
        ]
        select_result = MagicMock()
        select_result.fetchall.return_value = rows
        mock_db.execute.return_value = select_result

        with patch(
            "app.domains.wealth.workers.wealth_embedding_worker.async_generate_embeddings",
            return_value=_fake_embedding_batch(1),
        ):
            with patch(
                "app.domains.wealth.workers.wealth_embedding_worker._batch_upsert",
            ) as mock_upsert:
                result = await _embed_brochure_sections(mock_db)

        assert result == {"embedded": 1}
        upsert_rows = mock_upsert.call_args[0][1]
        assert upsert_rows[0]["entity_type"] == "firm"
        assert upsert_rows[0]["firm_crd"] == "12345"
        assert "manager" not in str(upsert_rows)


class TestEmbedEsmaFunds:
    @pytest.mark.asyncio
    async def test_entity_type_is_fund(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_esma_funds,
        )

        rows = [
            _make_row(
                isin="IE00B4L5Y983",
                fund_name="iShares Core MSCI World",
                fund_type="UCITS ETF",
                domicile="IE",
                esma_manager_id="ESM_001",
            ),
        ]
        select_result = MagicMock()
        select_result.fetchall.return_value = rows
        mock_db.execute.return_value = select_result

        with patch(
            "app.domains.wealth.workers.wealth_embedding_worker.async_generate_embeddings",
            return_value=_fake_embedding_batch(1),
        ):
            with patch(
                "app.domains.wealth.workers.wealth_embedding_worker._batch_upsert",
            ) as mock_upsert:
                result = await _embed_esma_funds(mock_db)

        assert result == {"embedded": 1}
        upsert_rows = mock_upsert.call_args[0][1]
        assert upsert_rows[0]["entity_type"] == "fund"
        assert upsert_rows[0]["entity_id"] == "IE00B4L5Y983"


class TestEmbedEsmaManagers:
    @pytest.mark.asyncio
    async def test_firm_crd_populated(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_esma_managers,
        )

        rows = [
            _make_row(
                esma_id="ESM_001",
                company_name="BlackRock Fund Managers",
                country="IE",
                authorization_status="Authorised",
                sec_crd_number="99999",
            ),
        ]
        select_result = MagicMock()
        select_result.fetchall.return_value = rows
        mock_db.execute.return_value = select_result

        with patch(
            "app.domains.wealth.workers.wealth_embedding_worker.async_generate_embeddings",
            return_value=_fake_embedding_batch(1),
        ):
            with patch(
                "app.domains.wealth.workers.wealth_embedding_worker._batch_upsert",
            ) as mock_upsert:
                result = await _embed_esma_managers(mock_db)

        assert result == {"embedded": 1}
        upsert_rows = mock_upsert.call_args[0][1]
        assert upsert_rows[0]["entity_type"] == "firm"
        assert upsert_rows[0]["firm_crd"] == "99999"


class TestEmbedDdChapters:
    @pytest.mark.asyncio
    async def test_org_scoped_with_instrument_id(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_dd_chapters,
        )

        inst_id = uuid.uuid4()
        org_id = uuid.uuid4()
        ch_id = uuid.uuid4()

        rows = [
            _make_row(
                chapter_id=ch_id,
                instrument_id=inst_id,
                organization_id=org_id,
                chapter_tag="executive_summary",
                content_md="# Executive Summary\nFund analysis...",
            ),
        ]
        select_result = MagicMock()
        select_result.fetchall.return_value = rows
        mock_db.execute.return_value = select_result

        with patch(
            "app.domains.wealth.workers.wealth_embedding_worker.async_generate_embeddings",
            return_value=_fake_embedding_batch(1),
        ):
            with patch(
                "app.domains.wealth.workers.wealth_embedding_worker._batch_upsert",
            ) as mock_upsert:
                result = await _embed_dd_chapters(mock_db)

        assert result == {"embedded": 1}
        upsert_rows = mock_upsert.call_args[0][1]
        assert upsert_rows[0]["organization_id"] == str(org_id)
        assert upsert_rows[0]["entity_id"] == str(inst_id)
        assert upsert_rows[0]["entity_type"] == "fund"


class TestRunWealthEmbedding:
    @pytest.mark.asyncio
    async def test_lock_prevents_concurrent_execution(self):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            run_wealth_embedding,
        )

        mock_db = AsyncMock()
        lock_result = MagicMock()
        lock_result.scalar.return_value = False
        mock_db.execute.return_value = lock_result

        with patch(
            "app.domains.wealth.workers.wealth_embedding_worker.async_session",
        ) as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await run_wealth_embedding()

        assert result == {"status": "skipped", "reason": "lock_held"}


# ── Search function tests ────────────────────────────────────────────


class TestSearchFundFirmContextSync:
    def test_returns_empty_when_no_identifiers(self):
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_firm_context_sync,
        )

        result = search_fund_firm_context_sync(
            query_vector=[0.1] * 3072,
            sec_crd=None,
            esma_manager_id=None,
        )
        assert result == []


class TestSearchFundAnalysisSync:
    def test_validates_uuid(self):
        from ai_engine.extraction.pgvector_search_service import (
            search_fund_analysis_sync,
        )

        with pytest.raises(ValueError, match="Invalid UUID"):
            search_fund_analysis_sync(
                organization_id="not-a-uuid",
                query_vector=[0.1] * 3072,
            )
