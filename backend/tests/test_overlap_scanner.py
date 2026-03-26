"""Tests for the Holdings Overlap Scanner — Sprint 5 (G6.1, G6.2).

Covers:
- Pure math: compute_overlap with various holding configurations
- Breach detection when single CUSIP exceeds limit
- Sector aggregation
- Edge cases: empty holdings, single fund, no overlap
- Floating point precision with pytest.approx
"""

from __future__ import annotations

import uuid

import pytest

from app.domains.wealth.services.holdings_exploder import HoldingRow
from vertical_engines.wealth.monitoring.overlap_scanner import (
    compute_overlap,
)

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

FUND_A = uuid.uuid4()
FUND_B = uuid.uuid4()
FUND_C = uuid.uuid4()


def _h(
    cusip: str,
    fund_id: uuid.UUID,
    fund_weight: float,
    pct_of_fund_nav: float,
    issuer_name: str | None = None,
    sector: str | None = None,
) -> HoldingRow:
    """Shorthand for creating a HoldingRow."""
    return HoldingRow(
        cusip=cusip,
        issuer_name=issuer_name,
        sector=sector,
        fund_instrument_id=fund_id,
        fund_weight=fund_weight,
        pct_of_fund_nav=pct_of_fund_nav,
        weighted_pct=fund_weight * (pct_of_fund_nav / 100.0),
    )


# ═══════════════════════════════════════════════════════════════════
#  Test: empty holdings
# ═══════════════════════════════════════════════════════════════════

class TestEmptyHoldings:
    def test_empty_returns_zero(self) -> None:
        result = compute_overlap([])
        assert result.total_holdings == 0
        assert result.breaches == ()
        assert result.cusip_exposures == ()
        assert result.sector_exposures == ()


# ═══════════════════════════════════════════════════════════════════
#  Test: single fund, no overlap
# ═══════════════════════════════════════════════════════════════════

class TestSingleFundNoOverlap:
    def test_no_breach_below_limit(self) -> None:
        """Fund A = 50% of portfolio. Holds NVDA at 8% of fund NAV.
        Weighted: 0.50 × 0.08 = 0.04 = 4% < 5% limit → no breach."""
        holdings = [
            _h("NVDA_CUSIP", FUND_A, 0.50, 8.0, "NVIDIA Corp", "Technology"),
            _h("AAPL_CUSIP", FUND_A, 0.50, 6.0, "Apple Inc", "Technology"),
            _h("MSFT_CUSIP", FUND_A, 0.50, 5.0, "Microsoft Corp", "Technology"),
        ]
        result = compute_overlap(holdings)
        assert result.total_holdings == 3
        assert len(result.breaches) == 0
        assert len(result.cusip_exposures) == 3

    def test_sector_aggregation(self) -> None:
        """All holdings in Technology sector should aggregate."""
        holdings = [
            _h("NVDA_CUSIP", FUND_A, 0.50, 8.0, "NVIDIA Corp", "Technology"),
            _h("AAPL_CUSIP", FUND_A, 0.50, 6.0, "Apple Inc", "Technology"),
            _h("JPM_CUSIP", FUND_A, 0.50, 4.0, "JPMorgan", "Financials"),
        ]
        result = compute_overlap(holdings)
        assert len(result.sector_exposures) == 2
        tech = next(s for s in result.sector_exposures if s.sector == "Technology")
        assert tech.n_cusips == 2
        # 0.50 × (8 + 6) / 100 = 0.07
        assert tech.total_weighted_pct == pytest.approx(0.07, abs=1e-8)


# ═══════════════════════════════════════════════════════════════════
#  Test: two funds with NVIDIA overlap — G6.1 core scenario
# ═══════════════════════════════════════════════════════════════════

class TestTwoFundsOverlap:
    """Both Fund A and Fund B hold NVIDIA. Combined exposure exceeds 5%."""

    def setup_method(self) -> None:
        # Fund A = 40% of portfolio, NVDA = 8% of fund A NAV
        # Fund B = 35% of portfolio, NVDA = 6% of fund B NAV
        # Weighted NVDA: 0.40 × 0.08 + 0.35 × 0.06 = 0.032 + 0.021 = 0.053 = 5.3%
        self.holdings = [
            _h("NVDA_CUSIP", FUND_A, 0.40, 8.0, "NVIDIA Corp", "Technology"),
            _h("AAPL_CUSIP", FUND_A, 0.40, 5.0, "Apple Inc", "Technology"),
            _h("NVDA_CUSIP", FUND_B, 0.35, 6.0, "NVIDIA Corp", "Technology"),
            _h("MSFT_CUSIP", FUND_B, 0.35, 4.0, "Microsoft", "Technology"),
        ]

    def test_nvidia_breach_detected(self) -> None:
        result = compute_overlap(self.holdings, limit_pct=0.05)
        assert len(result.breaches) == 1
        breach = result.breaches[0]
        assert breach.cusip == "NVDA_CUSIP"
        assert breach.issuer_name == "NVIDIA Corp"
        # 0.40 × 0.08 + 0.35 × 0.06 = 0.053
        assert breach.total_weighted_pct == pytest.approx(0.053, abs=1e-8)
        assert breach.breach is True
        assert len(breach.contributing_funds) == 2

    def test_no_breach_with_higher_limit(self) -> None:
        result = compute_overlap(self.holdings, limit_pct=0.06)
        assert len(result.breaches) == 0

    def test_cusip_exposures_sorted_descending(self) -> None:
        result = compute_overlap(self.holdings, limit_pct=0.05)
        pcts = [e.total_weighted_pct for e in result.cusip_exposures]
        assert pcts == sorted(pcts, reverse=True)


# ═══════════════════════════════════════════════════════════════════
#  Test: three funds, no overlap
# ═══════════════════════════════════════════════════════════════════

class TestNoOverlap:
    def test_no_breaches_when_funds_hold_different_cusips(self) -> None:
        holdings = [
            _h("AAPL_CUSIP", FUND_A, 0.40, 10.0, "Apple", "Technology"),
            _h("MSFT_CUSIP", FUND_B, 0.30, 8.0, "Microsoft", "Technology"),
            _h("JPM_CUSIP", FUND_C, 0.30, 7.0, "JPMorgan", "Financials"),
        ]
        result = compute_overlap(holdings)
        assert len(result.breaches) == 0
        # Even Apple at 40% × 10% = 4% < 5%
        assert len(result.cusip_exposures) == 3


# ═══════════════════════════════════════════════════════════════════
#  Test: floating point precision
# ═══════════════════════════════════════════════════════════════════

class TestFloatingPointPrecision:
    def test_weighted_pct_precision(self) -> None:
        """Verify accumulated weighted_pct maintains precision."""
        # 3 funds each contributing 1/3 of portfolio, each holding CUSIP at 5%
        # Expected: 3 × (1/3 × 0.05) = 0.05 exactly
        holdings = [
            _h("CUSIP_X", FUND_A, 1 / 3, 5.0, "Issuer X", "Technology"),
            _h("CUSIP_X", FUND_B, 1 / 3, 5.0, "Issuer X", "Technology"),
            _h("CUSIP_X", FUND_C, 1 / 3, 5.0, "Issuer X", "Technology"),
        ]
        result = compute_overlap(holdings, limit_pct=0.05)
        total = result.cusip_exposures[0].total_weighted_pct
        # Should be ~0.05 (at the boundary)
        assert total == pytest.approx(0.05, abs=1e-8)

    def test_small_weights_accumulate_correctly(self) -> None:
        """Many small weights should not lose precision."""
        holdings = [
            _h(f"CUSIP_{i}", FUND_A, 0.01, 1.0)
            for i in range(100)
        ]
        result = compute_overlap(holdings)
        total_pct = sum(e.total_weighted_pct for e in result.cusip_exposures)
        # 100 × 0.01 × 0.01 = 0.01
        assert total_pct == pytest.approx(0.01, abs=1e-8)


# ═══════════════════════════════════════════════════════════════════
#  Test: sector exposure with None/Unknown sectors
# ═══════════════════════════════════════════════════════════════════

class TestSectorEdgeCases:
    def test_none_sector_grouped_as_unknown(self) -> None:
        holdings = [
            _h("C1", FUND_A, 0.50, 4.0, sector=None),
            _h("C2", FUND_A, 0.50, 3.0, sector=None),
        ]
        result = compute_overlap(holdings)
        assert len(result.sector_exposures) == 1
        assert result.sector_exposures[0].sector == "Unknown"
        assert result.sector_exposures[0].n_cusips == 2

    def test_mixed_sectors(self) -> None:
        holdings = [
            _h("C1", FUND_A, 0.30, 10.0, sector="Technology"),
            _h("C2", FUND_A, 0.30, 8.0, sector="Financials"),
            _h("C3", FUND_B, 0.40, 5.0, sector="Technology"),
        ]
        result = compute_overlap(holdings)
        sectors = {s.sector: s for s in result.sector_exposures}
        assert "Technology" in sectors
        assert "Financials" in sectors
        # Tech: 0.30 × 0.10 + 0.40 × 0.05 = 0.03 + 0.02 = 0.05
        assert sectors["Technology"].total_weighted_pct == pytest.approx(0.05, abs=1e-8)


# ═══════════════════════════════════════════════════════════════════
#  Test: result structure
# ═══════════════════════════════════════════════════════════════════

class TestResultStructure:
    def test_result_has_correct_limit(self) -> None:
        result = compute_overlap([], limit_pct=0.10)
        assert result.limit_pct == 0.10

    def test_breach_items_are_subset_of_cusip_exposures(self) -> None:
        holdings = [
            _h("HIGH", FUND_A, 0.60, 10.0),  # 0.06 > 0.05
            _h("LOW", FUND_A, 0.60, 2.0),  # 0.012 < 0.05
        ]
        result = compute_overlap(holdings, limit_pct=0.05)
        breach_cusips = {b.cusip for b in result.breaches}
        all_cusips = {e.cusip for e in result.cusip_exposures}
        assert breach_cusips.issubset(all_cusips)
        assert breach_cusips == {"HIGH"}
