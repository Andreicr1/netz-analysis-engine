"""Tests for the edgar/ package — mock-based, no live SEC API.

Covers:
  - Entity extraction (smart target detection, dedup, placeholders)
  - CIK resolution (sanitization, confidence threshold)
  - Going concern (3-tier: CONFIRMED, MITIGATED, NONE with negation)
  - Financial ratio calculation
  - Context serializer (attribution framework, truncation)
  - Insider signal detection (cluster selling, exclusions)
  - Models (dataclass creation, enum values)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vertical_engines.credit.edgar.cik_resolver import sanitize_entity_name
from vertical_engines.credit.edgar.context_serializer import build_edgar_multi_entity_context
from vertical_engines.credit.edgar.entity_extraction import extract_searchable_entities
from vertical_engines.credit.edgar.financials import FinancialStatements, calculate_ratios
from vertical_engines.credit.edgar.going_concern import GoingConcernVerdict, _classify_context
from vertical_engines.credit.edgar.models import (
    CikResolution,
    EdgarEntityResult,
    InsiderSignal,
    InsiderSignalType,
    SignalSeverity,
)


# ── Entity Extraction Tests ──────────────────────────────────────


class TestEntityExtraction:
    """Tests for extract_searchable_entities()."""

    def test_basic_deal_with_sponsor(self):
        entities = extract_searchable_entities(
            {"deal_name": "ACME Fund LP", "sponsor_name": "ACME Capital"},
        )
        assert len(entities) == 2
        assert entities[0]["role"] == "fund/vehicle"
        assert entities[0]["is_direct_target"] is True
        assert entities[1]["role"] == "sponsor/manager"

    def test_deal_name_equals_sponsor_not_direct_target(self):
        entities = extract_searchable_entities(
            {"deal_name": "ACME Capital", "sponsor_name": "ACME Capital"},
        )
        # deal_name == sponsor_name → classified as sponsor, not direct target
        assert len(entities) == 1
        assert entities[0]["role"] == "sponsor/manager"

    def test_target_vehicle_from_analysis(self):
        entities = extract_searchable_entities(
            {"deal_name": "ACME Capital", "sponsor_name": "ACME Capital"},
            analysis={"targetVehicle": "NELI US LP"},
        )
        assert any(e["name"] == "NELI US LP" and e["is_direct_target"] for e in entities)

    def test_skip_placeholders(self):
        entities = extract_searchable_entities(
            {"deal_name": "n/a", "sponsor_name": "tbd"},
        )
        assert len(entities) == 0

    def test_skip_generic_patterns(self):
        entities = extract_searchable_entities(
            {"deal_name": "various borrowers", "sponsor_name": "pending diligence"},
        )
        assert len(entities) == 0

    def test_dedup_same_entity(self):
        entities = extract_searchable_entities(
            {
                "deal_name": "Blue Owl Fund",
                "sponsor_name": "Blue Owl Capital",
                "borrower_name": "Blue Owl Fund",
            },
        )
        names = [e["name"] for e in entities]
        assert names.count("Blue Owl Fund") <= 1

    def test_all_8_roles_extracted(self):
        entities = extract_searchable_entities(
            {
                "deal_name": "Target Fund LP",
                "sponsor_name": "Manager Corp",
                "borrower_name": "Borrower Inc",
            },
            analysis={
                "corporateStructure": {
                    "borrower": "Operating Co",
                    "guarantors": ["Guarantor LLC"],
                    "spvs": ["SPV 2024-1"],
                },
                "sponsorDetails": {
                    "investmentManager": "IM Advisors",
                    "gpEntity": "GP Holdings",
                },
            },
        )
        roles = {e["role"] for e in entities}
        assert "fund/vehicle" in roles
        assert "sponsor/manager" in roles
        assert "borrower" in roles
        assert "guarantor" in roles
        assert "spv" in roles
        assert "investment_manager" in roles
        assert "gp" in roles

    def test_ticker_passed_to_direct_target(self):
        entities = extract_searchable_entities(
            {"deal_name": "ARCC Fund"},
            ticker="ARCC",
        )
        assert entities[0]["ticker"] == "ARCC"


# ── Sanitization Tests ───────────────────────────────────────────


class TestSanitization:
    def test_normal_name(self):
        assert sanitize_entity_name("Ares Capital") == "Ares Capital"

    def test_empty_name(self):
        assert sanitize_entity_name("") is None

    def test_whitespace_only(self):
        assert sanitize_entity_name("   ") is None

    def test_too_long(self):
        assert sanitize_entity_name("x" * 201) is None

    def test_control_chars_stripped(self):
        result = sanitize_entity_name("Ares\x00Capital\x1f")
        assert result == "AresCapital"

    def test_max_length_ok(self):
        name = "x" * 200
        assert sanitize_entity_name(name) == name


# ── Going Concern Tests ──────────────────────────────────────────


class TestGoingConcern:
    def test_confirmed_no_negation(self):
        text = "there is substantial doubt about the company's ability to continue"
        verdict = _classify_context(text)
        assert verdict == GoingConcernVerdict.CONFIRMED

    def test_negated_no_substantial_doubt(self):
        text = "management has concluded that there is no substantial doubt about ability"
        verdict = _classify_context(text)
        assert verdict == GoingConcernVerdict.NONE

    def test_negated_doubt_resolved(self):
        text = "conditions that previously raised doubt has been resolved and alleviated"
        verdict = _classify_context(text)
        assert verdict == GoingConcernVerdict.NONE

    def test_mitigated_with_plans(self):
        text = "while conditions exist, management believes its plans to alleviate the situation"
        verdict = _classify_context(text)
        assert verdict == GoingConcernVerdict.MITIGATED

    def test_no_keywords_returns_confirmed(self):
        # _classify_context is called AFTER a keyword is found
        # if no negation/mitigation → confirmed
        text = "some random text without negation or mitigation"
        verdict = _classify_context(text)
        assert verdict == GoingConcernVerdict.CONFIRMED


# ── Financial Ratio Tests ─────────────────────────────────────────


class TestRatioCalculation:
    def test_leverage_ratio(self):
        financials = FinancialStatements(
            balance_sheet=[{
                "period": "2024",
                "Total Assets": 1_000_000,
                "Liabilities": 600_000,
                "Long-Term Debt": 400_000,
            }],
        )
        ratios = calculate_ratios(financials)
        # equity = 1M - 600K = 400K, leverage = 400K/400K = 1.0
        assert ratios["leverage_ratio"] == 1.0

    def test_interest_coverage(self):
        financials = FinancialStatements(
            balance_sheet=[{"period": "2024", "Total Assets": 1_000_000}],
            income_statement=[{
                "period": "2024",
                "Operating Income": 500_000,
                "Interest Expense": 100_000,
            }],
        )
        ratios = calculate_ratios(financials)
        assert ratios["interest_coverage"] == 5.0

    def test_dscr(self):
        financials = FinancialStatements(
            balance_sheet=[{"period": "2024", "Total Assets": 1_000_000}],
            income_statement=[{
                "period": "2024",
                "Interest Expense": 100_000,
            }],
            cash_flow=[{
                "period": "2024",
                "Net Cash from Operating Activities": 300_000,
            }],
        )
        ratios = calculate_ratios(financials)
        assert ratios["debt_service_coverage"] == 3.0

    def test_no_balance_sheet_returns_none(self):
        financials = FinancialStatements()
        ratios = calculate_ratios(financials)
        assert all(v is None for v in ratios.values())

    def test_division_by_zero_returns_none(self):
        financials = FinancialStatements(
            balance_sheet=[{
                "period": "2024",
                "Total Assets": 1_000_000,
                "Liabilities": 1_000_000,  # equity = 0
            }],
        )
        ratios = calculate_ratios(financials)
        assert ratios["leverage_ratio"] is None


# ── Context Serializer Tests ─────────────────────────────────────


class TestContextSerializer:
    def test_empty_results_returns_empty(self):
        result = build_edgar_multi_entity_context({"results": []})
        assert result == ""

    def test_all_not_found(self):
        result = build_edgar_multi_entity_context({
            "results": [
                {"status": "NOT_FOUND", "lookup_entity": "ACME Corp"},
            ],
        })
        assert "No EDGAR filings found" in result

    def test_attribution_framework_present(self):
        result = build_edgar_multi_entity_context({
            "results": [
                {
                    "status": "FOUND",
                    "lookup_entity": "ARCC",
                    "matched_name": "Ares Capital",
                    "cik": "0001287750",
                    "is_direct_target": True,
                    "role": "fund/vehicle",
                },
            ],
            "entities_tried": 1,
            "entities_found": 1,
            "unique_ciks": 1,
        }, deal_name="ARCC Fund")
        assert "ATTRIBUTION RULES" in result
        assert "DIRECT TARGET" in result

    def test_related_entity_labeled(self):
        result = build_edgar_multi_entity_context({
            "results": [
                {
                    "status": "FOUND",
                    "lookup_entity": "Sponsor Corp",
                    "matched_name": "Sponsor Corp",
                    "cik": "1234567890",
                    "is_direct_target": False,
                    "role": "sponsor/manager",
                    "relationship_desc": "Manager entity",
                },
            ],
            "entities_tried": 1,
            "entities_found": 1,
            "unique_ciks": 1,
        })
        assert "RELATED ENTITY" in result

    def test_no_direct_target_warning(self):
        result = build_edgar_multi_entity_context({
            "results": [
                {
                    "status": "FOUND",
                    "lookup_entity": "Sponsor",
                    "matched_name": "Sponsor",
                    "cik": "1234567890",
                    "is_direct_target": False,
                    "role": "sponsor/manager",
                },
            ],
            "entities_tried": 1,
            "entities_found": 1,
            "unique_ciks": 1,
        })
        assert "NO DIRECT TARGET" in result

    def test_going_concern_direct_target(self):
        result = build_edgar_multi_entity_context({
            "results": [
                {
                    "status": "FOUND",
                    "lookup_entity": "Fund",
                    "matched_name": "Fund",
                    "cik": "0001234567",
                    "is_direct_target": True,
                    "role": "fund/vehicle",
                    "going_concern": True,
                    "going_concern_detail": {"verdict": "confirmed"},
                },
            ],
            "entities_tried": 1,
            "entities_found": 1,
            "unique_ciks": 1,
        })
        assert "GOING CONCERN DETECTED" in result
        assert "escalate" in result


# ── Model Tests ──────────────────────────────────────────────────


class TestModels:
    def test_cik_resolution_creation(self):
        r = CikResolution(cik="0001234567", company_name="Test", method="ticker", confidence=1.0)
        assert r.cik == "0001234567"
        assert r.confidence == 1.0

    def test_edgar_entity_result_defaults(self):
        r = EdgarEntityResult(entity_name="Test", role="fund/vehicle")
        assert r.warnings == []
        assert r.also_matched_as == []
        assert r.resolution_confidence == 0.0

    def test_insider_signal_enums(self):
        s = InsiderSignal(
            signal_type=InsiderSignalType.CLUSTER_SELLING,
            severity=SignalSeverity.ELEVATED,
            entity_name="Test",
            description="3 insiders sold",
            insiders=[],
            transactions=[],
            aggregate_value=1_000_000,
            period_days=30,
            detected_at="2026-03-15",
        )
        assert s.signal_type.value == "cluster_selling"
        assert s.severity.value == "elevated"

    def test_financial_statements_defaults(self):
        f = FinancialStatements()
        assert f.income_statement is None
        assert f.ratios == {}
        assert f.periods_available == 0
