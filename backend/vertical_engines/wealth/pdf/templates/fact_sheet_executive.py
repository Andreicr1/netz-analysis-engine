"""Fact Sheet Executive HTML template — Netz Premium Institutional System Design Doctrine.

1-2 page A4 Executive Summary with:

- **Cover header**: Navy strip with Playfair Display portfolio name, copper
  accent rule, metadata line. Compact — not full-page (executive is condensed).
- **Performance section**: 70/30 manuscript sidenote layout — KPI strip,
  performance chart, returns table in main; annualized metrics with sparklines
  + benchmark label in margin.
- **Composition section**: Allocation bars + top holdings in main; risk metrics
  in margin. Page 2 if holdings overflow.

Shares the DD Report design system verbatim: CSS variables, typography,
page headers, 70/30 sidenote layout, margin metrics, Tufte tables,
page footers, and disclaimer.

Rendered via Playwright Chromium ``page.pdf()``.
All user-supplied text escaped via ``html.escape()``.
Bilingual PT / EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
from typing import Any

from vertical_engines.wealth.fact_sheet.i18n import (
    LABELS,
    Language,
    fmt_strategy,
    format_date,
)
from vertical_engines.wealth.fact_sheet.models import FactSheetData
from vertical_engines.wealth.pdf.svg_charts import NavPoint as SvgNavPoint
from vertical_engines.wealth.pdf.svg_charts import (
    performance_line_chart,
    sparkline_svg,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _e(text: Any) -> str:
    if text is None:
        return "&mdash;"
    return html.escape(str(text))


def _pct_display(value: float | None, *, decimals: int = 2) -> str:
    """Accounting convention: negatives in parentheses."""
    if value is None:
        return "&mdash;"
    pct = value * 100
    if pct < 0:
        return f"({abs(pct):.{decimals}f}%)"
    return f"{pct:+.{decimals}f}%"


def _pct_color(value: float | None) -> str:
    if value is None:
        return "#94A3B8"
    return "#0F172A" if value >= 0 else "#8B0000"


# ---------------------------------------------------------------------------
# CSS — Netz Premium Institutional System Design Doctrine
# (verbatim from DD Report + Executive-specific additions)
# ---------------------------------------------------------------------------

_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;1,600&family=Inter:wght@300;400;500;600;700&display=swap');

@page { size: A4; margin: 0; }
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    --navy: #0A192F;
    --navy-light: #0F172A;
    --slate-900: #1E293B;
    --slate-700: #334155;
    --slate-500: #64748B;
    --slate-400: #94A3B8;
    --slate-300: #CBD5E1;
    --slate-200: #E2E8F0;
    --slate-100: #F1F5F9;
    --slate-50:  #F8FAFC;
    --copper: #B48608;
    --copper-light: #D4A017;
    --burgundy: #8B0000;
    --white: #FFFFFF;
    --text-primary: #0F172A;
    --text-secondary: #334155;
    --text-muted: #64748B;
}

html, body {
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
    font-size: 10px; color: var(--text-primary); line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    font-variant-numeric: tabular-nums;
}

/* ── Page shell ── */
.page {
    width: 210mm; height: 297mm;
    position: relative; overflow: hidden;
    page-break-after: always; background: var(--white);
}
.page:last-child { page-break-after: auto; }

/* ══════════════════════  COVER HEADER (compact)  ══════════════════════ */
.cover-hdr {
    background: var(--navy);
    padding: 32px 40px 26px;
}
.cv-label {
    font-size: 7.5px; letter-spacing: 0.18em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 10px;
}
.cv-fund {
    font-family: 'Playfair Display', serif;
    font-size: 26px; font-weight: 700;
    color: var(--white); line-height: 1.15;
    margin-bottom: 8px;
}
.cv-sub {
    font-size: 10px; color: var(--slate-400);
    margin-bottom: 16px; letter-spacing: 0.02em;
}
.cv-rule {
    width: 56px; height: 1.5px;
    background: var(--copper);
}

/* ══════════════════════  CONTENT PAGES  ══════════════════════ */

/* Page header bar */
.ph {
    display: flex; justify-content: space-between; align-items: center;
    padding: 18px 40px 14px;
    border-bottom: 0.75px solid var(--slate-200);
}
.ph-fund {
    font-size: 10px; font-weight: 600;
    color: var(--navy); letter-spacing: 0.01em;
}
.ph-page { font-size: 7.5px; color: var(--slate-400); }

/* Section header (full-width, above the 70/30 split) */
.ch-header {
    margin: 14px 40px 0; padding-bottom: 8px;
    border-bottom: 0.75px solid var(--slate-200);
}
.ch-ord {
    font-size: 7px; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--copper);
    margin-bottom: 3px;
}
.ch-title {
    font-family: 'Playfair Display', serif;
    font-size: 16px; font-weight: 700;
    color: var(--navy); line-height: 1.25;
}

/* 70 / 30 sidenote layout */
.ch-wrap {
    display: flex; gap: 0;
    padding: 12px 40px 0;
}
.ch-main {
    flex: 7; padding-right: 22px;
}
.ch-margin {
    flex: 3; padding-left: 18px;
    border-left: 0.5px solid var(--slate-200);
}

/* ══════════════════════  BODY TYPOGRAPHY  ══════════════════════ */
.bt {
    font-size: 9.5px; line-height: 1.65;
    color: var(--text-secondary); margin: 0 0 6px;
}
.sh {
    font-family: 'Playfair Display', serif;
    font-size: 11px; font-weight: 600;
    color: var(--slate-900); margin: 14px 0 6px;
    padding-bottom: 3px;
    border-bottom: 0.5px solid var(--slate-200);
}

/* ── Margin: evidence block ── */
.mg-ev {
    background: var(--slate-50);
    border-left: 2px solid var(--slate-900);
    padding: 10px 12px; margin-bottom: 14px;
}
.mg-ev-label {
    font-size: 6.5px; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--slate-500); margin-bottom: 6px;
}
.mg-ev-item {
    font-size: 7.5px; line-height: 1.5;
    color: var(--text-secondary); margin-bottom: 2px;
    letter-spacing: 0.015em;
}

/* ── Margin: quant metrics (hairline-separated, no background) ── */
.mg-q {
    display: flex; align-items: center;
    justify-content: space-between;
    padding: 6px 0;
    border-bottom: 0.5px solid var(--slate-200);
}
.mg-q:last-child { border-bottom: none; }
.mg-q-label {
    font-size: 7px; color: var(--slate-500);
    text-transform: uppercase; letter-spacing: 0.05em;
}
.mg-q-right {
    display: flex; align-items: center; gap: 6px;
}
.mg-q-val {
    font-size: 10px; font-weight: 600;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
}

/* ── Page footer ── */
.pf {
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 10px 40px;
    font-size: 7px; color: var(--slate-400);
    border-top: 0.5px solid var(--slate-200);
    display: flex; justify-content: space-between;
    letter-spacing: 0.02em;
}
.pf .backtest-note { color: var(--copper); font-weight: 500; }

/* ── Disclaimer ── */
.disc {
    margin-top: 14px; padding: 14px 0 0;
    border-top: 0.75px solid var(--slate-200);
    font-size: 7.5px; line-height: 1.7;
    color: var(--slate-500);
}
.disc-title {
    font-weight: 700; font-size: 7.5px;
    color: var(--slate-700); text-transform: uppercase;
    letter-spacing: 0.08em; margin-bottom: 6px;
}
.disc p { margin-top: 4px; }

/* ══════════════════════  EXECUTIVE SPECIFICS  ══════════════════════ */

/* KPI strip (4 inline cells) */
.kpi-strip {
    display: flex; margin: 0 0 10px;
}
.kpi-cell {
    flex: 1; text-align: center;
    padding: 8px 6px 6px;
    border-right: 0.5px solid var(--slate-200);
}
.kpi-cell:last-child { border-right: none; }
.kpi-cell-label {
    font-size: 7px; color: var(--slate-500);
    text-transform: uppercase; letter-spacing: 0.07em;
    margin-bottom: 2px; font-weight: 500;
}
.kpi-cell-val {
    font-size: 16px; font-weight: 700;
    font-variant-numeric: tabular-nums;
}
.kpi-cell-sub {
    font-size: 7.5px; color: var(--slate-400);
    font-weight: 400; margin-top: 1px;
}

/* Tufte tables */
table {
    border-collapse: collapse; width: 100%;
    font-variant-numeric: tabular-nums;
}
table.fixed-cols { table-layout: fixed; }
thead th {
    font-family: 'Inter', sans-serif;
    font-size: 7.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--slate-500);
    text-align: left;
    padding: 7px 8px 5px;
    border-bottom: 1.5px solid var(--navy);
    border-top: none;
}
tbody td {
    font-size: 9px; padding: 5px 8px;
    border-bottom: none;
    color: var(--text-secondary);
}
tbody tr:nth-child(even) td {
    background: var(--slate-50);
}
tfoot td {
    font-size: 9px; padding: 6px 8px;
    border-top: 1.5px solid var(--navy);
    font-weight: 700;
    color: var(--text-primary);
}

/* Allocation bar rows */
.alloc-bar-row {
    margin-bottom: 6px;
}
.alloc-bar-header {
    display: flex; justify-content: space-between;
    margin-bottom: 2px;
}
.alloc-bar-label {
    font-size: 9px; color: var(--slate-700);
}
.alloc-bar-weight {
    font-size: 9px; font-weight: 600;
    color: var(--navy);
    font-variant-numeric: tabular-nums;
}
.alloc-bar-track {
    height: 3px; background: var(--slate-100);
    border-radius: 1.5px; overflow: hidden;
}
.alloc-bar-fill {
    height: 3px; border-radius: 1.5px;
}
"""

# ---------------------------------------------------------------------------
# Allocation colors
# ---------------------------------------------------------------------------

_ALLOC_COLORS = [
    "#0A192F", "#1E3A5F", "#2D5F8A", "#3D7CB5",
    "#4A5568", "#8B7355", "#4A6741", "#6B5B73",
]


# ---------------------------------------------------------------------------
# Shared data helpers
# ---------------------------------------------------------------------------


def _to_svg_nav(data: FactSheetData) -> list[SvgNavPoint]:
    return [
        SvgNavPoint(
            nav_date=p.nav_date,
            portfolio_nav=p.nav,
            benchmark_nav=p.benchmark_nav,
        )
        for p in data.nav_series
    ]


def _alloc_blocks(data: FactSheetData) -> list[dict[str, Any]]:
    return [
        {
            "label": fmt_strategy(a.block_id),
            "weight": a.weight,
            "color": _ALLOC_COLORS[i % len(_ALLOC_COLORS)],
        }
        for i, a in enumerate(data.allocations)
    ]


def _annualized_return(data: FactSheetData) -> float | None:
    """Compute annualized return from total since-inception return."""
    si = data.returns.since_inception
    if si is None or data.inception_date is None:
        return si
    days = (data.as_of - data.inception_date).days
    if days <= 0:
        return si
    years = days / 365.25
    if years < 1:
        return si
    return (1 + si) ** (1 / years) - 1


# ---------------------------------------------------------------------------
# Returns table (Tufte, fixed columns)
# ---------------------------------------------------------------------------


def _returns_table(data: FactSheetData, labels: dict[str, str]) -> str:
    periods = [
        (labels["mtd"], data.returns.mtd),
        (labels["qtd"], data.returns.qtd),
        (labels["ytd"], data.returns.ytd),
        (labels["1y"], data.returns.one_year),
        (labels["3y"], data.returns.three_year),
        (labels["since_inception"], data.returns.since_inception),
    ]

    bm = data.benchmark_returns
    bm_vals = [
        bm.mtd if bm else None,
        bm.qtd if bm else None,
        bm.ytd if bm else None,
        bm.one_year if bm else None,
        bm.three_year if bm else None,
        bm.since_inception if bm else None,
    ]

    col_w = "13%"
    headers = "".join(
        f'<th style="text-align:right;width:{col_w}">{_e(lbl)}</th>'
        for lbl, _ in periods
    )

    def _row(name: str, vals: list[float | None]) -> str:
        cells = ""
        for v in vals:
            color = _pct_color(v)
            cells += (
                f'<td style="text-align:right;color:{color};'
                f'font-variant-numeric:tabular-nums">{_pct_display(v)}</td>'
            )
        return f"<tr><td style='font-weight:600;color:var(--text-primary)'>{_e(name)}</td>{cells}</tr>"

    port_row = _row(labels["portfolio"], [v for _, v in periods])
    bm_row = _row("Benchmark", bm_vals)

    active_vals = []
    for (_, pv), bv in zip(periods, bm_vals, strict=True):
        if pv is not None and bv is not None:
            active_vals.append(pv - bv)
        else:
            active_vals.append(None)

    active_cells = ""
    for v in active_vals:
        color = _pct_color(v)
        active_cells += (
            f'<td style="text-align:right;color:{color};font-weight:700;'
            f'font-variant-numeric:tabular-nums">{_pct_display(v)}</td>'
        )
    active_row = (
        f"<td style='font-weight:700;color:var(--text-primary)'>Active</td>"
        f"{active_cells}"
    )

    return (
        f'<table class="fixed-cols"><thead><tr>'
        f'<th style="width:22%">{_e(labels["returns"])}</th>'
        f"{headers}</tr></thead>"
        f"<tbody>{port_row}{bm_row}</tbody>"
        f"<tfoot><tr>{active_row}</tr></tfoot>"
        f"</table>"
    )


# ---------------------------------------------------------------------------
# Holdings table
# ---------------------------------------------------------------------------


def _holdings_table(
    holdings: list[Any],
    labels: dict[str, str],
    *,
    limit: int | None = None,
) -> str:
    items = holdings[:limit] if limit else holdings

    # Detect if any holding has 1Y return from prospectus
    has_returns = any(
        getattr(h, "one_year_return", None) is not None for h in items
    )

    rows = ""
    for h in items:
        one_yr = getattr(h, "one_year_return", None)
        ret_color = "var(--text-primary)" if one_yr is None or one_yr >= 0 else "var(--burgundy, #8B0000)"

        cells = (
            f'<td style="color:var(--text-primary);font-weight:500">{_e(h.fund_name)}</td>'
            f'<td style="color:var(--slate-500)">{_e(fmt_strategy(h.block_id))}</td>'
            f'<td style="text-align:right;font-weight:600;color:var(--text-primary);'
            f'font-variant-numeric:tabular-nums">{h.weight * 100:.1f}%</td>'
        )
        if has_returns:
            cells += (
                f'<td style="text-align:right;color:{ret_color};font-variant-numeric:tabular-nums">'
                f'{"&mdash;" if one_yr is None else f"{one_yr:+.1f}%"}</td>'
            )
        rows += f"<tr>{cells}</tr>"

    if has_returns:
        header = (
            f'<th style="width:42%">{_e(labels["fund_name"])}</th>'
            f'<th style="width:26%">{_e(labels["strategy"])}</th>'
            f'<th style="text-align:right;width:16%">{_e(labels["weight"])}</th>'
            f'<th style="text-align:right;width:16%">1Y Ret.</th>'
        )
    else:
        header = (
            f'<th style="width:50%">{_e(labels["fund_name"])}</th>'
            f'<th style="width:30%">{_e(labels["strategy"])}</th>'
            f'<th style="text-align:right;width:20%">{_e(labels["weight"])}</th>'
        )

    return (
        f'<table class="fixed-cols"><thead><tr>{header}</tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _page1(data: FactSheetData, labels: dict[str, str], language: Language) -> str:
    """Page 1: Cover header + Performance (70/30) + Composition (70/30)."""
    total_pages = 2 if len(data.holdings) > 8 else 1
    parts: list[str] = []

    # ── Cover header (compact navy strip) ──
    parts.append(
        '<div class="cover-hdr">'
        f'<div class="cv-label">'
        f'{_e(labels["report_title_executive"])} &middot; Fact Sheet &middot; Confidential</div>'
        f'<div class="cv-fund">{_e(data.portfolio_name)}</div>'
        f'<div class="cv-sub">'
        f'{_e(labels["as_of"])} {format_date(data.as_of, language)} &middot; '
        f'{_e(labels["profile"])}: {_e(data.profile.title())}</div>'
        '<div class="cv-rule"></div>'
        "</div>"
    )

    # ── Section header ──
    parts.append(
        '<div class="ch-header">'
        '<div class="ch-ord">Performance Overview</div>'
        "</div>"
    )

    # ── 70/30 layout ──
    parts.append('<div class="ch-wrap">')

    # ── Main column (70%) ──
    parts.append('<div class="ch-main">')

    # KPI strip
    bm = data.benchmark_returns
    kpi_items = [
        ("MTD", data.returns.mtd, bm.mtd if bm else None),
        ("QTD", data.returns.qtd, bm.qtd if bm else None),
        ("YTD", data.returns.ytd, bm.ytd if bm else None),
        ("Since Inception", data.returns.since_inception, bm.since_inception if bm else None),
    ]
    kpi_html = '<div class="kpi-strip">'
    for lbl, val, bm_val in kpi_items:
        color = _pct_color(val)
        display = _pct_display(val) if val is not None else "&mdash;"
        bm_sub = ""
        if val is not None and bm_val is not None:
            active = val - bm_val
            bm_sub = f'<div class="kpi-cell-sub">BM {_pct_display(active)}</div>'
        kpi_html += (
            f'<div class="kpi-cell">'
            f'<div class="kpi-cell-label">{_e(lbl)}</div>'
            f'<div class="kpi-cell-val" style="color:{color}">{display}</div>'
            f"{bm_sub}"
            f"</div>"
        )
    kpi_html += "</div>"
    parts.append(kpi_html)

    # Performance chart
    svg_points = _to_svg_nav(data)
    if svg_points:
        chart_svg = performance_line_chart(svg_points, width=410, height=160)
        legend = (
            '<div style="display:flex;gap:16px;margin:3px 0 0;font-size:7.5px;'
            'color:var(--slate-500);font-weight:500">'
            '<span><svg width="18" height="2" style="vertical-align:middle">'
            '<line x1="0" y1="1" x2="18" y2="1" stroke="#0A192F" stroke-width="1.8"/></svg>'
            " Portfolio</span>"
            '<span><svg width="18" height="2" style="vertical-align:middle">'
            '<line x1="0" y1="1" x2="18" y2="1" stroke="#B48608" stroke-width="1" '
            'stroke-dasharray="5 3"/></svg>'
            " Benchmark</span>"
            "</div>"
        )
        parts.append(f'<div style="margin:6px 0 4px">{chart_svg}{legend}</div>')

    # Returns table
    parts.append(f'<div style="margin:6px 0">{_returns_table(data, labels)}</div>')

    # Commentary (if available)
    if data.manager_commentary:
        parts.append(
            f'<p class="bt" style="font-style:italic;margin-top:6px">'
            f"{_e(data.manager_commentary)}</p>"
        )

    # ── Composition section (below performance, still in main column) ──
    blocks = _alloc_blocks(data)
    if blocks:
        parts.append('<h3 class="sh">Strategic Allocation</h3>')
        for b in blocks:
            pct = b["weight"] * 100
            bar_w_pct = max(b["weight"] * 100, 1)
            parts.append(
                f'<div class="alloc-bar-row">'
                f'<div class="alloc-bar-header">'
                f'<span class="alloc-bar-label">{_e(b["label"])}</span>'
                f'<span class="alloc-bar-weight">{pct:g}%</span>'
                f"</div>"
                f'<div class="alloc-bar-track">'
                f'<div class="alloc-bar-fill" style="width:{bar_w_pct:.1f}%;'
                f'background:{b["color"]}"></div>'
                f"</div></div>"
            )

    # Top holdings (limit to 8 on page 1)
    if data.holdings:
        parts.append('<h3 class="sh">Top Holdings</h3>')
        parts.append(_holdings_table(data.holdings, labels, limit=8))

    parts.append("</div>")  # close ch-main

    # ── Margin column (30%) ──
    parts.append('<div class="ch-margin">')

    # Annualized metrics with sparklines
    ann_ret = _annualized_return(data)
    margin_metrics = [
        (labels["annualized_return"], ann_ret, lambda v: _pct_display(v)),
        (labels["sharpe"], data.risk.sharpe, lambda v: f"{v:.2f}"),
        (labels["annualized_vol"], data.risk.annualized_vol, lambda v: f"{v * 100:.1f}%"),
        (labels["max_drawdown"], data.risk.max_drawdown, lambda v: f"({abs(v) * 100:.2f}%)"),
    ]

    nav_vals = [p.nav for p in data.nav_series[-24:]] if data.nav_series else []

    for label, val, fmt in margin_metrics:
        display = fmt(val) if val is not None else "&mdash;"
        color = "var(--burgundy)" if val is not None and val < 0 else "var(--text-primary)"
        spark_html = ""
        if nav_vals and len(nav_vals) >= 2 and label in (labels["annualized_return"], labels["sharpe"]):
            spark_html = sparkline_svg(nav_vals, width=50, height=12)
        parts.append(
            f'<div class="mg-q">'
            f'<div class="mg-q-label">{_e(label)}</div>'
            f'<div class="mg-q-right">'
            f"{spark_html}"
            f'<div class="mg-q-val" style="color:{color}">{display}</div>'
            f"</div></div>"
        )

    # CVaR (if available)
    if data.risk.cvar_95 is not None:
        parts.append(
            '<div style="margin-top:10px;padding-top:8px;'
            'border-top:0.5px solid var(--slate-200)">'
            '<div class="mg-ev">'
            f'<div class="mg-ev-label">{_e(labels["cvar_95"])}</div>'
            f'<div class="mg-ev-item" style="font-weight:600;font-size:9px;'
            f'color:var(--burgundy)">{data.risk.cvar_95 * 100:.2f}%</div>'
            "</div></div>"
        )

    # Benchmark label
    if data.benchmark_label:
        parts.append(
            '<div style="margin-top:10px;padding-top:8px;'
            'border-top:0.5px solid var(--slate-200)">'
            '<div class="mg-ev">'
            '<div class="mg-ev-label">Benchmark</div>'
            f'<div class="mg-ev-item">{_e(data.benchmark_label)}</div>'
            "</div></div>"
        )

    # Disclaimer (on page 1 if single-page)
    if total_pages == 1:
        parts.append(
            '<div class="disc">'
            '<div class="disc-title">Disclaimer</div>'
            f"<p>{_e(labels['disclaimer'])}</p>"
            "</div>"
        )

    parts.append("</div>")  # close ch-margin
    parts.append("</div>")  # close ch-wrap

    # Page footer
    bt = (
        f' <span class="backtest-note">*{_e(labels["backtest_note"])}</span>'
        if data.returns.is_backtest
        else ""
    )
    parts.append(
        f'<div class="pf">'
        f"<span>Confidential &mdash; For authorized recipients only{bt}</span>"
        f"<span>p.&thinsp;1 of {total_pages}</span>"
        f"</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


def _page2(data: FactSheetData, labels: dict[str, str], language: Language) -> str:
    """Page 2: continuation holdings + disclaimer."""
    remaining = data.holdings[8:]
    if not remaining:
        return ""

    parts: list[str] = []

    # Page header bar
    parts.append(
        f'<div class="ph">'
        f'<span class="ph-fund">{_e(data.portfolio_name)}</span>'
        '<span class="ph-page">p.&thinsp;2 of 2</span>'
        "</div>"
    )

    # Section header
    parts.append(
        '<div class="ch-header">'
        f'<div class="ch-ord">{_e(labels["top_holdings"])}</div>'
        '<div class="ch-title">Continued</div>'
        "</div>"
    )

    # Holdings table — full width
    parts.append(
        f'<div style="padding:14px 40px 0">'
        f"{_holdings_table(remaining, labels)}"
    )

    # Backtest note
    if data.returns.is_backtest:
        parts.append(
            '<div class="mg-ev" style="margin-top:14px">'
            '<div class="mg-ev-label">Note</div>'
            f'<div class="mg-ev-item">{_e(labels["backtest_note"])}</div>'
            "</div>"
        )

    # Disclaimer
    parts.append(
        '<div class="disc">'
        '<div class="disc-title">Disclaimer</div>'
        f"<p>{_e(labels['disclaimer'])}</p>"
        "</div>"
    )

    parts.append("</div>")  # close content padding

    # Page footer
    parts.append(
        '<div class="pf">'
        "<span>Confidential &mdash; For authorized recipients only</span>"
        "<span>p.&thinsp;2 of 2</span>"
        "</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_fact_sheet_executive(
    data: FactSheetData,
    *,
    language: Language = "en",
) -> str:
    """Render 1-2 page Executive Fact Sheet as self-contained HTML.

    Parameters
    ----------
    data:
        Frozen ``FactSheetData`` with portfolio returns, risk, holdings, etc.
    language:
        ``"pt"`` or ``"en"`` for bilingual labels and date formatting.

    Returns
    -------
    str
        Complete HTML ready for Playwright PDF rendering.
    """
    labels = LABELS[language]
    page1 = _page1(data, labels, language)
    page2 = _page2(data, labels, language)

    return (
        f"<!DOCTYPE html>"
        f'<html lang="{_e(language)}">'
        f"<head>"
        f'<meta charset="utf-8"/>'
        f"<title>{_e(data.portfolio_name)} &mdash; "
        f"{_e(labels['report_title_executive'])}</title>"
        f"<style>{_CSS}</style>"
        f"</head>"
        f"<body>{page1}{page2}</body>"
        f"</html>"
    )
