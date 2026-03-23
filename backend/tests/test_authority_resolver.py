"""Tests for ai_engine.governance.authority_resolver — authority resolution and issuer detection."""
from __future__ import annotations

from ai_engine.governance.authority_resolver import (
    AUTHORITY_RANK,
    DOC_TYPE_AUTHORITY_OVERRIDE,
    _binding_scope,
    _resolve_authority,
    detect_chunk_issuer,
    enrich_chunks_with_authority,
)

# ── _resolve_authority ────────────────────────────────────────────


class TestResolveAuthority:
    def test_no_override_returns_container_level(self):
        assert _resolve_authority("EVIDENCE", "investment_memo") == "EVIDENCE"

    def test_unknown_container_defaults_to_evidence(self):
        assert _resolve_authority("BOGUS", "investment_memo") == "EVIDENCE"

    def test_override_binding_on_regulatory(self):
        result = _resolve_authority("NARRATIVE", "REGULATORY_CIMA")
        assert result == "BINDING"

    def test_override_binding_on_fund_constitutional(self):
        result = _resolve_authority("EVIDENCE", "FUND_CONSTITUTIONAL")
        assert result == "BINDING"

    def test_intelligence_container_with_binding_override_stays_intelligence(self):
        # Special rule: INTELLIGENCE + BINDING override → INTELLIGENCE
        result = _resolve_authority("INTELLIGENCE", "REGULATORY_CIMA")
        assert result == "INTELLIGENCE"

    def test_narrative_override_on_investor_narrative(self):
        result = _resolve_authority("EVIDENCE", "INVESTOR_NARRATIVE")
        # max(EVIDENCE=3, NARRATIVE=1) → EVIDENCE wins
        assert result == "EVIDENCE"

    def test_narrative_override_on_deal_marketing(self):
        result = _resolve_authority("NARRATIVE", "DEAL_MARKETING")
        assert result == "NARRATIVE"

    def test_service_provider_binding_override(self):
        result = _resolve_authority("EVIDENCE", "SERVICE_PROVIDER_CONTRACT")
        assert result == "BINDING"

    def test_all_overrides_use_valid_authority_ranks(self):
        for doc_type, override in DOC_TYPE_AUTHORITY_OVERRIDE.items():
            assert override in AUTHORITY_RANK


# ── _binding_scope ────────────────────────────────────────────────


class TestBindingScope:
    def test_regulatory_is_fund(self):
        assert _binding_scope("REGULATORY_CIMA") == "FUND"

    def test_fund_constitutional_is_fund(self):
        assert _binding_scope("FUND_CONSTITUTIONAL") == "FUND"

    def test_risk_policy_is_fund(self):
        assert _binding_scope("RISK_POLICY_INTERNAL") == "FUND"

    def test_service_provider_contract(self):
        assert _binding_scope("SERVICE_PROVIDER_CONTRACT") == "SERVICE_PROVIDER"

    def test_investment_memo_is_manager(self):
        assert _binding_scope("INVESTMENT_MEMO") == "MANAGER"

    def test_deal_marketing_is_manager(self):
        assert _binding_scope("DEAL_MARKETING") == "MANAGER"

    def test_unknown_defaults_to_fund(self):
        assert _binding_scope("SOME_UNKNOWN_TYPE") == "FUND"


# ── detect_chunk_issuer ───────────────────────────────────────────


class TestDetectChunkIssuer:
    def test_detects_pwc(self):
        chunk = {"title": "PwC Audit Report", "content": "..."}
        result = detect_chunk_issuer(chunk)
        assert result is not None
        assert result["issuer"] == "PwC"
        assert result["category"] == "audit"

    def test_detects_moodys(self):
        chunk = {"title": "", "content": "Moody's rating report for the fund"}
        result = detect_chunk_issuer(chunk)
        assert result is not None
        assert result["issuer"] == "Moody's"
        assert result["category"] == "rating_agency"

    def test_detects_clifford_chance(self):
        chunk = {"title": "Legal Opinion by Clifford Chance", "content": "..."}
        result = detect_chunk_issuer(chunk)
        assert result is not None
        assert result["issuer"] == "Clifford Chance"
        assert result["category"] == "legal"
        assert result["tier"] == "BINDING"

    def test_detects_cima_regulator(self):
        chunk = {"title": "", "content": "CIMA registration document"}
        result = detect_chunk_issuer(chunk)
        assert result is not None
        assert result["issuer"] == "CIMA"
        assert result["category"] == "regulator"

    def test_detects_ey(self):
        chunk = {"title": "Ernst & Young Report", "content": ""}
        result = detect_chunk_issuer(chunk)
        assert result is not None
        assert result["issuer"] == "EY"

    def test_no_match_returns_none(self):
        chunk = {"title": "Generic Document", "content": "Nothing special here"}
        result = detect_chunk_issuer(chunk)
        assert result is None

    def test_empty_chunk_returns_none(self):
        chunk = {}
        result = detect_chunk_issuer(chunk)
        assert result is None

    def test_detects_from_doc_type(self):
        chunk = {"doc_type": "kpmg audit", "content": ""}
        result = detect_chunk_issuer(chunk)
        assert result is not None
        assert result["issuer"] == "KPMG"

    def test_content_preview_limited_to_600_chars(self):
        # Issuer name at position 700 should NOT be detected
        chunk = {"title": "", "content": "X" * 700 + "PwC"}
        result = detect_chunk_issuer(chunk)
        assert result is None

    def test_detects_houlihan_lokey(self):
        chunk = {"title": "", "content": "Valuation by Houlihan Lokey"}
        result = detect_chunk_issuer(chunk)
        assert result is not None
        assert result["category"] == "valuation"


# ── enrich_chunks_with_authority ─────────────────────────────────


class TestEnrichChunksWithAuthority:
    def test_enriches_matching_chunks(self):
        chunks = [
            {"title": "PwC Audit", "content": "PwC report content"},
            {"title": "Generic", "content": "No issuer here"},
        ]
        enriched, summary = enrich_chunks_with_authority(chunks)
        assert len(enriched) == 2
        assert enriched[0]["issuer_name"] == "PwC"
        assert enriched[0]["issuer_tier"] == "EVIDENCE"
        assert enriched[0]["issuer_category"] == "audit"
        assert enriched[1]["issuer_name"] is None

    def test_summary_contains_categories(self):
        chunks = [
            {"title": "PwC Report", "content": ""},
            {"title": "Deloitte Report", "content": ""},
        ]
        enriched, summary = enrich_chunks_with_authority(chunks)
        assert "audit" in summary
        assert sorted(summary["audit"]) == ["Deloitte", "PwC"]

    def test_empty_chunks_returns_empty(self):
        enriched, summary = enrich_chunks_with_authority([])
        assert enriched == []
        assert summary == {}

    def test_does_not_mutate_original(self):
        original = {"title": "PwC", "content": "PwC stuff"}
        chunks = [original]
        enriched, _ = enrich_chunks_with_authority(chunks)
        assert "issuer_name" not in original
        assert "issuer_name" in enriched[0]
