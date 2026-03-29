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


class TestEmbedSecManagerProfiles:
    @pytest.mark.asyncio
    async def test_no_rows_returns_zero(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_manager_profiles,
        )

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_db.execute.return_value = result_mock

        result = await _embed_sec_manager_profiles(mock_db)
        assert result == {"embedded": 0}

    @pytest.mark.asyncio
    async def test_generates_profile_text(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_manager_profiles,
        )

        rows = [
            _make_row(
                crd_number="55555",
                firm_name="Acme Capital LLC",
                registration_status="Approved",
                state="NY",
                country="US",
                aum_total=5_000_000_000,
                aum_discretionary=4_500_000_000,
                total_accounts=150,
                fee_types={"performance": True, "fixed": True},
                client_types={"institutional": True},
                compliance_disclosures=2,
                last_adv_filed_at=date(2026, 2, 1),
                private_fund_count=3,
                hedge_fund_count=2,
                pe_fund_count=1,
                vc_fund_count=0,
                real_estate_fund_count=0,
                other_fund_count=0,
                total_private_fund_assets=3_000_000_000,
                team_count=12,
                top_team="John Doe (CIO), Jane Smith (PM), Bob Lee (Analyst)",
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
                result = await _embed_sec_manager_profiles(mock_db)

        assert result == {"embedded": 1}
        upsert_rows = mock_upsert.call_args[0][1]
        row = upsert_rows[0]
        assert row["entity_type"] == "firm"
        assert row["source_type"] == "sec_manager_profile"
        assert row["firm_crd"] == "55555"
        assert row["id"] == "sec_manager_profile_55555"
        assert "Acme Capital" in row["content"]
        assert "$5.0B" in row["content"]
        assert "3 private funds" in row["content"]


class TestEmbedSecFundProfiles:
    @pytest.mark.asyncio
    async def test_no_rows_returns_zero(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_fund_profiles,
        )

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_db.execute.return_value = result_mock

        result = await _embed_sec_fund_profiles(mock_db)
        assert result == {"embedded": 0}

    @pytest.mark.asyncio
    async def test_includes_holdings_in_content(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_fund_profiles,
        )

        rows = [
            _make_row(
                cik="0001234567",
                fund_name="Acme Growth Fund",
                fund_type="mutual_fund",
                strategy_label="Large Cap Growth",
                total_assets=500_000_000,
                monthly_avg_net_assets=None,
                inception_date=date(2015, 6, 1),
                last_nport_date=date(2026, 3, 1),
                crd_number="55555",
                lei=None,
                is_index=False,
                is_target_date=False,
                is_fund_of_fund=False,
                management_fee=None,
                net_operating_expenses=None,
                return_after_fees=None,
                return_before_fees=None,
                adviser_name="Acme Capital LLC",
                class_list="Class A (ACMGX), Class I (ACMIX)",
                top_holdings="Apple Inc (Technology): 5.2%; Microsoft Corp (Technology): 4.8%",
                sectors="Technology, Healthcare",
                holdings_date=date(2026, 3, 1),
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
                result = await _embed_sec_fund_profiles(mock_db)

        assert result == {"embedded": 1}
        row = mock_upsert.call_args[0][1][0]
        assert row["entity_type"] == "fund"
        assert row["source_type"] == "sec_fund_profile"
        assert row["firm_crd"] == "55555"
        assert "Apple Inc" in row["content"]
        assert "Class A" in row["content"]


class TestEmbedSec13fSummaries:
    @pytest.mark.asyncio
    async def test_no_rows_returns_zero(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_13f_summaries,
        )

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_db.execute.return_value = result_mock

        result = await _embed_sec_13f_summaries(mock_db)
        assert result == {"embedded": 0}

    @pytest.mark.asyncio
    async def test_generates_summary_with_concentration(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_13f_summaries,
        )

        rows = [
            _make_row(
                cik="0009876543",
                report_date=date(2026, 3, 15),
                position_count=250,
                total_value=10_000_000_000,
                top_holdings="Apple: $1,000,000,000 (10.0%); Microsoft: $800,000,000 (8.0%)",
                top5_pct=35.0,
                top10_pct=55.0,
                sector_breakdown="Technology: 40.0%; Healthcare: 20.0%",
                firm_name="Big Fund Manager",
                crd_number="77777",
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
                result = await _embed_sec_13f_summaries(mock_db)

        assert result == {"embedded": 1}
        row = mock_upsert.call_args[0][1][0]
        assert row["entity_type"] == "firm"
        assert row["source_type"] == "sec_13f_summary"
        assert row["firm_crd"] == "77777"
        assert "Top 5 = 35.0%" in row["content"]
        assert "Top 10 = 55.0%" in row["content"]
        assert row["filing_date"] == date(2026, 3, 15)
        assert row["id"] == "sec_13f_summary_0009876543_2026-03-15"


class TestEmbedSecPrivateFunds:
    @pytest.mark.asyncio
    async def test_no_rows_returns_zero(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_private_funds,
        )

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_db.execute.return_value = result_mock

        result = await _embed_sec_private_funds(mock_db)
        assert result == {"embedded": 0}

    @pytest.mark.asyncio
    async def test_generates_fund_list(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_private_funds,
        )

        rows = [
            _make_row(
                crd_number="55555",
                strategy="Hedge Fund",
                fund_count=3,
                strategy_gav=2_000_000_000,
                fof_count=1,
                type_breakdown="Hedge Fund, PE Fund",
                fund_list="Alpha Fund (Hedge Fund): GAV $1,000,000,000, 50 investors; Beta Fund (PE Fund): GAV $800,000,000, 20 investors",
                firm_name="Acme Capital LLC",
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
                result = await _embed_sec_private_funds(mock_db)

        assert result == {"embedded": 1}
        row = mock_upsert.call_args[0][1][0]
        assert row["entity_type"] == "firm"
        assert row["source_type"] == "sec_private_funds"
        assert row["id"] == "sec_private_funds_55555_hedge_fund"
        assert "Alpha Fund" in row["content"]
        assert "Fund-of-funds: 1" in row["content"]


class TestEmbedEsmaFundProfiles:
    @pytest.mark.asyncio
    async def test_entity_type_is_fund(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_esma_fund_profiles,
        )

        rows = [
            _make_row(
                isin="IE00B4L5Y983",
                fund_name="iShares Core MSCI World",
                fund_type="UCITS ETF",
                domicile="IE",
                host_member_states=["DE", "FR", "NL"],
                yahoo_ticker="IWDA.AS",
                manager_name="BlackRock Fund Managers",
                manager_country="IE",
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
                result = await _embed_esma_fund_profiles(mock_db)

        assert result == {"embedded": 1}
        row = mock_upsert.call_args[0][1][0]
        assert row["entity_type"] == "fund"
        assert row["source_type"] == "esma_fund_profile"
        assert row["entity_id"] == "IE00B4L5Y983"
        assert row["id"] == "esma_fund_profile_IE00B4L5Y983"
        assert "BlackRock" in row["content"]
        assert "DE, FR, NL" in row["content"]
        assert "IWDA.AS" in row["content"]


class TestEmbedEsmaManagerProfiles:
    @pytest.mark.asyncio
    async def test_firm_crd_populated(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_esma_manager_profiles,
        )

        rows = [
            _make_row(
                esma_manager_id="ESM_001",
                strategy="UCITS",
                company_name="BlackRock Fund Managers",
                country="IE",
                authorization_status="Authorised",
                lei="549300ABCDEF123456",
                resolved_crd="99999",
                sec_name=None,
                sec_aum=None,
                sec_pf_count=None,
                fund_count=42,
                domicile_count=5,
                domiciles="IE, LU, DE, FR, NL",
                with_ticker=10,
                fund_list="Fund A (IE); Fund B (LU)",
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
                result = await _embed_esma_manager_profiles(mock_db)

        assert result == {"embedded": 1}
        row = mock_upsert.call_args[0][1][0]
        assert row["entity_type"] == "firm"
        assert row["source_type"] == "esma_manager_profile"
        assert row["firm_crd"] == "99999"
        assert row["id"] == "esma_manager_ESM_001_ucits"
        assert "42 UCITS sub-funds" in row["content"]
        assert "5 domiciles" in row["content"]


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


class TestCleanupLegacySourceTypes:
    @pytest.mark.asyncio
    async def test_deletes_old_source_types(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _cleanup_legacy_source_types,
        )

        result_mock = MagicMock()
        result_mock.rowcount = 150
        mock_db.execute.return_value = result_mock

        await _cleanup_legacy_source_types(mock_db)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_commit_when_nothing_deleted(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _cleanup_legacy_source_types,
        )

        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_db.execute.return_value = result_mock

        await _cleanup_legacy_source_types(mock_db)
        mock_db.commit.assert_not_called()


class TestFormatAum:
    def test_billions(self):
        from app.domains.wealth.workers.wealth_embedding_worker import _format_aum

        assert _format_aum(5_000_000_000) == "$5.0B"

    def test_millions(self):
        from app.domains.wealth.workers.wealth_embedding_worker import _format_aum

        assert _format_aum(500_000_000) == "$500.0M"

    def test_small(self):
        from app.domains.wealth.workers.wealth_embedding_worker import _format_aum

        assert _format_aum(500_000) == "$500,000"

    def test_none(self):
        from app.domains.wealth.workers.wealth_embedding_worker import _format_aum

        assert _format_aum(None) == "N/A"

    def test_zero(self):
        from app.domains.wealth.workers.wealth_embedding_worker import _format_aum

        assert _format_aum(0) == "N/A"


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


class TestIdempotency:
    """Verify that second call with same data produces 0 new rows."""

    @pytest.mark.asyncio
    async def test_sec_manager_profiles_idempotent(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_sec_manager_profiles,
        )

        # First call returns rows, second returns empty (LEFT JOIN finds existing)
        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_db.execute.return_value = result_mock

        result = await _embed_sec_manager_profiles(mock_db)
        assert result == {"embedded": 0}

    @pytest.mark.asyncio
    async def test_esma_fund_profiles_idempotent(self, mock_db):
        from app.domains.wealth.workers.wealth_embedding_worker import (
            _embed_esma_fund_profiles,
        )

        result_mock = MagicMock()
        result_mock.fetchall.return_value = []
        mock_db.execute.return_value = result_mock

        result = await _embed_esma_fund_profiles(mock_db)
        assert result == {"embedded": 0}
