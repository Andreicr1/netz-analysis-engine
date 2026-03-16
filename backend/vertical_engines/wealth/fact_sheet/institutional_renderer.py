"""Institutional Complete PDF renderer (4-6 pages).

Everything from executive summary PLUS: attribution analysis,
regime overlay, stress scenarios, rebalance history, ESG placeholder,
and regulatory disclaimer.

All text labels come from ``i18n.LABELS[language]``.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import PageBreak, Paragraph, Spacer

from ai_engine.pdf.pdf_base import (
    build_institutional_table,
    build_netz_styles,
    create_netz_document,
    netz_header_footer,
    safe_text,
)
from vertical_engines.wealth.fact_sheet.executive_renderer import (
    _fmt_metric,
    _fmt_return,
)
from vertical_engines.wealth.fact_sheet.i18n import (
    LABELS,
    Language,
    format_date,
    format_pct,
)
from vertical_engines.wealth.fact_sheet.models import FactSheetData


def render_institutional(
    data: FactSheetData,
    *,
    language: Language = "pt",
    nav_chart: BytesIO | None = None,
    allocation_chart: BytesIO | None = None,
    regime_chart: BytesIO | None = None,
) -> BytesIO:
    """Render institutional complete PDF. Returns BytesIO seeked to 0."""
    labels = LABELS[language]
    styles = build_netz_styles()
    buf = BytesIO()
    title = f"{data.portfolio_name} — {labels['report_title_institutional']}"
    doc = create_netz_document(buf, title=title)
    story: list[Any] = []

    usable_w = A4[0] - 30 * mm

    # ── Reuse executive sections ───────────────────────────────────
    # Cover
    from reportlab.platypus import HRFlowable

    from ai_engine.pdf.pdf_base import ORANGE

    story.append(Paragraph(labels["report_title_institutional"], styles["cover_title"]))
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
    story.append(PageBreak())

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

    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════
    # INSTITUTIONAL-ONLY SECTIONS
    # ══════════════════════════════════════════════════════════════

    # ── Attribution analysis ───────────────────────────────────────
    if data.attribution:
        story.append(Paragraph(labels["attribution"], styles["section_heading"]))
        attr_header = [
            labels["block_name"],
            labels["allocation_effect"],
            labels["selection_effect"],
            labels["interaction_effect"],
            labels["total_effect"],
        ]
        attr_rows: list[list[str]] = [attr_header]
        for a in data.attribution:
            attr_rows.append([
                safe_text(a.block_name),
                format_pct(a.allocation_effect, 2, language),
                format_pct(a.selection_effect, 2, language),
                format_pct(a.interaction_effect, 2, language),
                format_pct(a.total_effect, 2, language),
            ])
        col_w = [usable_w * 0.30] + [usable_w * 0.175] * 4
        story.append(build_institutional_table(attr_rows, col_widths=col_w, styles=styles))
        story.append(Spacer(1, 4 * mm))

    # ── Regime overlay chart ───────────────────────────────────────
    if regime_chart:
        story.append(Paragraph(labels["regime_chart_title"], styles["section_heading"]))
        regime_chart.seek(0)
        img = RLImage(regime_chart, width=usable_w, height=usable_w * 0.45)
        story.append(img)
        story.append(Spacer(1, 4 * mm))

    # ── Stress scenarios ───────────────────────────────────────────
    if data.stress:
        story.append(Paragraph(labels["stress_scenarios"], styles["section_heading"]))
        stress_header = [
            labels["scenario"], labels["period"],
            labels["portfolio_return"], labels["max_drawdown"],
        ]
        stress_rows: list[list[str]] = [stress_header]
        for s in data.stress:
            period = f"{format_date(s.start_date, language)} — {format_date(s.end_date, language)}"
            stress_rows.append([
                safe_text(s.name.replace("_", " ").title()),
                period,
                format_pct(s.portfolio_return, 2, language),
                format_pct(s.max_drawdown, 2, language),
            ])
        col_w = [usable_w * 0.25, usable_w * 0.35, usable_w * 0.20, usable_w * 0.20]
        story.append(build_institutional_table(stress_rows, col_widths=col_w, styles=styles))
        story.append(Spacer(1, 4 * mm))

    # ── ESG placeholder ────────────────────────────────────────────
    story.append(Paragraph(labels["esg_section"], styles["section_heading"]))
    story.append(Paragraph(labels["esg_placeholder"], styles["body"]))
    story.append(Spacer(1, 4 * mm))

    # ── Disclaimer ─────────────────────────────────────────────────
    story.append(Paragraph(labels["disclaimer"], styles["disclaimer"]))

    # Build PDF
    def _on_page(canvas: Any, doc_obj: Any) -> None:
        netz_header_footer(
            canvas, doc_obj,
            report_title=title,
            confidentiality=labels["confidential"],
        )

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf
