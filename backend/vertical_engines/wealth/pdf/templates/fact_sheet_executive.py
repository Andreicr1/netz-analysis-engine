"""Fact Sheet Executive HTML template (1-2 page A4, rendered via Playwright).

Receives a ``FactSheetData`` dataclass and returns a self-contained HTML
string ready for ``page.set_content()`` + ``page.pdf()``.

Design: Netz Premium Institutional — Playfair Display headings, Inter body,
navy/slate palette, Tufte tables, area-chart SVG with risk metrics sidebar.

All user-supplied text is escaped via ``html.escape()``.
Bilingual PT/EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
from datetime import date
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
    allocation_bars,
    performance_line_chart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _e(text: Any) -> str:
    if text is None:
        return "&mdash;"
    return html.escape(str(text))


def _pct(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value * 100:+.{decimals}f}%"


def _pct_color(value: float | None) -> str:
    """Institutional palette: dark for positive, burgundy for negative."""
    if value is None:
        return "#94A3B8"
    return "#0F172A" if value >= 0 else "#8B0000"


def _pct_display(value: float | None, *, decimals: int = 2) -> str:
    """Accounting convention: negatives in parentheses."""
    if value is None:
        return "&mdash;"
    pct = value * 100
    if pct < 0:
        return f"({abs(pct):.{decimals}f}%)"
    return f"{pct:+.{decimals}f}%"


def _fmt_number(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value:,.{decimals}f}"


# ---------------------------------------------------------------------------
# CSS — Premium Institutional Design System
# ---------------------------------------------------------------------------

_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@300;400;500;600;700&display=swap');

@page { size: A4; margin: 0; }
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    --navy: #0A192F;
    --navy-light: #0F172A;
    --slate-900: #1E293B;
    --slate-700: #334155;
    --slate-500: #64748B;
    --slate-400: #94A3B8;
    --slate-200: #E2E8F0;
    --slate-100: #F1F5F9;
    --slate-50: #F8FAFC;
    --copper: #B48608;
    --burgundy: #8B0000;
    --white: #FFFFFF;
    --text-primary: #0F172A;
    --text-secondary: #334155;
    --text-muted: #64748B;
}

html, body {
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
    font-size: 10.5px;
    color: var(--text-primary);
    line-height: 1.45;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    font-variant-numeric: tabular-nums;
}

.page {
    width: 210mm; height: 297mm;
    position: relative; overflow: hidden;
    page-break-after: always;
    background: var(--white);
}
.page:last-child { page-break-after: auto; }

/* --- Tufte Tables --- */
table {
    border-collapse: collapse; width: 100%;
    font-variant-numeric: tabular-nums;
}
table.fixed-cols {
    table-layout: fixed;
}
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

/* --- Section headers --- */
.sec-title {
    font-family: 'Inter', sans-serif;
    font-size: 9px; font-weight: 700;
    color: var(--slate-900);
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--slate-200);
}

/* --- Masthead --- */
.masthead {
    background: var(--navy);
    padding: 26px 28px 22px;
    border-bottom: 2px solid var(--copper);
}
.masthead-label {
    font-family: 'Inter', sans-serif;
    font-size: 8px; letter-spacing: 0.16em;
    color: var(--slate-500);
    text-transform: uppercase;
    margin-bottom: 6px;
}
.masthead-name {
    font-family: 'Playfair Display', 'Georgia', serif;
    font-size: 22px; font-weight: 700;
    color: var(--white);
    margin-bottom: 4px;
    letter-spacing: -0.01em;
}
.masthead-meta {
    font-family: 'Inter', sans-serif;
    font-size: 10px; color: var(--slate-400);
    letter-spacing: 0.02em;
}

/* --- KPI strip --- */
.kpi-strip {
    display: flex;
    border-bottom: 1px solid var(--slate-200);
    background: var(--slate-50);
}
.kpi-card {
    flex: 1; text-align: center;
    padding: 12px 6px 10px;
    border-right: 1px solid var(--slate-200);
}
.kpi-card:last-child { border-right: none; }
.kpi-label {
    font-size: 7.5px; color: var(--slate-500);
    text-transform: uppercase; letter-spacing: 0.07em;
    margin-bottom: 3px; font-weight: 500;
}
.kpi-value {
    font-size: 17px; font-weight: 700;
    font-variant-numeric: tabular-nums;
}

/* --- Chart + Risk grid --- */
.chart-risk-grid {
    display: grid;
    grid-template-columns: 3fr 1fr;
    gap: 12px;
    margin: 10px 0 8px;
    height: 210px;
}
.risk-stack {
    display: flex;
    flex-direction: column;
    gap: 0;
    height: 210px;
}
.risk-stack-card {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    background: var(--slate-50);
    border-bottom: 1px solid var(--slate-200);
    text-align: center;
}
.risk-stack-card:last-child { border-bottom: none; }
.risk-stack-label {
    font-size: 7px; color: var(--slate-500);
    text-transform: uppercase; letter-spacing: 0.06em;
    margin-bottom: 2px; font-weight: 500;
}
.risk-stack-value {
    font-size: 15px; font-weight: 700;
    font-variant-numeric: tabular-nums;
}

/* --- Footer --- */
.page-footer {
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 10px 28px;
    font-size: 7px; color: var(--slate-400);
    border-top: 1px solid var(--slate-200);
    display: flex; justify-content: space-between;
    align-items: flex-end;
    line-height: 1.4;
}
.page-footer .backtest-note { color: var(--copper); font-weight: 500; }
"""


# ---------------------------------------------------------------------------
# Page footer
# ---------------------------------------------------------------------------


def _page_footer(
    as_of: date,
    page: int,
    total: int,
    labels: dict[str, str],
    *,
    backtest: bool = False,
) -> str:
    bt = (
        f' <span class="backtest-note">*{_e(labels["backtest_note"])}</span>'
        if backtest
        else ""
    )
    return (
        f'<div class="page-footer">'
        f"<span>{_e(labels['disclaimer'])}{bt}</span>"
        f"<span>p.&nbsp;{page}/{total}</span>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------------------


def _kpi_card(label: str, value: float | None) -> str:
    color = _pct_color(value)
    display = _pct_display(value) if value is not None else "&mdash;"
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{_e(label)}</div>'
        f'<div class="kpi-value" style="color:{color}">{display}</div>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Chart + Risk metrics (75/25 architectural block)
# ---------------------------------------------------------------------------


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
        return si  # < 1 year: show total return as-is
    return (1 + si) ** (1 / years) - 1


def _chart_risk_block(data: FactSheetData, labels: dict[str, str]) -> str:
    """Render chart (75%) + stacked risk metrics (25%) side by side."""
    svg_points = _to_svg_nav(data)
    chart_svg = performance_line_chart(svg_points, width=500, height=210)

    legend = (
        '<div style="display:flex;gap:16px;margin:5px 0 0;font-size:8px;'
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

    # Risk metrics: Annualized Return, Sharpe, Annualized Vol, Max Drawdown
    ann_ret = _annualized_return(data)
    risk_items = [
        (labels["annualized_return"], ann_ret, lambda v: _pct_display(v), False),
        (labels["sharpe"], data.risk.sharpe, lambda v: f"{v:.2f}", False),
        (labels["annualized_vol"], data.risk.annualized_vol, lambda v: f"{v * 100:.1f}%", False),
        (labels["max_drawdown"], data.risk.max_drawdown, lambda v: f"({abs(v) * 100:.2f}%)", True),
    ]
    risk_cards = ""
    for label, val, fmt, is_neg in risk_items:
        display = fmt(val) if val is not None else "&mdash;"
        color = "var(--burgundy)" if is_neg and val is not None else "var(--text-primary)"
        risk_cards += (
            f'<div class="risk-stack-card">'
            f'<div class="risk-stack-label">{_e(label)}</div>'
            f'<div class="risk-stack-value" style="color:{color}">{display}</div>'
            f"</div>"
        )

    if not svg_points:
        return ""

    return (
        f'<div class="chart-risk-grid">'
        f"<div>{chart_svg}{legend}</div>"
        f'<div class="risk-stack">{risk_cards}</div>'
        f"</div>"
    )


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

    # Fixed-width header: first col wider, rest equal
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
            f'<td style="text-align:right;color:{color};font-weight:600;'
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
# Holdings table (strategy, not block)
# ---------------------------------------------------------------------------


def _holdings_table(
    holdings: list[Any],
    labels: dict[str, str],
    *,
    limit: int | None = None,
) -> str:
    items = holdings[:limit] if limit else holdings
    rows = ""
    for h in items:
        rows += (
            f"<tr>"
            f'<td style="color:var(--text-primary);font-weight:500">{_e(h.fund_name)}</td>'
            f'<td style="color:var(--slate-500)">{_e(fmt_strategy(h.block_id))}</td>'
            f'<td style="text-align:right;font-weight:600;color:var(--text-primary);'
            f'font-variant-numeric:tabular-nums">{h.weight * 100:.1f}%</td>'
            f"</tr>"
        )
    return (
        f'<table class="fixed-cols"><thead><tr>'
        f'<th style="width:50%">{_e(labels["fund_name"])}</th>'
        f'<th style="width:30%">{_e(labels["strategy"])}</th>'
        f'<th style="text-align:right;width:20%">{_e(labels["weight"])}</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Build NAV series for SVG charts
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


# ---------------------------------------------------------------------------
# Allocation colors — institutional palette
# ---------------------------------------------------------------------------

_ALLOC_COLORS = [
    "#0A192F", "#1E3A5F", "#2D5F8A", "#3D7CB5",
    "#64748B", "#8B7355", "#4A6741", "#6B5B73",
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


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _page1(data: FactSheetData, labels: dict[str, str], language: Language) -> str:
    # Masthead
    header = (
        f'<div class="masthead">'
        f'<div class="masthead-label">'
        f'{_e(labels["report_title_executive"])} &middot; FACT SHEET</div>'
        f'<div class="masthead-name">{_e(data.portfolio_name)}</div>'
        f'<div class="masthead-meta">'
        f'{_e(labels["as_of"])} {format_date(data.as_of, language)}'
        f' &nbsp;&bull;&nbsp; {_e(labels["profile"])}: {_e(data.profile.title())}'
        f"</div></div>"
    )

    # Chart (75%) + Risk metrics (25%) — architectural block
    chart_risk = _chart_risk_block(data, labels)

    # Returns table
    returns_html = _returns_table(data, labels)

    # Manager commentary — first page, right after returns
    commentary = ""
    if data.manager_commentary:
        commentary = (
            f'<div style="margin:10px 0 12px">'
            f'<div class="sec-title">{_e(labels["manager_commentary"])}</div>'
            f'<p style="font-size:9.5px;line-height:1.6;color:var(--text-secondary);'
            f'font-style:italic">{_e(data.manager_commentary)}</p></div>'
        )

    # 2-column: allocation + top holdings
    alloc_html = allocation_bars(_alloc_blocks(data), width=195)
    top_8 = _holdings_table(data.holdings, labels, limit=8)

    grid = (
        f'<div style="display:grid;grid-template-columns:210px 1fr;gap:20px;margin:10px 0">'
        f"<div>"
        f'<div class="sec-title">{_e(labels["allocation"])}</div>'
        f"{alloc_html}</div>"
        f"<div>"
        f'<div class="sec-title">{_e(labels["top_holdings"])}</div>'
        f"{top_8}</div>"
        f"</div>"
    )

    total_pages = 2 if len(data.holdings) > 8 else 1

    return (
        f'<div class="page">'
        f"{header}"
        f'<div style="padding:0 28px">'
        f"{chart_risk}"
        f'<div style="margin:8px 0">{returns_html}</div>'
        f"{commentary}"
        f"{grid}"
        f"</div>"
        f"{_page_footer(data.as_of, 1, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page2(data: FactSheetData, labels: dict[str, str], language: Language) -> str:
    """Page 2: continuation holdings + backtest note."""
    remaining = data.holdings[8:]
    if not remaining:
        return ""

    table = _holdings_table(remaining, labels)

    backtest_note = ""
    if data.returns.is_backtest:
        backtest_note = (
            f'<div style="margin-top:14px;padding:10px 14px;background:var(--slate-50);'
            f"border-left:2px solid var(--copper);"
            f'font-size:9px;color:var(--slate-700);line-height:1.5">'
            f"{_e(labels['backtest_note'])}</div>"
        )

    return (
        f'<div class="page">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:16px 28px 12px;border-bottom:1px solid var(--slate-200);margin-bottom:14px">'
        f'<span style="font-family:\'Playfair Display\',serif;font-size:13px;'
        f'font-weight:600;color:var(--text-primary)">{_e(data.portfolio_name)}</span>'
        f'<span style="font-size:8px;color:var(--slate-400)">p.&nbsp;2/2</span>'
        f"</div>"
        f'<div style="padding:0 28px">'
        f'<div class="sec-title">{_e(labels["top_holdings"])} ({_e(labels["weight"])})</div>'
        f"{table}"
        f"{backtest_note}"
        f"</div>"
        f"{_page_footer(data.as_of, 2, 2, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


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
