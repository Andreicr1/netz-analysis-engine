"""Tests for tenant isolation in Azure Search queries (Security F2/F5/F6).

Validates that:
- _validate_uuid() correctly accepts/rejects UUIDs
- _validate_domain() accepts valid domains and rejects unknowns
- search_deal_chunks() includes organization_id in OData filter
- search_fund_policy_chunks() includes organization_id in OData filter
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from ai_engine.extraction.search_upsert_service import (
    _validate_domain,
    _validate_uuid,
)

# ── UUID validation ───────────────────────────────────────────────────


class TestValidateUUID:
    """_validate_uuid() must normalize valid UUIDs and reject invalid ones."""

    def test_accepts_lowercase_hyphenated(self):
        result = _validate_uuid("550e8400-e29b-41d4-a716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_accepts_uppercase(self):
        result = _validate_uuid("550E8400-E29B-41D4-A716-446655440000")
        # uuid.UUID normalizes to lowercase
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_accepts_uuid_object(self):
        u = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        result = _validate_uuid(u)
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid("")

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid("' OR 1=1 --")

    def test_rejects_odata_injection(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid("' or deal_id ne '")

    def test_rejects_random_string(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid("not-a-uuid-at-all")

    def test_rejects_none_via_attribute_error(self):
        with pytest.raises(ValueError, match="Invalid UUID"):
            _validate_uuid(None, "test_field")  # type: ignore[arg-type]

    def test_field_name_in_error_message(self):
        with pytest.raises(ValueError, match="organization_id"):
            _validate_uuid("invalid", "organization_id")

    def test_normalizes_format(self):
        """Ensures consistent lowercase-hyphenated output for OData filter."""
        result = _validate_uuid("550E8400E29B41D4A716446655440000")
        assert "-" in result
        assert result == result.lower()


# ── Domain validation ──────────────────────────────────────────────────


class TestValidateDomain:
    """_validate_domain() must accept known domains and reject unknowns."""

    @pytest.mark.parametrize("domain", [
        "credit", "wealth", "macro", "benchmark",
        "POLICY", "REGULATORY", "CONSTITUTION", "SERVICE_PROVIDER",
        "PIPELINE",
    ])
    def test_accepts_valid_domains(self, domain: str):
        assert _validate_domain(domain) == domain

    def test_rejects_unknown_domain(self):
        with pytest.raises(ValueError, match="Invalid domain"):
            _validate_domain("EVIL_DOMAIN")

    def test_rejects_odata_injection_in_domain(self):
        with pytest.raises(ValueError, match="Invalid domain"):
            _validate_domain("credit' or 1 eq 1 or domain eq '")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Invalid domain"):
            _validate_domain("")


# ── search_deal_chunks org_id filter ───────────────────────────────────


class TestSearchDealChunksOrgFilter:
    """Verify organization_id is included in the OData filter expression."""

    @patch("app.services.azure.search_client.get_search_client")
    def test_filter_includes_organization_id(self, mock_get_client):
        from ai_engine.extraction.search_upsert_service import search_deal_chunks

        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_get_client.return_value = mock_client

        deal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        search_deal_chunks(
            deal_id=deal_id,
            organization_id=org_id,
            query_text="test",
        )

        call_kwargs = mock_client.search.call_args[1]
        filter_expr = call_kwargs["filter"]
        assert f"organization_id eq '{org_id}'" in filter_expr
        assert f"deal_id eq '{deal_id}'" in filter_expr

    @patch("app.services.azure.search_client.get_search_client")
    def test_filter_includes_domain_when_provided(self, mock_get_client):
        from ai_engine.extraction.search_upsert_service import search_deal_chunks

        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_get_client.return_value = mock_client

        deal_id = uuid.uuid4()
        org_id = uuid.uuid4()

        search_deal_chunks(
            deal_id=deal_id,
            organization_id=org_id,
            query_text="test",
            domain_filter="credit",
        )

        call_kwargs = mock_client.search.call_args[1]
        filter_expr = call_kwargs["filter"]
        assert "organization_id" in filter_expr
        assert "domain eq 'credit'" in filter_expr

    @patch("app.services.azure.search_client.get_search_client")
    def test_rejects_invalid_organization_id(self, _mock):
        from ai_engine.extraction.search_upsert_service import search_deal_chunks

        with pytest.raises(ValueError, match="Invalid UUID"):
            search_deal_chunks(
                deal_id=uuid.uuid4(),
                organization_id="not-a-uuid",
                query_text="test",
            )

    @patch("app.services.azure.search_client.get_search_client")
    def test_rejects_invalid_domain_filter(self, _mock):
        from ai_engine.extraction.search_upsert_service import search_deal_chunks

        with pytest.raises(ValueError, match="Invalid domain"):
            search_deal_chunks(
                deal_id=uuid.uuid4(),
                organization_id=uuid.uuid4(),
                query_text="test",
                domain_filter="EVIL",
            )


# ── search_fund_policy_chunks org_id filter ────────────────────────────


class TestSearchFundPolicyChunksOrgFilter:
    """Verify organization_id is included in fund policy search filters."""

    @patch("app.services.azure.search_client.get_search_client")
    def test_filter_includes_organization_id(self, mock_get_client):
        from ai_engine.extraction.search_upsert_service import search_fund_policy_chunks

        mock_client = MagicMock()
        mock_client.search.return_value = []
        mock_get_client.return_value = mock_client

        fund_id = uuid.uuid4()
        org_id = uuid.uuid4()

        search_fund_policy_chunks(
            fund_id=fund_id,
            organization_id=org_id,
            query_text="test",
        )

        call_kwargs = mock_client.search.call_args[1]
        filter_expr = call_kwargs["filter"]
        assert f"organization_id eq '{org_id}'" in filter_expr
        assert f"fund_id eq '{fund_id}'" in filter_expr
        assert "domain eq 'POLICY'" in filter_expr
