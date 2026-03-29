"""Tests for Fact-Sheet PDF generation — i18n, models, chart builder, renderers.

Smoke tests verify: valid PDF header, minimum page count, content assertions.
Both Portuguese and English are tested with sample portfolio data.
"""

from __future__ import annotations

import uuid
from datetime import date
from io import BytesIO

import pytest

# ── i18n tests ──────────────────────────────────────────────────────────────


class TestI18n:
    """Test bilingual labels and formatting helpers."""

    def test_labels_both_languages_present(self):
        from vertical_engines.wealth.fact_sheet.i18n import LABELS

        assert "pt" in LABELS
        assert "en" in LABELS

    def test_labels_keys_match(self):
        from vertical_engines.wealth.fact_sheet.i18n import LABELS

        pt_keys = set(LABELS["pt"].keys())
        en_keys = set(LABELS["en"].keys())
        assert pt_keys == en_keys, f"Key mismatch: {pt_keys.symmetric_difference(en_keys)}"

    def test_format_date_pt(self):
        from vertical_engines.wealth.fact_sheet.i18n import format_date

        d = date(2026, 3, 15)
        assert format_date(d, "pt") == "15/03/2026"

    def test_format_date_en(self):
        from vertical_engines.wealth.fact_sheet.i18n import format_date

        d = date(2026, 3, 15)
        assert format_date(d, "en") == "03/15/2026"

    def test_format_number_pt(self):
        from vertical_engines.wealth.fact_sheet.i18n import format_number

        assert format_number(1234.56, 2, "pt") == "1.234,56"

    def test_format_number_en(self):
        from vertical_engines.wealth.fact_sheet.i18n import format_number

        assert format_number(1234.56, 2, "en") == "1,234.56"

    def test_format_pct(self):
        from vertical_engines.wealth.fact_sheet.i18n import format_pct

        assert format_pct(12.5, 2, "en") == "12.50%"
        assert format_pct(12.5, 2, "pt") == "12,50%"

    def test_format_number_zero(self):
        from vertical_engines.wealth.fact_sheet.i18n import format_number

        assert format_number(0, 2, "pt") == "0,00"
        assert format_number(0, 2, "en") == "0.00"

    def test_format_number_negative(self):
        from vertical_engines.wealth.fact_sheet.i18n import format_number

        result_pt = format_number(-1234.5, 1, "pt")
        assert "1.234" in result_pt
        assert "," in result_pt


# ── Model tests ─────────────────────────────────────────────────────────────


class TestFactSheetModels:
    """Test frozen dataclasses."""

    def test_fact_sheet_data_frozen(self):
        from vertical_engines.wealth.fact_sheet.models import FactSheetData

        data = FactSheetData(
            portfolio_id=uuid.uuid4(),
            portfolio_name="Test",
            profile="moderate",
            as_of=date.today(),
        )
        with pytest.raises(AttributeError):
            data.portfolio_name = "Changed"  # type: ignore[misc]

    def test_return_metrics_defaults(self):
        from vertical_engines.wealth.fact_sheet.models import ReturnMetrics

        rm = ReturnMetrics()
        assert rm.mtd is None
        assert rm.is_backtest is False

    def test_risk_metrics_defaults(self):
        from vertical_engines.wealth.fact_sheet.models import RiskMetrics

        rm = RiskMetrics()
        assert rm.sharpe is None
        assert rm.cvar_95 is None

    def test_holding_row_frozen(self):
        from vertical_engines.wealth.fact_sheet.models import HoldingRow

        h = HoldingRow(fund_name="Fund A", block_id="equity", weight=0.3)
        with pytest.raises(AttributeError):
            h.weight = 0.5  # type: ignore[misc]

    def test_stress_row_frozen(self):
        from vertical_engines.wealth.fact_sheet.models import StressRow

        s = StressRow(
            name="2008_gfc",
            start_date=date(2007, 10, 1),
            end_date=date(2009, 3, 31),
            portfolio_return=-15.0,
            max_drawdown=-20.0,
        )
        with pytest.raises(AttributeError):
            s.name = "changed"  # type: ignore[misc]

    def test_nav_point_frozen(self):
        from vertical_engines.wealth.fact_sheet.models import NavPoint

        np_val = NavPoint(nav_date=date.today(), nav=1000.0)
        with pytest.raises(AttributeError):
            np_val.nav = 2000.0  # type: ignore[misc]


# ── Chart builder tests ─────────────────────────────────────────────────────


class TestChartBuilder:
    """Test chart rendering produces valid PNG buffers."""

    def test_render_nav_chart(self):
        from vertical_engines.wealth.fact_sheet.chart_builder import render_nav_chart
        from vertical_engines.wealth.fact_sheet.models import NavPoint

        series = [
            NavPoint(nav_date=date(2025, 1, i + 1), nav=1000 + i * 10)
            for i in range(30)
        ]
        buf = render_nav_chart(series, title="Test NAV")
        assert isinstance(buf, BytesIO)
        header = buf.read(8)
        assert header[:4] == b"\x89PNG"  # Valid PNG

    def test_render_nav_chart_with_benchmark(self):
        from vertical_engines.wealth.fact_sheet.chart_builder import render_nav_chart
        from vertical_engines.wealth.fact_sheet.models import NavPoint

        series = [
            NavPoint(nav_date=date(2025, 1, i + 1), nav=1000 + i * 10, benchmark_nav=1000 + i * 8)
            for i in range(30)
        ]
        buf = render_nav_chart(series, title="NAV vs Bench")
        header = buf.read(8)
        assert header[:4] == b"\x89PNG"

    def test_render_allocation_pie(self):
        from vertical_engines.wealth.fact_sheet.chart_builder import (
            render_allocation_pie,
        )
        from vertical_engines.wealth.fact_sheet.models import AllocationBlock

        allocs = [
            AllocationBlock(block_id="equity_global", weight=0.4),
            AllocationBlock(block_id="fixed_income", weight=0.35),
            AllocationBlock(block_id="alternatives", weight=0.25),
        ]
        buf = render_allocation_pie(allocs, title="Allocation")
        header = buf.read(8)
        assert header[:4] == b"\x89PNG"

    def test_render_regime_overlay(self):
        from vertical_engines.wealth.fact_sheet.chart_builder import (
            render_regime_overlay,
        )
        from vertical_engines.wealth.fact_sheet.models import NavPoint, RegimePoint

        nav = [NavPoint(nav_date=date(2025, 1, i + 1), nav=1000 + i * 5) for i in range(30)]
        regimes = [
            RegimePoint(regime_date=date(2025, 1, 1), regime="expansion"),
            RegimePoint(regime_date=date(2025, 1, 15), regime="contraction"),
        ]
        buf = render_regime_overlay(nav, regimes, title="Regimes")
        header = buf.read(8)
        assert header[:4] == b"\x89PNG"


# ── Renderer tests (smoke tests) ────────────────────────────────────────────


def _sample_data() -> object:
    """Build sample FactSheetData for testing."""
    from vertical_engines.wealth.fact_sheet.models import (
        AllocationBlock,
        AttributionRow,
        FactSheetData,
        HoldingRow,
        ReturnMetrics,
        RiskMetrics,
        StressRow,
    )

    return FactSheetData(
        portfolio_id=uuid.uuid4(),
        portfolio_name="Conservative Portfolio",
        profile="conservative",
        as_of=date(2026, 3, 15),
        inception_date=date(2024, 1, 1),
        returns=ReturnMetrics(
            mtd=0.5, qtd=1.2, ytd=3.5, one_year=8.0, three_year=6.5,
            since_inception=12.0, is_backtest=True, inception_date=date(2024, 1, 1),
        ),
        risk=RiskMetrics(
            annualized_vol=8.5, sharpe=1.2, max_drawdown=-5.3, cvar_95=-3.1,
        ),
        holdings=[
            HoldingRow(fund_name="Global Equity Fund", block_id="equity_global", weight=0.25),
            HoldingRow(fund_name="EM Debt Fund", block_id="fixed_income_em", weight=0.20),
            HoldingRow(fund_name="US Aggregate", block_id="fixed_income_us", weight=0.15),
            HoldingRow(fund_name="Real Estate REIT", block_id="alternatives", weight=0.10),
            HoldingRow(fund_name="Infra Fund", block_id="infrastructure", weight=0.10),
        ],
        allocations=[
            AllocationBlock(block_id="equity_global", weight=0.35),
            AllocationBlock(block_id="fixed_income", weight=0.40),
            AllocationBlock(block_id="alternatives", weight=0.25),
        ],
        attribution=[
            AttributionRow(block_name="Equity Global", allocation_effect=0.3, selection_effect=0.5, interaction_effect=0.1, total_effect=0.9),
            AttributionRow(block_name="Fixed Income", allocation_effect=-0.1, selection_effect=0.2, interaction_effect=0.0, total_effect=0.1),
        ],
        stress=[
            StressRow(name="2008_gfc", start_date=date(2007, 10, 1), end_date=date(2009, 3, 31), portfolio_return=-12.5, max_drawdown=-18.0),
            StressRow(name="2020_covid", start_date=date(2020, 2, 15), end_date=date(2020, 4, 30), portfolio_return=-8.0, max_drawdown=-12.0),
        ],
        benchmark_label="60/40 Composite",
    )


class TestExecutiveRenderer:
    """Smoke tests for executive HTML template renderer (Playwright stack)."""

    def test_render_pt_produces_html(self):
        from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
            render_fact_sheet_executive,
        )

        data = _sample_data()
        html_str = render_fact_sheet_executive(data, language="pt")  # type: ignore[arg-type]
        assert isinstance(html_str, str)
        assert "<!DOCTYPE html>" in html_str or "<html" in html_str

    def test_render_en_produces_html(self):
        from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
            render_fact_sheet_executive,
        )

        data = _sample_data()
        html_str = render_fact_sheet_executive(data, language="en")  # type: ignore[arg-type]
        assert isinstance(html_str, str)
        assert "Conservative Portfolio" in html_str

    def test_holdings_table_present(self):
        from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
            render_fact_sheet_executive,
        )

        data = _sample_data()
        html_str = render_fact_sheet_executive(data, language="en")  # type: ignore[arg-type]
        assert "Global Equity Fund" in html_str
        assert "25.0%" in html_str


class TestInstitutionalRenderer:
    """Smoke tests for institutional HTML template renderer (Playwright stack)."""

    def test_render_pt_produces_html(self):
        from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
            render_fact_sheet_institutional,
        )

        data = _sample_data()
        html_str = render_fact_sheet_institutional(data, language="pt")  # type: ignore[arg-type]
        assert isinstance(html_str, str)
        assert "<!DOCTYPE html>" in html_str or "<html" in html_str

    def test_render_en_produces_html(self):
        from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
            render_fact_sheet_institutional,
        )

        data = _sample_data()
        html_str = render_fact_sheet_institutional(data, language="en")  # type: ignore[arg-type]
        assert isinstance(html_str, str)
        assert "Conservative Portfolio" in html_str

    def test_institutional_has_attribution(self):
        from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
            render_fact_sheet_institutional,
        )

        data = _sample_data()
        html_str = render_fact_sheet_institutional(data, language="en")  # type: ignore[arg-type]
        assert "Equity Global" in html_str

    def test_institutional_has_stress(self):
        from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
            render_fact_sheet_institutional,
        )

        data = _sample_data()
        html_str = render_fact_sheet_institutional(data, language="en")  # type: ignore[arg-type]
        assert "2008" in html_str or "gfc" in html_str.lower()


# ── DD Report PDF tests ─────────────────────────────────────────────────────


class TestDDReportPDF:
    """Smoke tests for DD Report PDF generation."""

    def test_render_valid_pdf_pt(self):
        from ai_engine.pdf.generate_dd_report_pdf import generate_dd_report_pdf

        chapters = [
            {"chapter_tag": "fund_overview", "chapter_order": 1, "content_md": "This is the fund overview."},
            {"chapter_tag": "strategy_analysis", "chapter_order": 2, "content_md": "Strategy analysis content."},
        ]
        buf = generate_dd_report_pdf(
            fund_name="Test Fund Alpha",
            report_id=str(uuid.uuid4()),
            chapters=chapters,
            confidence_score=85.0,
            decision_anchor="INVEST",
            language="pt",
        )
        header = buf.read(5)
        assert header == b"%PDF-"

    def test_render_valid_pdf_en(self):
        from ai_engine.pdf.generate_dd_report_pdf import generate_dd_report_pdf

        chapters = [
            {"chapter_tag": "fund_overview", "chapter_order": 1, "content_md": "Overview."},
        ]
        buf = generate_dd_report_pdf(
            fund_name="Test Fund Beta",
            report_id=str(uuid.uuid4()),
            chapters=chapters,
            language="en",
        )
        header = buf.read(5)
        assert header == b"%PDF-"


# ── Storage routing tests ───────────────────────────────────────────────────


class TestStorageRouting:
    """Test gold_fact_sheet_path and gold_dd_report_path."""

    def test_fact_sheet_path_format(self):
        from ai_engine.pipeline.storage_routing import gold_fact_sheet_path

        org = uuid.uuid4()
        path = gold_fact_sheet_path(
            org_id=org, vertical="wealth", portfolio_id="abc123",
            as_of_date="2026-03-15", language="pt", filename="executive.pdf",
        )
        assert str(org) in path
        assert "wealth" in path
        assert "abc123" in path
        assert "2026-03-15" in path
        assert "pt" in path
        assert "executive.pdf" in path

    def test_dd_report_path_format(self):
        from ai_engine.pipeline.storage_routing import gold_dd_report_path

        org = uuid.uuid4()
        path = gold_dd_report_path(
            org_id=org, vertical="wealth", report_id="rpt123", language="en",
        )
        assert "dd_reports" in path
        assert "en" in path
        assert "report.pdf" in path

    def test_fact_sheet_path_validates_segments(self):
        from ai_engine.pipeline.storage_routing import gold_fact_sheet_path

        with pytest.raises(ValueError):
            gold_fact_sheet_path(
                org_id=uuid.uuid4(), vertical="wealth",
                portfolio_id="../escape", as_of_date="2026-03-15",
                language="pt", filename="exec.pdf",
            )

    def test_fact_sheet_path_validates_vertical(self):
        from ai_engine.pipeline.storage_routing import gold_fact_sheet_path

        with pytest.raises(ValueError):
            gold_fact_sheet_path(
                org_id=uuid.uuid4(), vertical="invalid",
                portfolio_id="abc", as_of_date="2026-03-15",
                language="pt", filename="exec.pdf",
            )
