"""Smoke tests for Playwright PDF rendering stack."""
from __future__ import annotations

from datetime import date

import pytest


@pytest.mark.asyncio
async def test_html_to_pdf_basic():
    """html_to_pdf returns non-empty bytes for trivial HTML."""
    from vertical_engines.wealth.pdf.html_renderer import html_to_pdf

    pdf = await html_to_pdf("<html><body><h1>Test</h1></body></html>")
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000  # sanity: PDF has content
    assert pdf[:4] == b"%PDF"  # valid PDF magic bytes


def test_svg_performance_chart():
    """performance_line_chart returns valid SVG string."""
    from vertical_engines.wealth.pdf.svg_charts import NavPoint, performance_line_chart

    points = [
        NavPoint(nav_date=date(2025, 1, 1), portfolio_nav=1.0, benchmark_nav=1.0),
        NavPoint(nav_date=date(2025, 6, 1), portfolio_nav=1.08, benchmark_nav=1.05),
        NavPoint(nav_date=date(2026, 1, 1), portfolio_nav=1.15, benchmark_nav=1.10),
    ]
    svg = performance_line_chart(points)
    assert "<svg" in svg
    assert "<polyline" in svg
    assert "xmlns" in svg


def test_svg_performance_chart_empty():
    """performance_line_chart handles empty input."""
    from vertical_engines.wealth.pdf.svg_charts import performance_line_chart

    svg = performance_line_chart([])
    assert "<svg" in svg
    assert "<polyline" not in svg


def test_drawdown_chart():
    """drawdown_chart returns valid SVG with area polygon."""
    from vertical_engines.wealth.pdf.svg_charts import DrawdownPoint, drawdown_chart

    points = [
        DrawdownPoint(dd_date=date(2025, 1, 1), drawdown=0.0),
        DrawdownPoint(dd_date=date(2025, 8, 1), drawdown=-0.0845),
        DrawdownPoint(dd_date=date(2026, 1, 1), drawdown=0.0),
    ]
    svg = drawdown_chart(points)
    assert "<polygon" in svg
    assert "<polyline" in svg
    assert "-8.45%" in svg


def test_drawdown_chart_empty():
    """drawdown_chart handles empty input."""
    from vertical_engines.wealth.pdf.svg_charts import drawdown_chart

    svg = drawdown_chart([])
    assert "<svg" in svg
    assert "<polygon" not in svg


def test_allocation_bars():
    """allocation_bars returns HTML with correct percentages."""
    from vertical_engines.wealth.pdf.svg_charts import allocation_bars

    blocks = [
        {"label": "US Equity", "weight": 0.40, "color": "#185FA5"},
        {"label": "Fixed Income", "weight": 0.30, "color": "#639922"},
    ]
    html = allocation_bars(blocks)
    assert "US Equity" in html
    assert "40%" in html
    assert "30%" in html


def test_long_form_dd_template_renders():
    """render_long_form_dd returns non-empty HTML with correct structure."""
    from vertical_engines.wealth.long_form_report.models import (
        AllocationItem,
        ChapterResult,
        LongFormReportData,
    )
    from vertical_engines.wealth.pdf.templates.long_form_dd import render_long_form_dd

    data = LongFormReportData(
        portfolio_id="test-123",
        portfolio_name="Growth Portfolio",
        profile="growth",
        as_of=date(2026, 3, 28),
        regime="expansion",
        active_return_bps=45.0,
        cvar_95=-0.032,
        avg_expense_ratio=0.85,
        instrument_count=8,
        allocations=[
            AllocationItem(
                block_id="us_equity",
                block_name="US Equity",
                portfolio_weight=0.40,
                benchmark_weight=0.35,
                active_weight=0.05,
            ),
        ],
        chapters=[
            ChapterResult(
                tag="macro_context",
                order=1,
                title="Macro Context",
                content={"global_summary": "Markets remained stable."},
                status="completed",
                confidence=1.0,
            ),
            ChapterResult(
                tag="strategic_allocation",
                order=2,
                title="Strategic Allocation Rationale",
                content={"profile": "growth", "blocks": []},
                status="completed",
            ),
            ChapterResult(tag="portfolio_composition", order=3, title="Portfolio Composition & Changes", content={}),
            ChapterResult(tag="performance_attribution", order=4, title="Performance Attribution", content={}),
            ChapterResult(tag="risk_decomposition", order=5, title="Risk Decomposition", content={}),
            ChapterResult(tag="fee_analysis", order=6, title="Fee Analysis", content={}),
            ChapterResult(tag="per_fund_highlights", order=7, title="Per-Fund Highlights", content={}),
            ChapterResult(tag="forward_outlook", order=8, title="Forward Outlook", content={}),
        ],
    )

    html = render_long_form_dd(data, language="en")
    assert "<!DOCTYPE html>" in html
    assert "Growth Portfolio" in html
    assert "Due Diligence Report" in html
    assert "Macro Context" in html
    assert len(html) > 2000


def test_monthly_client_template_renders():
    """render_monthly_client returns non-empty HTML."""
    from vertical_engines.wealth.monthly_report.models import MonthlyReportData
    from vertical_engines.wealth.pdf.templates.monthly_client import render_monthly_client

    data = MonthlyReportData(
        portfolio_id="test-456",
        portfolio_name="Moderate Portfolio",
        profile="moderate",
        report_month="March 2026",
        as_of=date(2026, 3, 28),
        regime="expansion",
        month_return=0.015,
        ytd_return=0.042,
        inception_return=0.128,
        month_bm_return=0.012,
        ytd_bm_return=0.035,
        inception_bm_return=0.105,
        manager_note="Markets were favorable this month.",
        macro_commentary="The global economy showed resilience.",
        portfolio_activity_intro="We made targeted adjustments.",
        forward_positioning="Looking ahead with cautious optimism.",
    )

    html = render_monthly_client(data, language="en")
    assert "<!DOCTYPE html>" in html
    assert "Moderate Portfolio" in html
    assert "Monthly Portfolio Report" in html
    assert len(html) > 2000


def test_fact_sheet_executive_template_renders():
    """render_fact_sheet_executive returns valid HTML with correct structure."""
    from vertical_engines.wealth.fact_sheet.models import (
        AllocationBlock,
        FactSheetData,
        HoldingRow,
        NavPoint,
        ReturnMetrics,
        RiskMetrics,
    )
    from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
        render_fact_sheet_executive,
    )

    data = FactSheetData(
        portfolio_id=__import__("uuid").uuid4(),
        portfolio_name="Growth Portfolio",
        profile="growth",
        as_of=date(2026, 3, 28),
        inception_date=date(2024, 1, 1),
        returns=ReturnMetrics(mtd=0.015, ytd=0.042, one_year=0.118, since_inception=0.245),
        risk=RiskMetrics(annualized_vol=0.118, sharpe=0.92, max_drawdown=-0.064, cvar_95=-0.032),
        holdings=[
            HoldingRow(fund_name="Vanguard S&P 500 ETF", block_id="us_equity", weight=0.25),
            HoldingRow(fund_name="PIMCO Income Fund", block_id="fixed_income", weight=0.15),
        ],
        allocations=[
            AllocationBlock(block_id="us_equity", weight=0.40),
            AllocationBlock(block_id="fixed_income", weight=0.30),
        ],
        nav_series=[
            NavPoint(nav_date=date(2025, 1, 1), nav=1.0, benchmark_nav=1.0),
            NavPoint(nav_date=date(2026, 3, 1), nav=1.15, benchmark_nav=1.10),
        ],
        benchmark_label="60/40 Composite",
    )

    html = render_fact_sheet_executive(data, language="en")
    assert "<!DOCTYPE html>" in html
    assert "Growth Portfolio" in html
    assert "Executive Summary" in html
    assert "Vanguard S&amp;P 500 ETF" in html
    assert len(html) > 2000


def test_fact_sheet_executive_bilingual():
    """render_fact_sheet_executive supports PT language."""
    from vertical_engines.wealth.fact_sheet.models import FactSheetData
    from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
        render_fact_sheet_executive,
    )

    data = FactSheetData(
        portfolio_id=__import__("uuid").uuid4(),
        portfolio_name="Portfólio Moderado",
        profile="moderate",
        as_of=date(2026, 3, 28),
    )

    html = render_fact_sheet_executive(data, language="pt")
    assert "Resumo Executivo" in html
    assert 'lang="pt"' in html


def test_fact_sheet_institutional_template_renders():
    """render_fact_sheet_institutional returns valid HTML with attribution."""
    from vertical_engines.wealth.fact_sheet.models import (
        AllocationBlock,
        AttributionRow,
        FactSheetData,
        HoldingRow,
        ReturnMetrics,
        RiskMetrics,
        StressRow,
    )
    from vertical_engines.wealth.pdf.templates.fact_sheet_institutional import (
        render_fact_sheet_institutional,
    )

    data = FactSheetData(
        portfolio_id=__import__("uuid").uuid4(),
        portfolio_name="Institutional Portfolio",
        profile="growth",
        as_of=date(2026, 3, 28),
        returns=ReturnMetrics(mtd=0.015, ytd=0.042, one_year=0.118, since_inception=0.245),
        risk=RiskMetrics(annualized_vol=0.118, sharpe=0.92, max_drawdown=-0.064, cvar_95=-0.032),
        holdings=[
            HoldingRow(fund_name="Vanguard S&P 500 ETF", block_id="us_equity", weight=0.25),
        ],
        allocations=[
            AllocationBlock(block_id="us_equity", weight=0.40),
            AllocationBlock(block_id="fixed_income", weight=0.30),
        ],
        attribution=[
            AttributionRow(
                block_name="US Equity",
                allocation_effect=0.0012,
                selection_effect=0.0032,
                interaction_effect=0.0005,
                total_effect=0.0049,
            ),
        ],
        stress=[
            StressRow(
                name="GFC Replay",
                start_date=date(2008, 9, 1),
                end_date=date(2009, 3, 1),
                portfolio_return=-0.284,
                max_drawdown=-0.312,
            ),
        ],
    )

    html = render_fact_sheet_institutional(data, language="en")
    assert "<!DOCTYPE html>" in html
    assert "Institutional Portfolio" in html
    assert "Institutional Report" in html
    assert "US Equity" in html
    assert "GFC Replay" in html
    assert len(html) > 3000


def test_dd_report_template_renders():
    """render_dd_report returns valid HTML with 8 chapters."""
    from vertical_engines.wealth.pdf.templates.dd_report import (
        DDReportPDFData,
        render_dd_report,
    )

    chapters = [
        {
            "chapter_tag": "executive_summary",
            "chapter_order": i + 1,
            "content_md": f"## Chapter {i + 1}\n\nThis is the content for chapter {i + 1}.\n\n"
            f"**Key finding:** The fund demonstrates strong risk-adjusted returns.\n\n"
            f"- Point A: Consistent alpha generation\n"
            f"- Point B: Disciplined risk management",
            "evidence_refs": {"source_1": "SEC Filing 2025-Q4"} if i == 0 else {},
            "quant_data": {"sharpe": "0.92", "cvar_95": "-3.2%"} if i == 3 else {},
            "critic_iterations": 2 if i < 4 else 1,
            "critic_status": "accepted",
        }
        for i in range(8)
    ]

    data = DDReportPDFData(
        fund_name="Vanguard S&P 500 ETF",
        fund_id="test-fund-001",
        as_of=date(2026, 3, 28),
        confidence_score=0.82,
        decision_anchor="approve",
        chapters=chapters,
    )

    html = render_dd_report(data, language="en")
    assert "<!DOCTYPE html>" in html
    assert "Vanguard S&amp;P 500 ETF" in html
    assert "Due Diligence Report" in html
    assert "Chapter 1" in html
    assert "Chapter 8" in html
    assert "82%" in html  # confidence
    assert "APPROVE" in html
    assert len(html) > 5000


def test_dd_report_bilingual():
    """render_dd_report supports PT language."""
    from vertical_engines.wealth.pdf.templates.dd_report import (
        DDReportPDFData,
        render_dd_report,
    )

    data = DDReportPDFData(
        fund_name="Fundo Teste",
        fund_id="test",
        as_of=date(2026, 3, 28),
        confidence_score=0.75,
        decision_anchor="review",
        chapters=[{"chapter_order": 1, "chapter_tag": "exec", "content_md": "Resumo."}],
    )

    html = render_dd_report(data, language="pt")
    assert "Relat\u00f3rio de Due Diligence" in html


def test_content_report_template_renders():
    """render_content_report returns valid HTML for markdown content."""
    from vertical_engines.wealth.pdf.templates.content_report import render_content_report

    content = (
        "## Global Macro Summary\n\n"
        "The global economy continues to expand at a moderate pace, with GDP growth "
        "tracking near 2.3% annualized.\n\n"
        "## Regional Outlook\n\n"
        "- **United States:** Moderate expansion continues\n"
        "- **Europe:** Stabilizing after a challenging 2025\n"
        "- **Asia:** Mixed signals from China and India\n\n"
        "## Key Risks\n\n"
        "Geopolitical tensions remain the primary concern."
    )

    html = render_content_report(
        content,
        title="Investment Outlook",
        language="en",
    )
    assert "<!DOCTYPE html>" in html
    assert "Investment Outlook" in html
    assert "Global Macro Summary" in html
    assert "<strong>United States:</strong>" in html
    assert len(html) > 1000


def test_content_report_with_subtitle():
    """render_content_report includes subtitle when provided."""
    from vertical_engines.wealth.pdf.templates.content_report import render_content_report

    html = render_content_report(
        "## Overview\n\nFund analysis.",
        title="Manager Spotlight",
        subtitle="Vanguard S&P 500 ETF",
        language="en",
    )
    assert "Manager Spotlight" in html
    assert "Vanguard S&amp;P 500 ETF" in html


def test_long_form_report_data_is_frozen():
    """LongFormReportData is immutable (safe across async boundaries)."""
    from vertical_engines.wealth.long_form_report.models import LongFormReportData

    data = LongFormReportData(
        portfolio_id="test",
        portfolio_name="Test",
        profile="growth",
        as_of=date(2026, 1, 1),
        regime="expansion",
    )
    with pytest.raises(AttributeError):
        data.portfolio_name = "Changed"  # type: ignore[misc]


def test_monthly_report_data_is_frozen():
    """MonthlyReportData is immutable."""
    from vertical_engines.wealth.monthly_report.models import MonthlyReportData

    data = MonthlyReportData(
        portfolio_id="test",
        portfolio_name="Test",
        profile="growth",
        report_month="Jan 2026",
        as_of=date(2026, 1, 1),
        regime="expansion",
        month_return=0.01,
        ytd_return=0.01,
        inception_return=0.05,
        month_bm_return=0.008,
        ytd_bm_return=0.008,
        inception_bm_return=0.04,
        manager_note="",
        macro_commentary="",
        portfolio_activity_intro="",
        forward_positioning="",
    )
    with pytest.raises(AttributeError):
        data.portfolio_name = "Changed"  # type: ignore[misc]
