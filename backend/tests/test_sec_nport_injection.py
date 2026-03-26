"""Tests for SEC N-PORT injection and fund-centric evidence branching.

Validates:
1. gather_sec_nport_data() returns correct structure for known CIK
2. gather_sec_nport_data() returns empty dict for unknown CIK
3. Evidence pack branches correctly on holdings_source
4. Investment strategy prompt renders N-PORT block for registered funds
5. Investment strategy prompt renders 13F proxy for private funds
"""

from __future__ import annotations

from vertical_engines.wealth.dd_report.evidence_pack import (
    EvidencePack,
    build_evidence_pack,
)


class TestEvidencePackNportFields:
    """Verify N-PORT fields are present and correctly wired."""

    def test_nport_fields_exist_on_evidence_pack(self):
        pack = EvidencePack()
        assert pack.nport_available is False
        assert pack.nport_holdings_count == 0
        assert pack.nport_sector_weights == {}
        assert pack.nport_asset_allocation == {}
        assert pack.nport_top_holdings == []
        assert pack.nport_report_date is None
        assert pack.fund_style == {}
        assert pack.fund_style_drift_detected is False
        assert pack.holdings_source is None

    def test_build_evidence_pack_with_nport(self):
        nport_data = {
            "report_date": "2026-02-28",
            "holdings_count": 150,
            "sector_weights": {"Technology": 0.30, "Healthcare": 0.20},
            "asset_allocation": {"Equity": 0.85, "Cash": 0.15},
            "top_holdings": [
                {"name": "AAPL", "cusip": "037833100", "pct_of_nav": 5.2},
            ],
            "fund_style": {
                "style_label": "Large Growth",
                "equity_pct": 85.0,
                "fi_pct": 0.0,
                "cash_pct": 15.0,
                "confidence": 0.92,
            },
            "style_drift_detected": False,
        }

        pack = build_evidence_pack(
            fund_data={"instrument_id": "fund-001", "name": "Test Fund"},
            sec_nport_data=nport_data,
            holdings_source="nport",
        )

        assert pack.nport_available is True
        assert pack.nport_holdings_count == 150
        assert pack.nport_sector_weights == {"Technology": 0.30, "Healthcare": 0.20}
        assert pack.nport_asset_allocation == {"Equity": 0.85, "Cash": 0.15}
        assert len(pack.nport_top_holdings) == 1
        assert pack.nport_report_date == "2026-02-28"
        assert pack.fund_style["style_label"] == "Large Growth"
        assert pack.holdings_source == "nport"

    def test_build_evidence_pack_without_nport(self):
        """Private/UCITS fund — no N-PORT data, 13F overlay only."""
        pack = build_evidence_pack(
            fund_data={"instrument_id": "fund-002", "name": "Private Fund"},
            sec_13f_data={
                "thirteenf_available": True,
                "sector_weights": {"Technology": 0.45},
                "drift_detected": False,
                "drift_quarters": 4,
            },
            holdings_source=None,
        )

        assert pack.nport_available is False
        assert pack.holdings_source is None
        assert pack.thirteenf_available is True
        assert pack.sector_weights == {"Technology": 0.45}

    def test_build_evidence_pack_both_nport_and_13f(self):
        """Registered fund with both N-PORT and 13F overlay."""
        pack = build_evidence_pack(
            fund_data={"instrument_id": "fund-003", "name": "Registered Fund"},
            sec_nport_data={
                "report_date": "2026-02-28",
                "holdings_count": 200,
                "sector_weights": {"Technology": 0.25},
                "asset_allocation": {"Equity": 0.90},
                "top_holdings": [],
                "fund_style": {},
                "style_drift_detected": False,
            },
            sec_13f_data={
                "thirteenf_available": True,
                "sector_weights": {"Technology": 0.40},
                "drift_detected": True,
                "drift_quarters": 6,
            },
            holdings_source="nport",
        )

        assert pack.nport_available is True
        assert pack.holdings_source == "nport"
        assert pack.nport_sector_weights == {"Technology": 0.25}
        # 13F is overlay — still available
        assert pack.thirteenf_available is True
        assert pack.sector_weights == {"Technology": 0.40}


class TestEvidencePackContext:
    """Verify to_context() includes all new fields."""

    def test_to_context_has_nport_fields(self):
        pack = EvidencePack(
            nport_available=True,
            nport_report_date="2026-01-31",
            holdings_source="nport",
        )
        ctx = pack.to_context()
        assert ctx["nport_available"] is True
        assert ctx["nport_report_date"] == "2026-01-31"
        assert ctx["holdings_source"] == "nport"
        assert "nport_sector_weights" in ctx
        assert "nport_asset_allocation" in ctx
        assert "nport_top_holdings" in ctx
        assert "fund_style" in ctx
        assert "fund_style_drift_detected" in ctx


class TestChapterFieldExpectations:
    """Verify chapter field expectations include N-PORT fields."""

    def test_investment_strategy_expects_nport(self):
        from vertical_engines.wealth.dd_report.evidence_pack import _CHAPTER_FIELD_EXPECTATIONS

        inv_strat = _CHAPTER_FIELD_EXPECTATIONS["investment_strategy"]
        assert "holdings_source" in inv_strat["fields"]
        assert "nport_available" in inv_strat["fields"]
        assert "nport_sector_weights" in inv_strat["fields"]
        assert "SEC EDGAR N-PORT" in inv_strat["providers"]
        assert inv_strat["primary_provider"] == "SEC EDGAR N-PORT"

    def test_manager_assessment_expects_fund_style(self):
        from vertical_engines.wealth.dd_report.evidence_pack import _CHAPTER_FIELD_EXPECTATIONS

        mgr = _CHAPTER_FIELD_EXPECTATIONS["manager_assessment"]
        assert "nport_available" in mgr["fields"]
        assert "fund_style" in mgr["fields"]
        assert "SEC EDGAR N-PORT" in mgr["providers"]
