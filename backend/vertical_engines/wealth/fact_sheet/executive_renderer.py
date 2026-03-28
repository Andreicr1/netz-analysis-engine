"""Executive Summary PDF renderer (1-2 pages).

DEPRECATED: Migrating to Playwright PDF stack (vertical_engines/wealth/pdf/).
This file will be removed after Fact Sheet and content reports are migrated.
Do NOT use for new report types.

Renders a concise fact-sheet with: cover info, NAV chart, returns table,
allocation pie, top holdings, and key risk metrics.

All text labels come from ``i18n.LABELS[language]`` — no hardcoded strings.
Uses ``pdf_base`` building blocks for consistent Netz institutional branding.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Spacer,
)
from reportlab.platypus import Image as RLImage

from ai_engine.pdf.pdf_base import (
    ORANGE,
    build_institutional_table,
    build_netz_styles,
    create_netz_document,
    netz_header_footer,
    safe_text,
)
from vertical_engines.wealth.fact_sheet.i18n import (
    LABELS,
    Language,
    format_date,
    format_pct,
)
from vertical_engines.wealth.fact_sheet.models import FactSheetData


def render_executive(
    data: FactSheetData,
    *,
    language: Language = "pt",
    nav_chart: BytesIO | None = None,
    allocation_chart: BytesIO | None = None,
) -> BytesIO:
    """Render executive summary PDF. Returns BytesIO seeked to 0."""
    labels = LABELS[language]
    styles = build_netz_styles()
    buf = BytesIO()
    doc = create_netz_document(buf, title=f"{data.portfolio_name} — {labels['report_title_executive']}")
    story: list[Any] = []

    usable_w = A4[0] - 30 * mm  # 15mm each side

    # ── Cover section ──────────────────────────────────────────────
    story.append(Paragraph(labels["report_title_executive"], styles["cover_title"]))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="45%", thickness=2, color=ORANGE, spaceAfter=5 * mm, hAlign="CENTER"))
    story.append(Paragraph(safe_text(data.portfolio_name), styles["cover_subtitle"]))
    story.append(Spacer(1, 2 * mm))

    meta_parts = [
        f"{labels['profile']}: {data.profile.title()}",
        f"{labels['as_of']}: {format_date(data.as_of, language)}",
    ]
    story.append(Paragraph(" · ".join(meta_parts), styles["cover_meta"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(labels["confidential"], styles["cover_confidential"]))
    story.append(Spacer(1, 6 * mm))

    # ── NAV chart ──────────────────────────────────────────────────
    if nav_chart:
        nav_chart.seek(0)
        img = RLImage(nav_chart, width=usable_w, height=usable_w * 0.45)
        story.append(img)
        story.append(Spacer(1, 4 * mm))

    # ── Returns table ──────────────────────────────────────────────
    story.append(Paragraph(labels["returns"], styles["section_heading"]))
    returns_header = [
        labels["mtd"], labels["qtd"], labels["ytd"],
        labels["1y"], labels["3y"], labels["since_inception"],
    ]
    r = data.returns
    returns_row = [
        _fmt_return(r.mtd, language), _fmt_return(r.qtd, language),
        _fmt_return(r.ytd, language), _fmt_return(r.one_year, language),
        _fmt_return(r.three_year, language), _fmt_return(r.since_inception, language),
    ]
    returns_data = [returns_header, returns_row]

    if data.benchmark_returns:
        br = data.benchmark_returns
        bench_row = [
            _fmt_return(br.mtd, language), _fmt_return(br.qtd, language),
            _fmt_return(br.ytd, language), _fmt_return(br.one_year, language),
            _fmt_return(br.three_year, language), _fmt_return(br.since_inception, language),
        ]
        returns_data.append(bench_row)

    tbl = build_institutional_table(returns_data, col_widths=[usable_w / 6] * 6, styles=styles)
    story.append(tbl)

    if r.is_backtest:
        story.append(Paragraph(labels["backtest_note"], styles["disclaimer"]))
    story.append(Spacer(1, 4 * mm))

    # ── Allocation pie ─────────────────────────────────────────────
    if allocation_chart:
        story.append(Paragraph(labels["allocation"], styles["section_heading"]))
        allocation_chart.seek(0)
        img = RLImage(allocation_chart, width=usable_w * 0.65, height=usable_w * 0.5)
        story.append(img)
        story.append(Spacer(1, 4 * mm))

    # ── Top holdings ───────────────────────────────────────────────
    if data.holdings:
        story.append(Paragraph(labels["top_holdings"], styles["section_heading"]))
        holdings_header = [labels["fund_name"], labels["block"], labels["weight"]]
        holdings_rows: list[list[str]] = [holdings_header]
        for h in data.holdings[:10]:
            holdings_rows.append([
                safe_text(h.fund_name),
                safe_text(h.block_id.replace("_", " ").title()),
                format_pct(h.weight * 100, 1, language),
            ])
        col_w = [usable_w * 0.55, usable_w * 0.25, usable_w * 0.20]
        story.append(build_institutional_table(holdings_rows, col_widths=col_w, styles=styles))
        story.append(Spacer(1, 4 * mm))

    # ── Risk metrics ───────────────────────────────────────────────
    story.append(Paragraph(labels["risk_metrics"], styles["section_heading"]))
    risk_header = [labels["annualized_vol"], labels["sharpe"], labels["max_drawdown"], labels["cvar_95"]]
    risk_row = [
        _fmt_return(data.risk.annualized_vol, language),
        _fmt_metric(data.risk.sharpe, language),
        _fmt_return(data.risk.max_drawdown, language),
        _fmt_return(data.risk.cvar_95, language),
    ]
    risk_tbl = build_institutional_table([risk_header, risk_row], col_widths=[usable_w / 4] * 4, styles=styles)
    story.append(risk_tbl)
    story.append(Spacer(1, 4 * mm))

    # ── Manager commentary ─────────────────────────────────────────
    if data.manager_commentary:
        story.append(Paragraph(labels["manager_commentary"], styles["section_heading"]))
        story.append(Paragraph(safe_text(data.manager_commentary), styles["body"]))
        story.append(Spacer(1, 4 * mm))

    # ── Disclaimer ─────────────────────────────────────────────────
    story.append(Paragraph(labels["disclaimer"], styles["disclaimer"]))

    # Build PDF
    def _on_page(canvas: Any, doc_obj: Any) -> None:
        netz_header_footer(
            canvas, doc_obj,
            report_title=f"{data.portfolio_name} — {labels['report_title_executive']}",
            confidentiality=labels["confidential"],
        )

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf


def _fmt_return(value: float | None, language: Language) -> str:
    """Format a return/pct value, or em-dash if None."""
    if value is None:
        return "\u2014"
    return format_pct(value, 2, language)


def _fmt_metric(value: float | None, language: Language) -> str:
    """Format a ratio metric (e.g. Sharpe), no % suffix."""
    if value is None:
        return "\u2014"
    from vertical_engines.wealth.fact_sheet.i18n import format_number
    return format_number(value, 2, language)
