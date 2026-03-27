"""Tests for the Unified Fund Catalog — query builder + schemas.

Covers:
- CatalogFilters defaults
- Branch pruning (region/universe filters eliminate branches)
- UNION ALL query generation
- Facet query generation
- DisclosureMatrix correctness per universe
- UnifiedFundItem serialization
- Pydantic schema validation
"""

from __future__ import annotations

import pytest

from app.domains.wealth.queries.catalog_sql import (
    CatalogFilters,
    _private_us_branch,
    _registered_us_branch,
    _ucits_eu_branch,
    build_catalog_facets_query,
    build_catalog_query,
)
from app.domains.wealth.schemas.catalog import (
    CatalogFacetItem,
    CatalogFacets,
    DisclosureMatrix,
    UnifiedCatalogPage,
    UnifiedFundItem,
)


class TestCatalogFilters:
    def test_defaults(self):
        f = CatalogFilters()
        assert f.q is None
        assert f.region is None
        assert f.fund_universe is None
        assert f.fund_type is None
        assert f.aum_min is None
        assert f.has_nav is None
        assert f.sort == "name_asc"
        assert f.page == 1
        assert f.page_size == 50

    def test_frozen(self):
        f = CatalogFilters(q="test")
        with pytest.raises(AttributeError):
            f.q = "changed"  # type: ignore[misc]


class TestBranchPruning:
    """Verify that filters correctly prune irrelevant UNION branches."""

    def test_eu_region_prunes_us_branches(self):
        f = CatalogFilters(region="EU")
        assert _registered_us_branch(f) is None
        assert _private_us_branch(f) is None
        assert _ucits_eu_branch(f) is not None

    def test_us_region_prunes_eu_branch(self):
        f = CatalogFilters(region="US")
        assert _registered_us_branch(f) is not None
        assert _private_us_branch(f) is not None
        assert _ucits_eu_branch(f) is None

    def test_registered_universe_prunes_others(self):
        f = CatalogFilters(fund_universe="registered")
        assert _registered_us_branch(f) is not None
        assert _private_us_branch(f) is None
        assert _ucits_eu_branch(f) is None

    def test_private_universe_prunes_others(self):
        f = CatalogFilters(fund_universe="private")
        assert _registered_us_branch(f) is None
        assert _private_us_branch(f) is not None
        assert _ucits_eu_branch(f) is None

    def test_ucits_universe_prunes_others(self):
        f = CatalogFilters(fund_universe="ucits")
        assert _registered_us_branch(f) is None
        assert _private_us_branch(f) is None
        assert _ucits_eu_branch(f) is not None

    def test_all_universe_keeps_all(self):
        f = CatalogFilters(fund_universe="all")
        assert _registered_us_branch(f) is not None
        assert _private_us_branch(f) is not None
        assert _ucits_eu_branch(f) is not None

    def test_has_nav_true_prunes_private(self):
        """Private funds never have NAV — should be pruned."""
        f = CatalogFilters(has_nav=True)
        assert _private_us_branch(f) is None
        assert _registered_us_branch(f) is not None
        assert _ucits_eu_branch(f) is not None

    def test_aum_min_prunes_ucits(self):
        """ESMA has no AUM data — should be pruned when aum_min is set."""
        f = CatalogFilters(aum_min=1_000_000)
        assert _ucits_eu_branch(f) is None
        assert _registered_us_branch(f) is not None
        assert _private_us_branch(f) is not None

    def test_non_us_domicile_prunes_private(self):
        """Private US funds are always US domicile."""
        f = CatalogFilters(domicile="IE")
        assert _private_us_branch(f) is None

    def test_impossible_filters_returns_none(self):
        """EU region + registered universe = no branches."""
        f = CatalogFilters(region="EU", fund_universe="registered")
        assert build_catalog_query(f) is None


class TestBuildCatalogQuery:
    def test_default_returns_query(self):
        stmt = build_catalog_query(CatalogFilters())
        assert stmt is not None

    def test_all_pruned_returns_none(self):
        f = CatalogFilters(region="EU", fund_universe="private")
        assert build_catalog_query(f) is None

    def test_query_has_pagination(self):
        stmt = build_catalog_query(CatalogFilters(page=3, page_size=25))
        assert stmt is not None
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT" in compiled
        assert "OFFSET" in compiled

    def test_text_search_generates_ilike(self):
        stmt = build_catalog_query(CatalogFilters(q="blackrock"))
        assert stmt is not None
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True})).upper()
        # Default dialect renders ilike as LOWER(...) LIKE LOWER(...);
        # PostgreSQL dialect renders as ILIKE.  Accept either.
        assert "ILIKE" in compiled or "LIKE" in compiled


class TestBuildCatalogFacetsQuery:
    def test_default_returns_query(self):
        stmt = build_catalog_facets_query(CatalogFilters())
        assert stmt is not None

    def test_pruned_returns_none(self):
        f = CatalogFilters(region="EU", fund_universe="registered")
        assert build_catalog_facets_query(f) is None

    def test_facets_group_by(self):
        stmt = build_catalog_facets_query(CatalogFilters())
        assert stmt is not None
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "GROUP BY" in compiled


class TestDisclosureMatrix:
    def test_registered_us_full_disclosure(self):
        d = DisclosureMatrix(
            has_holdings=True,
            has_nav_history=True,
            has_quant_metrics=True,
            has_style_analysis=True,
            has_13f_overlay=True,
            has_peer_analysis=True,
            holdings_source="nport",
            nav_source="yfinance",
            aum_source="nport",
        )
        assert d.has_holdings is True
        assert d.holdings_source == "nport"

    def test_private_us_minimal_disclosure(self):
        d = DisclosureMatrix(
            has_private_fund_data=True,
            aum_source="schedule_d",
        )
        assert d.has_holdings is False
        assert d.has_nav_history is False
        assert d.has_private_fund_data is True
        assert d.aum_source == "schedule_d"

    def test_ucits_eu_nav_only(self):
        d = DisclosureMatrix(
            has_nav_history=True,
            has_quant_metrics=True,
            has_peer_analysis=True,
            nav_source="yfinance",
            aum_source="yfinance",
        )
        assert d.has_holdings is False
        assert d.has_nav_history is True

    def test_default_all_false(self):
        d = DisclosureMatrix()
        assert d.has_holdings is False
        assert d.has_nav_history is False
        assert d.has_quant_metrics is False
        assert d.has_private_fund_data is False
        assert d.has_style_analysis is False
        assert d.has_13f_overlay is False
        assert d.has_peer_analysis is False
        assert d.holdings_source is None
        assert d.nav_source is None
        assert d.aum_source is None


class TestUnifiedFundItem:
    def _make_registered(self, **overrides) -> UnifiedFundItem:
        defaults = dict(
            external_id="0001234567",
            universe="registered_us",
            name="Vanguard 500 Index Fund",
            ticker="VOO",
            isin="US9229087286",
            region="US",
            fund_type="etf",
            domicile="US",
            currency="USD",
            manager_name="Vanguard Group",
            manager_id="105958",
            aum=350_000_000_000,
            inception_date="2010-09-07",
            total_shareholder_accounts=50_000,
            disclosure=DisclosureMatrix(
                has_holdings=True,
                has_nav_history=True,
                has_quant_metrics=True,
                has_style_analysis=True,
                has_13f_overlay=True,
                has_peer_analysis=True,
                holdings_source="nport",
                nav_source="yfinance",
                aum_source="nport",
            ),
        )
        defaults.update(overrides)
        return UnifiedFundItem(**defaults)

    def _make_private(self, **overrides) -> UnifiedFundItem:
        defaults = dict(
            external_id="a1b2c3d4-5678-9abc-def0-123456789abc",
            universe="private_us",
            name="Citadel Wellington Fund",
            region="US",
            fund_type="hedge_fund",
            domicile="US",
            currency="USD",
            manager_name="Citadel Advisors",
            manager_id="148826",
            aum=20_000_000_000,
            investor_count=150,
            disclosure=DisclosureMatrix(
                has_private_fund_data=True,
                aum_source="schedule_d",
            ),
        )
        defaults.update(overrides)
        return UnifiedFundItem(**defaults)

    def _make_ucits(self, **overrides) -> UnifiedFundItem:
        defaults = dict(
            external_id="IE00B4L5Y983",
            universe="ucits_eu",
            name="iShares Core MSCI World UCITS ETF",
            ticker="IWDA.AS",
            isin="IE00B4L5Y983",
            region="EU",
            fund_type="ucits",
            domicile="IE",
            manager_name="BlackRock Asset Management Ireland",
            manager_id="ESM-12345",
            disclosure=DisclosureMatrix(
                has_nav_history=True,
                has_quant_metrics=True,
                has_peer_analysis=True,
                nav_source="yfinance",
                aum_source="yfinance",
            ),
        )
        defaults.update(overrides)
        return UnifiedFundItem(**defaults)

    def test_registered_serialization(self):
        item = self._make_registered()
        data = item.model_dump()
        assert data["universe"] == "registered_us"
        assert data["disclosure"]["has_holdings"] is True
        assert data["disclosure"]["holdings_source"] == "nport"

    def test_private_serialization(self):
        item = self._make_private()
        data = item.model_dump()
        assert data["universe"] == "private_us"
        assert data["disclosure"]["has_holdings"] is False
        assert data["disclosure"]["has_private_fund_data"] is True
        assert data["ticker"] is None
        assert data["isin"] is None
        assert data["investor_count"] == 150

    def test_ucits_serialization(self):
        item = self._make_ucits()
        data = item.model_dump()
        assert data["universe"] == "ucits_eu"
        assert data["disclosure"]["has_nav_history"] is True
        assert data["disclosure"]["has_holdings"] is False
        assert data["aum"] is None

    def test_screening_overlay_nullable(self):
        item = self._make_registered(
            instrument_id="abc123",
            screening_status="PASS",
            screening_score=0.87,
            approval_status="approved",
        )
        assert item.screening_status == "PASS"
        assert item.screening_score == 0.87

    def test_screening_overlay_absent(self):
        item = self._make_private()
        assert item.instrument_id is None
        assert item.screening_status is None
        assert item.screening_score is None


class TestUnifiedCatalogPage:
    def test_empty_page(self):
        page = UnifiedCatalogPage(
            items=[], total=0, page=1, page_size=50, has_next=False,
        )
        assert page.total == 0
        assert page.has_next is False

    def test_page_with_facets(self):
        page = UnifiedCatalogPage(
            items=[],
            total=130_000,
            page=1,
            page_size=50,
            has_next=True,
            facets=CatalogFacets(
                universes=[
                    CatalogFacetItem(value="registered_us", label="US Registered", count=50000),
                    CatalogFacetItem(value="private_us", label="US Private", count=50000),
                    CatalogFacetItem(value="ucits_eu", label="EU UCITS", count=30000),
                ],
                total=130_000,
            ),
        )
        assert page.facets is not None
        assert len(page.facets.universes) == 3
        assert page.facets.total == 130_000


class TestCatalogFacets:
    def test_empty_facets(self):
        f = CatalogFacets(total=0)
        assert f.universes == []
        assert f.regions == []
        assert f.fund_types == []
        assert f.domiciles == []

    def test_facet_item(self):
        item = CatalogFacetItem(value="registered_us", label="US Registered", count=50000)
        assert item.value == "registered_us"
        assert item.label == "US Registered"
        assert item.count == 50000


class TestParseSeriesClassHeader:
    """Test _parse_series_class_header extracts ALL series/classes."""

    SGML_MULTI_CLASS = """\
<SERIES-AND-CLASSES-CONTRACTS-DATA>
<EXISTING-SERIES-AND-CLASSES-CONTRACTS>
<SERIES>
<OWNER-CIK>0000003794
<SERIES-ID>S000027379
<SERIES-NAME>AB Municipal Bond Inflation Strategy
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000082624
<CLASS-CONTRACT-NAME>Class A
<CLASS-CONTRACT-TICKER-SYMBOL>AUNAX
</CLASS-CONTRACT>
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000082625
<CLASS-CONTRACT-NAME>Class C
<CLASS-CONTRACT-TICKER-SYMBOL>AUNCX
</CLASS-CONTRACT>
</SERIES>
<SERIES>
<OWNER-CIK>0000003794
<SERIES-ID>S000027380
<SERIES-NAME>AB Short Duration Income
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000082630
<CLASS-CONTRACT-NAME>Advisor Class
<CLASS-CONTRACT-TICKER-SYMBOL>ADFIX
</CLASS-CONTRACT>
</SERIES>
</EXISTING-SERIES-AND-CLASSES-CONTRACTS>
</SERIES-AND-CLASSES-CONTRACTS-DATA>
"""

    def test_extracts_all_classes(self):
        from app.domains.wealth.workers.nport_fund_discovery import (
            _parse_series_class_header,
        )

        result: dict = {"ticker": None, "series_id": None, "class_id": None}
        _parse_series_class_header(self.SGML_MULTI_CLASS, result)

        classes = result["fund_classes"]
        assert len(classes) == 3

        # First series, two classes
        assert classes[0]["series_id"] == "S000027379"
        assert classes[0]["series_name"] == "AB Municipal Bond Inflation Strategy"
        assert classes[0]["class_id"] == "C000082624"
        assert classes[0]["class_name"] == "Class A"
        assert classes[0]["ticker"] == "AUNAX"

        assert classes[1]["series_id"] == "S000027379"
        assert classes[1]["class_id"] == "C000082625"
        assert classes[1]["class_name"] == "Class C"
        assert classes[1]["ticker"] == "AUNCX"

        # Second series, one class
        assert classes[2]["series_id"] == "S000027380"
        assert classes[2]["series_name"] == "AB Short Duration Income"
        assert classes[2]["class_id"] == "C000082630"
        assert classes[2]["ticker"] == "ADFIX"

    def test_backward_compat_first_ticker(self):
        from app.domains.wealth.workers.nport_fund_discovery import (
            _parse_series_class_header,
        )

        result: dict = {"ticker": None, "series_id": None, "class_id": None}
        _parse_series_class_header(self.SGML_MULTI_CLASS, result)

        assert result["ticker"] == "AUNAX"
        assert result["series_id"] == "S000027379"
        assert result["class_id"] == "C000082624"

    def test_preserves_existing_ticker(self):
        from app.domains.wealth.workers.nport_fund_discovery import (
            _parse_series_class_header,
        )

        result: dict = {"ticker": "EXISTING", "series_id": None, "class_id": None}
        _parse_series_class_header(self.SGML_MULTI_CLASS, result)

        # Should NOT overwrite existing ticker
        assert result["ticker"] == "EXISTING"

    def test_empty_sgml(self):
        from app.domains.wealth.workers.nport_fund_discovery import (
            _parse_series_class_header,
        )

        result: dict = {"ticker": None, "series_id": None, "class_id": None}
        _parse_series_class_header("<html>no series data</html>", result)

        assert result["fund_classes"] == []
        assert result["ticker"] is None

    def test_class_without_ticker(self):
        from app.domains.wealth.workers.nport_fund_discovery import (
            _parse_series_class_header,
        )

        sgml = """\
<SERIES>
<SERIES-ID>S000099999
<SERIES-NAME>Test Fund
<CLASS-CONTRACT>
<CLASS-CONTRACT-ID>C000111111
<CLASS-CONTRACT-NAME>Institutional
</CLASS-CONTRACT>
</SERIES>
"""
        result: dict = {"ticker": None, "series_id": None, "class_id": None}
        _parse_series_class_header(sgml, result)

        assert len(result["fund_classes"]) == 1
        assert result["fund_classes"][0]["ticker"] is None
        assert result["fund_classes"][0]["class_name"] == "Institutional"
        # No ticker to set
        assert result["ticker"] is None


class TestUnifiedFundItemWithClassFields:
    """Test that UnifiedFundItem accepts series/class fields."""

    def test_registered_with_class_info(self):
        item = UnifiedFundItem(
            external_id="0001234567",
            universe="registered_us",
            name="Class A - Vanguard 500 Index Fund",
            ticker="VFIAX",
            region="US",
            fund_type="mutual_fund",
            series_id="S000002956",
            series_name="Vanguard 500 Index Fund",
            class_id="C000007859",
            class_name="Admiral Shares",
            disclosure=DisclosureMatrix(has_holdings=True),
        )
        assert item.series_id == "S000002956"
        assert item.class_name == "Admiral Shares"
        data = item.model_dump()
        assert data["series_id"] == "S000002956"
        assert data["class_id"] == "C000007859"

    def test_private_no_class_info(self):
        item = UnifiedFundItem(
            external_id="abc",
            universe="private_us",
            name="Some Fund",
            region="US",
            fund_type="hedge_fund",
            disclosure=DisclosureMatrix(),
        )
        assert item.series_id is None
        assert item.class_id is None
