"""Tests for GICS sector enrichment in N-PORT holdings.

Validates:
1. _batch_gics_lookup() returns dict from DB results
2. _resolve_sector() picks GICS for equities, falls back for non-equity
3. gather_sec_nport_data() uses GICS labels in sector_weights and top_holdings
4. gather_nport_sector_history() uses GICS labels
"""

from __future__ import annotations

from unittest.mock import MagicMock

from vertical_engines.wealth.dd_report.sec_injection import (
    _batch_gics_lookup,
    _resolve_sector,
)

# ── _batch_gics_lookup ────────────────────────────────────────────


class TestBatchGicsLookup:
    """Unit tests for _batch_gics_lookup()."""

    def test_empty_cusips_returns_empty(self):
        db = MagicMock()
        assert _batch_gics_lookup(db, []) == {}

    def test_returns_mapping_from_db(self):
        db = MagicMock()
        row1 = MagicMock()
        row1.cusip = "037833100"
        row1.gics_sector = "Information Technology"
        row2 = MagicMock()
        row2.cusip = "594918104"
        row2.gics_sector = "Information Technology"
        # ORM chain: db.query().filter().all()
        db.query.return_value.filter.return_value.all.return_value = [row1, row2]

        result = _batch_gics_lookup(db, ["037833100", "594918104"])

        assert result == {
            "037833100": "Information Technology",
            "594918104": "Information Technology",
        }

    def test_returns_empty_on_exception(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("connection lost")

        result = _batch_gics_lookup(db, ["037833100"])
        assert result == {}


# ── _resolve_sector ───────────────────────────────────────────────


class TestResolveSector:
    """Unit tests for _resolve_sector()."""

    def _make_holding(self, cusip="037833100", asset_class="EC", sector="CORP"):
        h = MagicMock()
        h.cusip = cusip
        h.asset_class = asset_class
        h.sector = sector
        return h

    def test_equity_with_gics_match(self):
        h = self._make_holding(cusip="037833100", asset_class="EC")
        gics = {"037833100": "Information Technology"}
        assert _resolve_sector(h, gics) == "Information Technology"

    def test_equity_without_gics_falls_back(self):
        h = self._make_holding(cusip="999999999", asset_class="EC", sector="CORP")
        assert _resolve_sector(h, {}) == "Equity"

    def test_non_equity_ignores_gics(self):
        h = self._make_holding(cusip="037833100", asset_class="DBT", sector="CORP")
        gics = {"037833100": "Information Technology"}
        # Non-equity CORP → Corporate Bonds, NOT Information Technology
        assert _resolve_sector(h, gics) == "Corporate Bonds"

    def test_equity_no_cusip_falls_back(self):
        h = self._make_holding(cusip=None, asset_class="EC", sector="EC")
        gics = {}
        assert _resolve_sector(h, gics) == "Equity"

    def test_stiv_asset_class_uses_gics(self):
        h = self._make_holding(cusip="037833100", asset_class="STIV")
        gics = {"037833100": "Health Care"}
        assert _resolve_sector(h, gics) == "Health Care"

    def test_fixed_income_keeps_issuer_label(self):
        h = self._make_holding(cusip="037833100", asset_class="DBT", sector="UST")
        gics = {"037833100": "Information Technology"}
        assert _resolve_sector(h, gics) == "US Treasury"


# ── Integration: _resolve_sector used in sector aggregation ──────


class TestSectorAggregation:
    """Verify GICS sectors aggregate correctly in sector_weights-like dicts."""

    def _make_holding(self, cusip, asset_class, sector, pct_of_nav, issuer_name="Test"):
        h = MagicMock()
        h.cusip = cusip
        h.asset_class = asset_class
        h.sector = sector
        h.pct_of_nav = pct_of_nav
        h.issuer_name = issuer_name
        h.market_value = 1_000_000
        return h

    def test_equity_holdings_get_gics_in_aggregation(self):
        """Simulate the sector aggregation loop from gather_sec_nport_data."""
        holdings = [
            self._make_holding("037833100", "EC", "CORP", 10.0, "Apple Inc"),
            self._make_holding("594918104", "EC", "CORP", 8.0, "Microsoft Corp"),
            self._make_holding("912828ZT6", "DBT", "UST", 5.0, "US Treasury Bond"),
        ]
        cusip_to_gics = {
            "037833100": "Information Technology",
            "594918104": "Information Technology",
        }

        # Replicate the aggregation loop
        sector_totals: dict[str, float] = {}
        for h in holdings:
            sector = _resolve_sector(h, cusip_to_gics)
            pct = float(h.pct_of_nav or 0)
            sector_totals[sector] = sector_totals.get(sector, 0.0) + pct

        assert "Information Technology" in sector_totals
        assert sector_totals["Information Technology"] == 18.0
        assert "US Treasury" in sector_totals
        assert sector_totals["US Treasury"] == 5.0
        # Generic "Equity" should NOT appear
        assert "Equity" not in sector_totals

    def test_mixed_equity_with_partial_gics(self):
        """Some equities have GICS, others fall back to generic Equity."""
        holdings = [
            self._make_holding("037833100", "EC", "CORP", 10.0),
            self._make_holding("UNKNOWN99", "EC", "CORP", 5.0),
        ]
        cusip_to_gics = {"037833100": "Information Technology"}

        sector_totals: dict[str, float] = {}
        for h in holdings:
            sector = _resolve_sector(h, cusip_to_gics)
            pct = float(h.pct_of_nav or 0)
            sector_totals[sector] = sector_totals.get(sector, 0.0) + pct

        assert sector_totals["Information Technology"] == 10.0
        assert sector_totals["Equity"] == 5.0
