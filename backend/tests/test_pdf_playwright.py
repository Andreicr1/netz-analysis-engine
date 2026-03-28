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
