"""Tests for pgvector search service — drop-in replacement for Azure AI Search.

Validates:
- UpsertResult properties (full success, degraded, total failure)
- build_search_document() produces correct chunk IDs
- validate_uuid() / validate_domain() correctness
- search functions return empty list when no query_vector
- Sync search wrappers exist and are callable
"""
from __future__ import annotations

import uuid

import pytest

from ai_engine.extraction.pgvector_search_service import (
    UpsertResult,
    build_search_document,
    validate_domain,
    validate_uuid,
)

# ── UpsertResult ─────────────────────────────────────────────────────


class TestUpsertResult:
    def test_full_success(self):
        r = UpsertResult(
            attempted_chunk_count=5,
            successful_chunk_count=5,
            failed_chunk_count=0,
            retryable=False,
        )
        assert r.is_full_success
        assert not r.is_degraded
        assert not r.is_total_failure

    def test_degraded(self):
        r = UpsertResult(
            attempted_chunk_count=5,
            successful_chunk_count=3,
            failed_chunk_count=2,
            retryable=True,
        )
        assert not r.is_full_success
        assert r.is_degraded
        assert not r.is_total_failure

    def test_total_failure(self):
        r = UpsertResult(
            attempted_chunk_count=5,
            successful_chunk_count=0,
            failed_chunk_count=5,
            retryable=True,
        )
        assert not r.is_full_success
        assert not r.is_degraded
        assert r.is_total_failure

    def test_empty_result(self):
        r = UpsertResult(
            attempted_chunk_count=0,
            successful_chunk_count=0,
            failed_chunk_count=0,
            retryable=False,
        )
        assert not r.is_full_success
        assert not r.is_degraded
        assert not r.is_total_failure


# ── build_search_document ────────────────────────────────────────────


class TestBuildSearchDocument:
    def test_chunk_id_with_document_id(self):
        deal_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        doc = build_search_document(
            deal_id=deal_id,
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="CIM",
            authority="test",
            title="Test Doc",
            chunk_index=3,
            content="Hello",
            embedding=[0.1] * 3072,
            page_start=1,
            page_end=2,
            document_id=doc_id,
            organization_id=uuid.uuid4(),
        )
        # _safe_id keeps hyphens (alphanumeric + dash + underscore)
        expected_id = f"{deal_id}_{doc_id}_3"
        assert doc["id"] == expected_id

    def test_chunk_id_without_document_id(self):
        deal_id = uuid.uuid4()
        doc = build_search_document(
            deal_id=deal_id,
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="CIM",
            authority="test",
            title="Test Doc",
            chunk_index=0,
            content="Hello",
            embedding=[0.1] * 3072,
            page_start=1,
            page_end=2,
        )
        expected_id = f"{deal_id}_CIM_0"
        assert doc["id"] == expected_id

    def test_required_fields_present(self):
        doc = build_search_document(
            deal_id=uuid.uuid4(),
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="CIM",
            authority="test",
            title="Test",
            chunk_index=0,
            content="Content",
            embedding=[0.1] * 3072,
            page_start=0,
            page_end=1,
            organization_id=uuid.uuid4(),
        )
        assert "id" in doc
        assert "organization_id" in doc
        assert "content" in doc
        assert "embedding" in doc
        assert doc["domain"] == "credit"


# ── Validation ───────────────────────────────────────────────────────


class TestValidateUUID:
    def test_accepts_valid_uuid(self):
        u = uuid.uuid4()
        assert validate_uuid(u) == str(u)

    def test_accepts_string_uuid(self):
        s = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_uuid(s) == s

    def test_rejects_invalid(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            validate_uuid("not-a-uuid")

    def test_rejects_injection(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            validate_uuid("' OR 1=1 --")


class TestValidateDomain:
    @pytest.mark.parametrize("domain", [
        "credit", "wealth", "macro", "benchmark",
        "POLICY", "REGULATORY", "CONSTITUTION", "SERVICE_PROVIDER", "PIPELINE",
    ])
    def test_accepts_valid(self, domain: str):
        assert validate_domain(domain) == domain

    def test_rejects_invalid(self):
        with pytest.raises(ValueError, match="Invalid domain"):
            validate_domain("EVIL")


# ── Search functions return empty on no vector ───────────────────────


class TestSearchEdgeCases:
    """Test that search functions handle edge cases without DB connection."""

    def test_sync_search_no_vector_returns_empty(self):
        from ai_engine.extraction.pgvector_search_service import search_deal_chunks_sync

        result = search_deal_chunks_sync(
            deal_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            query_text="test",
            query_vector=None,
        )
        assert result == []

    def test_sync_fund_search_no_vector_returns_empty(self):
        from ai_engine.extraction.pgvector_search_service import search_fund_policy_chunks_sync

        result = search_fund_policy_chunks_sync(
            fund_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            query_text="test",
            query_vector=None,
        )
        assert result == []

    def test_sync_search_rejects_invalid_org_id(self):
        from ai_engine.extraction.pgvector_search_service import search_deal_chunks_sync

        with pytest.raises(ValueError, match="Invalid UUID"):
            search_deal_chunks_sync(
                deal_id=uuid.uuid4(),
                organization_id="not-valid",
                query_vector=[0.1] * 3072,
            )

    def test_sync_search_rejects_invalid_domain(self):
        from ai_engine.extraction.pgvector_search_service import search_deal_chunks_sync

        with pytest.raises(ValueError, match="Invalid domain"):
            search_deal_chunks_sync(
                deal_id=uuid.uuid4(),
                organization_id=uuid.uuid4(),
                query_vector=[0.1] * 3072,
                domain_filter="EVIL",
            )


# ── Async search edge cases ──────────────────────────────────────────


class TestAsyncSearchEdgeCases:
    """Async search returns empty when no query_vector."""

    @pytest.mark.asyncio
    async def test_async_search_no_vector(self):
        from unittest.mock import AsyncMock

        from ai_engine.extraction.pgvector_search_service import search_deal_chunks

        mock_db = AsyncMock()
        result = await search_deal_chunks(
            mock_db,
            deal_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            query_vector=None,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_async_fund_search_no_vector(self):
        from unittest.mock import AsyncMock

        from ai_engine.extraction.pgvector_search_service import search_fund_policy_chunks

        mock_db = AsyncMock()
        result = await search_fund_policy_chunks(
            mock_db,
            fund_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            query_vector=None,
        )
        assert result == []
