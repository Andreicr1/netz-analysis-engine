"""Fact Sheet Institutional HTML template — Netz Premium Institutional System Design Doctrine.

4-page A4 Institutional Fact Sheet with:

- **Cover page**: Rich Navy (#0A192F), Playfair Display portfolio name, copper accent
  rule, leader-dot TOC with page references. No confidence/decision badges.
- **Performance page**: 70/30 manuscript sidenote layout — KPI strip, performance
  chart, returns table, portfolio analysis prose in main; annualized metrics with
  sparklines + benchmark label in margin.
- **Composition page**: 70/30 layout — strategic allocation bars + holdings table
  in main; risk profile KPIs + regime/CVaR in margin.
- **Risk & Returns page**: Full-width stress scenarios table + monthly returns matrix.

Shares the DD Report design system verbatim: CSS variables, typography, cover,
chapter headers, 70/30 sidenote layout, margin metrics, Tufte tables, page
headers/footers, and disclaimer.

Rendered via Playwright Chromium ``page.pdf()``.
All user-supplied text escaped via ``html.escape()``.
Bilingual PT / EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
from typing import Any

from vertical_engines.wealth.fact_sheet.i18n import (
    LABELS,
    MONTHS_SHORT,
    Language,
    fmt_strategy,
    format_date,
)
from vertical_engines.wealth.fact_sheet.models import FactSheetData
from vertical_engines.wealth.pdf.svg_charts import NavPoint as SvgNavPoint
from vertical_engines.wealth.pdf.svg_charts import (
    RegimeSpan,
    performance_line_chart,
    sparkline_svg,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REGIME_LABELS: dict[str, str] = {
    "expansion": "Expansion",
    "contraction": "Contraction",
    "crisis": "Crisis",
    "risk_off": "Risk-Off",
}

_REGIME_DOT_COLORS: dict[str, str] = {
    "expansion": "#64748B",
    "contraction": "#B48608",
    "crisis": "#8B0000",
    "risk_off": "#D4A017",
}


def _e(text: Any) -> str:
    if text is None:
        return "&mdash;"
    return html.escape(str(text))


def _pct(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value * 100:+.{decimals}f}%"


def _pct_display(value: float | None, *, decimals: int = 2) -> str:
    """Accounting convention: negatives in parentheses."""
    if value is None:
        return "&mdash;"
    pct = value * 100
    if pct < 0:
        return f"({abs(pct):.{decimals}f}%)"
    return f"{pct:+.{decimals}f}%"


def _pct_unsigned(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value * 100:.{decimals}f}%"


def _pct_color(value: float | None) -> str:
    if value is None:
        return "#94A3B8"
    return "#0F172A" if value >= 0 else "#8B0000"


# ---------------------------------------------------------------------------
# CSS — Netz Premium Institutional System Design Doctrine
# (verbatim from DD Report + Fact Sheet–specific additions)
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

/* ══════════════════════  COVER  ══════════════════════ */
.cover {
    background: var(--navy); height: 100%;
    padding: 52px 48px; display: flex; flex-direction: column;
}
.cv-label {
    font-size: 7.5px; letter-spacing: 0.18em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 32px;
}
.cv-fund {
    font-family: 'Playfair Display', serif;
    font-size: 30px; font-weight: 700;
    color: var(--white); line-height: 1.15;
    margin-bottom: 10px;
}
.cv-sub {
    font-size: 11px; color: var(--slate-400);
    margin-bottom: 28px; letter-spacing: 0.02em;
}
.cv-rule {
    width: 56px; height: 1.5px;
    background: var(--copper); margin-bottom: 32px;
}

/* Cover — TOC */
.toc-label {
    font-size: 7px; letter-spacing: 0.14em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 14px;
}
.toc-row {
    display: flex; align-items: baseline; padding: 6px 0;
}
.toc-num {
    font-size: 9px; color: var(--copper);
    font-weight: 600; width: 22px; flex-shrink: 0;
}
.toc-title { font-size: 10px; color: var(--slate-300); }
.toc-dots {
    flex: 1; border-bottom: 0.5px dotted rgba(255,255,255,0.15);
    margin: 0 8px; min-width: 20px;
    position: relative; top: -3px;
}
.toc-page {
    font-size: 8.5px; color: var(--slate-500);
    font-variant-numeric: tabular-nums;
}
.cv-footer { font-size: 7.5px; color: rgba(255,255,255,0.25); }

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
    margin: 18px 40px 0; padding-bottom: 10px;
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
    padding: 14px 40px 0;
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
.bl {
    margin: 6px 0; padding-left: 16px;
    font-size: 9.5px; line-height: 1.65;
    color: var(--text-secondary);
}
.bl li { margin-bottom: 3px; }
.mh {
    font-family: 'Playfair Display', serif;
    font-size: 12.5px; font-weight: 700;
    color: var(--navy); margin: 18px 0 8px;
}
.sh {
    font-family: 'Playfair Display', serif;
    font-size: 11px; font-weight: 600;
    color: var(--slate-900); margin: 14px 0 6px;
    padding-bottom: 3px;
    border-bottom: 0.5px solid var(--slate-200);
}
.v-space { height: 8px; }

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
    margin-top: 18px; padding: 18px 0 0;
    border-top: 0.75px solid var(--slate-200);
    font-size: 7.5px; line-height: 1.7;
    color: var(--slate-500);
}
.disc-title {
    font-weight: 700; font-size: 7.5px;
    color: var(--slate-700); text-transform: uppercase;
    letter-spacing: 0.08em; margin-bottom: 8px;
}
.disc p { margin-top: 5px; }

/* ══════════════════════  FACT SHEET SPECIFICS  ══════════════════════ */

/* KPI strip (4 inline cells — page 2) */
.kpi-strip {
    display: flex; margin: 0 0 14px;
}
.kpi-cell {
    flex: 1; text-align: center;
    padding: 10px 6px 8px;
    border-right: 0.5px solid var(--slate-200);
}
.kpi-cell:last-child { border-right: none; }
.kpi-cell-label {
    font-size: 7px; color: var(--slate-500);
    text-transform: uppercase; letter-spacing: 0.07em;
    margin-bottom: 3px; font-weight: 500;
}
.kpi-cell-val {
    font-size: 18px; font-weight: 700;
    font-variant-numeric: tabular-nums;
}
.kpi-cell-sub {
    font-size: 8px; color: var(--slate-400);
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

/* Monthly returns matrix */
table.matrix {
    table-layout: fixed;
    font-size: 7.5px;
}
table.matrix thead th {
    font-size: 7px; padding: 5px 3px;
    text-align: center;
    border-bottom: 1.5px solid var(--navy);
}
table.matrix thead th:first-child {
    text-align: left; width: 36px;
}
table.matrix thead th:last-child {
    border-left: 1px solid var(--slate-200);
    font-weight: 700;
}
table.matrix tbody td {
    font-size: 7.5px; padding: 4px 3px;
    text-align: center;
    color: var(--text-secondary);
    border-bottom: none;
}
table.matrix tbody td:first-child {
    text-align: left; font-weight: 700;
    color: var(--text-primary);
}
table.matrix tbody td:last-child {
    border-left: 1px solid var(--slate-200);
    font-weight: 600;
    color: var(--text-primary);
}
table.matrix tbody tr:nth-child(even) td {
    background: var(--slate-50);
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
    font-size: 10px; color: var(--slate-700);
}
.alloc-bar-weight {
    font-size: 10px; font-weight: 600;
    color: var(--navy);
    font-variant-numeric: tabular-nums;
}
.alloc-bar-track {
    height: 4px; background: var(--slate-100);
    border-radius: 2px; overflow: hidden;
}
.alloc-bar-fill {
    height: 4px; border-radius: 2px;
}
"""

# ---------------------------------------------------------------------------
# Allocation colors (by asset family)
# ---------------------------------------------------------------------------

_ALLOC_COLORS = [
    "#0A192F", "#1E3A5F", "#2D5F8A", "#3D7CB5",
    "#4A5568", "#8B7355", "#4A6741", "#6B5B73",
]


# ---------------------------------------------------------------------------
# Shared data helpers (reused from old template)
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


def _build_regime_spans(data: FactSheetData) -> list[RegimeSpan]:
    """Convert RegimePoint list to contiguous RegimeSpan list aligned to NAV indices."""
    if not data.regimes or not data.nav_series:
        return []

    nav_dates = [p.nav_date for p in data.nav_series]
    spans: list[RegimeSpan] = []

    for rp in data.regimes:
        idx = min(range(len(nav_dates)), key=lambda i: abs((nav_dates[i] - rp.regime_date).days))
        if rp.regime in ("contraction", "crisis", "risk_off"):
            spans.append(RegimeSpan(
                start_idx=max(0, idx - 1),
                end_idx=min(idx + 1, len(nav_dates) - 1),
                regime=rp.regime,
            ))

    if not spans:
        return []

    merged: list[RegimeSpan] = [spans[0]]
    for s in spans[1:]:
        prev = merged[-1]
        if s.regime == prev.regime and s.start_idx <= prev.end_idx + 2:
            merged[-1] = RegimeSpan(
                start_idx=prev.start_idx, end_idx=s.end_idx, regime=s.regime,
            )
        else:
            merged.append(s)

    return merged


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
    return float((1 + si) ** (1 / years) - 1)


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
    bm_vals: list[float | None] = [
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

    def _row(name: str, vals: list[float | None], *, bold: bool = False) -> str:
        cells = ""
        for v in vals:
            color = _pct_color(v)
            fw = "font-weight:700;" if bold else ""
            cells += (
                f'<td style="text-align:right;color:{color};{fw}'
                f'font-variant-numeric:tabular-nums">{_pct_display(v)}</td>'
            )
        nfw = "font-weight:700" if bold else "font-weight:600"
        return f"<tr><td style='{nfw};color:var(--text-primary)'>{_e(name)}</td>{cells}</tr>"

    port_row = _row(labels["portfolio"], [v for _, v in periods])
    bm_row = _row("Benchmark", bm_vals)

    active_vals: list[float | None] = []
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
# Holdings table (strategy + approach, no fund names)
# ---------------------------------------------------------------------------


def _holdings_table(
    holdings: list[Any],
    labels: dict[str, str],
) -> str:
    # Detect if any holding has prospectus data
    has_returns = any(
        getattr(h, "one_year_return", None) is not None for h in holdings
    )
    has_expense = any(
        getattr(h, "expense_ratio", None) is not None for h in holdings
    )

    rows = ""
    for h in holdings:
        one_yr = getattr(h, "one_year_return", None)
        er = getattr(h, "expense_ratio", None)
        ret_color = "var(--text-primary)" if one_yr is None or one_yr >= 0 else "var(--burgundy, #8B0000)"

        cells = (
            f'<td style="color:var(--text-primary);font-weight:500">'
            f"{_e(fmt_strategy(h.block_id))}</td>"
            f'<td style="color:var(--slate-500)">{_e(h.fund_name)}</td>'
            f'<td style="text-align:right;font-weight:600;color:var(--text-primary);'
            f'font-variant-numeric:tabular-nums">{h.weight * 100:.1f}%</td>'
        )
        if has_returns:
            cells += (
                f'<td style="text-align:right;color:{ret_color};font-variant-numeric:tabular-nums">'
                f'{"&mdash;" if one_yr is None else f"{one_yr:+.1f}%"}</td>'
            )
        if has_expense:
            cells += (
                f'<td style="text-align:right;color:var(--slate-500);font-variant-numeric:tabular-nums">'
                f'{"&mdash;" if er is None else f"{er:.2f}%"}</td>'
            )
        rows += f"<tr>{cells}</tr>"

    # Dynamic header based on available data
    if has_returns and has_expense:
        header = (
            f'<th style="width:28%">{_e(labels["strategy"])}</th>'
            f'<th style="width:32%">{_e(labels["fund_name"])}</th>'
            f'<th style="text-align:right;width:14%">{_e(labels["weight"])}</th>'
            f'<th style="text-align:right;width:14%">1Y Ret.</th>'
            f'<th style="text-align:right;width:12%">ER</th>'
        )
    elif has_returns:
        header = (
            f'<th style="width:30%">{_e(labels["strategy"])}</th>'
            f'<th style="width:36%">{_e(labels["fund_name"])}</th>'
            f'<th style="text-align:right;width:17%">{_e(labels["weight"])}</th>'
            f'<th style="text-align:right;width:17%">1Y Ret.</th>'
        )
    else:
        header = (
            f'<th style="width:35%">{_e(labels["strategy"])}</th>'
            f'<th style="width:45%">{_e(labels["fund_name"])}</th>'
            f'<th style="text-align:right;width:20%">{_e(labels["weight"])}</th>'
        )

    return (
        f'<table class="fixed-cols"><thead><tr>{header}</tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Stress table
# ---------------------------------------------------------------------------


def _stress_table(data: FactSheetData, labels: dict[str, str]) -> str:
    if not data.stress:
        return ""

    rows = ""
    for s in data.stress:
        pr_color = _pct_color(s.portfolio_return)
        dd_color = _pct_color(s.max_drawdown)
        rows += (
            f"<tr>"
            f'<td style="font-weight:500;color:var(--text-primary)">{_e(s.name)}</td>'
            f'<td style="text-align:center;font-size:8px;color:var(--slate-500)">'
            f"{s.start_date.strftime('%b %Y')} &ndash; {s.end_date.strftime('%b %Y')}</td>"
            f'<td style="text-align:right;color:{pr_color};font-weight:500">'
            f'{_pct_display(s.portfolio_return)}</td>'
            f'<td style="text-align:right;color:{dd_color};font-weight:500">'
            f'{_pct_display(s.max_drawdown)}</td>'
            f"</tr>"
        )

    return (
        f'<table class="fixed-cols"><thead><tr>'
        f'<th style="width:30%">{_e(labels["scenario"])}</th>'
        f'<th style="text-align:center;width:25%">{_e(labels["period"])}</th>'
        f'<th style="text-align:right;width:22%">{_e(labels["portfolio_return"])}</th>'
        f'<th style="text-align:right;width:23%">{_e(labels["max_drawdown"])}</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Fee structure section (client-safe: NO drag, NO status)
# ---------------------------------------------------------------------------


def _fee_section(data: FactSheetData, labels: dict[str, str]) -> str:
    fd = data.fee_drag
    if not fd:
        return ""

    # Summary row — 3 cards (instruments, gross, net)
    summary = (
        f'<div style="display:flex;gap:12px;margin:8px 0 12px">'
        f'<div style="flex:1;text-align:center;padding:8px 10px;'
        f'border-bottom:0.5px solid var(--slate-200)">'
        f'<div style="font-size:7px;color:var(--slate-500);text-transform:uppercase;'
        f'letter-spacing:0.05em;font-weight:500">{_e(labels["fd_instruments"])}</div>'
        f'<div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-top:2px">'
        f'{fd.get("total_instruments", 0)}</div></div>'
        f'<div style="flex:1;text-align:center;padding:8px 10px;'
        f'border-bottom:0.5px solid var(--slate-200)">'
        f'<div style="font-size:7px;color:var(--slate-500);text-transform:uppercase;'
        f'letter-spacing:0.05em;font-weight:500">{_e(labels["fd_gross_return"])}</div>'
        f'<div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-top:2px">'
        f'{_pct_unsigned(fd.get("weighted_gross_return"))}</div></div>'
        f'<div style="flex:1;text-align:center;padding:8px 10px;'
        f'border-bottom:0.5px solid var(--slate-200)">'
        f'<div style="font-size:7px;color:var(--slate-500);text-transform:uppercase;'
        f'letter-spacing:0.05em;font-weight:500">{_e(labels["fd_net_return"])}</div>'
        f'<div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-top:2px">'
        f'{_pct_unsigned(fd.get("weighted_net_return"))}</div></div>'
        f"</div>"
    )

    # Per-fund table
    instruments = fd.get("instruments", [])
    rows = ""
    for inst in instruments:
        fb = inst.get("fee_breakdown", {})
        rows += (
            f"<tr>"
            f'<td style="font-weight:500;color:var(--text-primary)">'
            f'{_e(inst.get("name", ""))}</td>'
            f'<td style="text-align:right">{_pct_unsigned(fb.get("management"))}</td>'
            f'<td style="text-align:right">{_pct_unsigned(fb.get("performance"))}</td>'
            f'<td style="text-align:right">{_pct_unsigned(fb.get("other"))}</td>'
            f'<td style="text-align:right;font-weight:600">{_pct_unsigned(fb.get("total"))}</td>'
            f"</tr>"
        )

    table = (
        f'<table class="fixed-cols"><thead><tr>'
        f'<th style="width:36%">{_e(labels["fc_fund"])}</th>'
        f'<th style="text-align:right;width:16%">{_e(labels["fc_mgmt_fee"])}</th>'
        f'<th style="text-align:right;width:16%">{_e(labels["fc_perf_fee"])}</th>'
        f'<th style="text-align:right;width:16%">{_e(labels["fc_other_fee"])}</th>'
        f'<th style="text-align:right;width:16%">{_e(labels["fc_total_fee"])}</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    ) if instruments else ""

    return f"{summary}{table}"


# ---------------------------------------------------------------------------
# Attribution table
# ---------------------------------------------------------------------------


def _attribution_table(data: FactSheetData, labels: dict[str, str]) -> str:
    if not data.attribution:
        return ""

    rows = ""
    tot_alloc = 0.0
    tot_sel = 0.0
    tot_inter = 0.0
    tot_total = 0.0
    for a in data.attribution:
        color_te = _pct_color(a.total_effect)
        rows += (
            f"<tr>"
            f'<td style="font-weight:500;color:var(--text-primary)">{_e(a.block_name)}</td>'
            f'<td style="text-align:right;color:{_pct_color(a.allocation_effect)}">'
            f'{_pct_display(a.allocation_effect, decimals=3)}</td>'
            f'<td style="text-align:right;color:{_pct_color(a.selection_effect)}">'
            f'{_pct_display(a.selection_effect, decimals=3)}</td>'
            f'<td style="text-align:right;color:{_pct_color(a.interaction_effect)}">'
            f'{_pct_display(a.interaction_effect, decimals=3)}</td>'
            f'<td style="text-align:right;font-weight:600;color:{color_te}">'
            f"{_pct_display(a.total_effect, decimals=3)}</td>"
            f"</tr>"
        )
        tot_alloc += a.allocation_effect
        tot_sel += a.selection_effect
        tot_inter += a.interaction_effect
        tot_total += a.total_effect

    footer = (
        f"<tfoot><tr>"
        f'<td style="font-weight:700;color:var(--text-primary)">Total</td>'
        f'<td style="text-align:right;font-weight:700;color:{_pct_color(tot_alloc)}">'
        f'{_pct_display(tot_alloc, decimals=3)}</td>'
        f'<td style="text-align:right;font-weight:700;color:{_pct_color(tot_sel)}">'
        f'{_pct_display(tot_sel, decimals=3)}</td>'
        f'<td style="text-align:right;font-weight:700;color:{_pct_color(tot_inter)}">'
        f'{_pct_display(tot_inter, decimals=3)}</td>'
        f'<td style="text-align:right;font-weight:700;color:{_pct_color(tot_total)}">'
        f"{_pct_display(tot_total, decimals=3)}</td>"
        f"</tr></tfoot>"
    )

    return (
        f'<table class="fixed-cols"><thead><tr>'
        f'<th style="width:28%">{_e(labels["asset_class"])}</th>'
        f'<th style="text-align:right;width:18%">{_e(labels["allocation_effect"])}</th>'
        f'<th style="text-align:right;width:18%">{_e(labels["selection_effect"])}</th>'
        f'<th style="text-align:right;width:18%">{_e(labels["interaction_effect"])}</th>'
        f'<th style="text-align:right;width:18%">{_e(labels["total_effect"])}</th>'
        f"</tr></thead><tbody>{rows}</tbody>{footer}</table>"
    )


# ---------------------------------------------------------------------------
# Monthly returns matrix (Year × Month + YTD)
# ---------------------------------------------------------------------------


def _monthly_returns_matrix(data: FactSheetData, labels: dict[str, str], language: Language) -> str:
    nav = data.nav_series
    if not nav or len(nav) < 2:
        return ""

    monthly_nav: dict[tuple[int, int], float] = {}
    for p in nav:
        monthly_nav[(p.nav_date.year, p.nav_date.month)] = p.nav

    sorted_keys = sorted(monthly_nav)
    if len(sorted_keys) < 2:
        return ""

    monthly_ret: dict[tuple[int, int], float] = {}
    for i in range(1, len(sorted_keys)):
        k = sorted_keys[i]
        kp = sorted_keys[i - 1]
        monthly_ret[k] = monthly_nav[k] / monthly_nav[kp] - 1

    years = sorted({k[0] for k in sorted_keys}, reverse=True)
    months_hdr = MONTHS_SHORT.get(language, MONTHS_SHORT["en"])

    def _ytd_for_year(yr: int) -> float | None:
        yr_keys = [(y, m) for y, m in sorted_keys if y == yr]
        if not yr_keys:
            return None
        last_nav = monthly_nav[yr_keys[-1]]
        prev_dec = monthly_nav.get((yr - 1, 12))
        if prev_dec is not None:
            return last_nav / prev_dec - 1
        first_nav = monthly_nav[yr_keys[0]]
        if first_nav == last_nav:
            return None
        return last_nav / first_nav - 1

    hdr = '<th style="text-align:left;width:36px">Year</th>'
    for m in months_hdr:
        hdr += f'<th style="text-align:center">{m}</th>'
    hdr += '<th style="text-align:center">YTD</th>'

    body = ""
    for yr in years:
        cells = f'<td style="font-weight:700;color:var(--text-primary)">{yr}</td>'
        for mo in range(1, 13):
            ret = monthly_ret.get((yr, mo))
            if ret is None:
                cells += '<td style="text-align:center;color:var(--slate-400)">&mdash;</td>'
            else:
                pct = ret * 100
                if pct < 0:
                    display = f"({abs(pct):.1f})"
                    color = "var(--slate-700)"
                else:
                    display = f"{pct:.1f}"
                    color = "var(--text-primary)"
                cells += f'<td style="text-align:center;color:{color}">{display}</td>'
        ytd_val = _ytd_for_year(yr)
        if ytd_val is None:
            cells += '<td style="text-align:center;color:var(--slate-400)">&mdash;</td>'
        else:
            pct = ytd_val * 100
            if pct < 0:
                display = f"({abs(pct):.1f}%)"
                color = "var(--slate-700)"
            else:
                display = f"+{pct:.1f}%"
                color = "var(--text-primary)"
            cells += f'<td style="text-align:center;color:{color};font-weight:600">{display}</td>'
        body += f"<tr>{cells}</tr>"

    return (
        f'<table class="matrix"><thead><tr>{hdr}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Regime legend (compact inline for chart annotation)
# ---------------------------------------------------------------------------


def _regime_legend(data: FactSheetData) -> str:
    if not data.regimes:
        return ""

    seen: dict[str, str] = {}
    for r in data.regimes:
        if r.regime != "expansion" and r.regime not in seen:
            seen[r.regime] = _REGIME_LABELS.get(r.regime, r.regime)

    if not seen:
        return ""

    dots = ""
    for regime, label in seen.items():
        color = _REGIME_DOT_COLORS.get(regime, "#94A3B8")
        dots += (
            f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
            f'<span style="width:8px;height:8px;border-radius:1px;background:{color};'
            f'opacity:0.6;display:inline-block"></span>'
            f'<span style="font-size:8px;color:var(--slate-500)">{label}</span>'
            f"</span>"
        )

    return f'<div style="margin:4px 0 6px;display:flex;align-items:center">{dots}</div>'


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _compute_total_pages(data: FactSheetData) -> int:
    """Cover + Performance + Composition + optional pages."""
    pages = 3  # cover + performance + composition
    has_stress_fee_or_matrix = (
        data.stress
        or data.fee_drag
        or (data.nav_series and len(data.nav_series) >= 2)
    )
    if has_stress_fee_or_matrix:
        pages += 1  # stress + monthly returns page
    if data.attribution:
        pages += 1  # attribution gets own page
    return pages


# ── Cover (page 1) ──


def _cover_page(
    data: FactSheetData,
    labels: dict[str, str],
    language: Language,
    total_pages: int,
) -> str:
    """Full-page navy cover — identical structure to DD Report."""

    # TOC entries — map sections to pages
    toc_sections: list[tuple[int, str, int]] = []
    toc_sections.append((1, "Performance Overview", 2))
    toc_sections.append((2, "Portfolio Analysis", 2))
    toc_sections.append((3, "Strategic Composition", 3))

    next_page = 4
    if data.attribution:
        toc_sections.append((4, "Attribution Analysis", next_page))
        next_page += 1

    has_risk_page = data.stress or data.fee_drag or (data.nav_series and len(data.nav_series) >= 2)
    if has_risk_page:
        toc_sections.append((len(toc_sections) + 1, "Risk Profile & Returns", next_page))

    toc_items = ""
    for num, title, page in toc_sections:
        toc_items += (
            f'<div class="toc-row">'
            f'<span class="toc-num">{num}.</span>'
            f'<span class="toc-title">{_e(title)}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-page">{page}</span>'
            f"</div>"
        )

    return (
        f'<div class="page"><div class="cover">'
        # Label
        f'<div class="cv-label">'
        f'{_e(labels["report_title_institutional"])} &middot; Fact Sheet &middot; Confidential</div>'
        # Portfolio name
        f'<div class="cv-fund">{_e(data.portfolio_name)}</div>'
        # Subtitle
        f'<div class="cv-sub">'
        f'{_e(labels["as_of"])} {format_date(data.as_of, language)} &middot; '
        f'{_e(labels["profile"])}: {_e(data.profile.title())}</div>'
        # Copper accent rule
        f'<div class="cv-rule"></div>'
        # TOC
        f'<div style="margin-top:8px">'
        f'<div class="toc-label">Table of Contents</div>'
        f"{toc_items}</div>"
        # Spacer
        f'<div style="flex:1"></div>'
        # Footer
        f'<div class="cv-footer">'
        f"{_e(labels['confidential'])} &middot; "
        f"p.&thinsp;1 of {total_pages}</div>"
        f"</div></div>"
    )


# ── Page 2: Performance Overview + Portfolio Analysis ──


def _page_performance(
    data: FactSheetData,
    labels: dict[str, str],
    language: Language,
    total_pages: int,
) -> str:
    """Performance page — 70/30 sidenote layout."""
    parts: list[str] = []

    # Page header bar
    parts.append(
        f'<div class="ph">'
        f'<span class="ph-fund">{_e(data.portfolio_name)}</span>'
        f'<span class="ph-page">p.&thinsp;2 of {total_pages}</span>'
        f"</div>"
    )

    # Section header
    parts.append(
        f'<div class="ch-header">'
        f'<div class="ch-ord">Performance Overview</div>'
        f'<div class="ch-title">{_e(data.portfolio_name)}</div>'
        f"</div>"
    )

    # 70/30 layout
    parts.append('<div class="ch-wrap">')

    # ── Main column (70%) ──
    parts.append('<div class="ch-main">')

    # KPI strip — MTD / QTD / YTD / Since Inception
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
            bm_sub = (
                f'<div class="kpi-cell-sub">'
                f"BM {_pct_display(active)}</div>"
            )
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
        regime_spans = _build_regime_spans(data)
        chart_svg = performance_line_chart(
            svg_points, width=410, height=180, regimes=regime_spans,
        )
        legend = (
            '<div style="display:flex;gap:16px;margin:4px 0 0;font-size:7.5px;'
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
        parts.append(f'<div style="margin:8px 0 4px">{chart_svg}{legend}</div>')
        regime_leg = _regime_legend(data)
        if regime_leg:
            parts.append(regime_leg)

    # Returns table
    parts.append(f'<div style="margin:8px 0">{_returns_table(data, labels)}</div>')

    # Portfolio Analysis section
    if data.manager_commentary:
        parts.append(
            f'<h3 class="sh">Portfolio Analysis</h3>'
            f'<p class="bt">{_e(data.manager_commentary)}</p>'
        )

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

    # Build sparkline data from NAV series (last 12 points for each metric)
    nav_vals = [p.nav for p in data.nav_series[-24:]] if data.nav_series else []

    for label, val, fmt in margin_metrics:
        display = fmt(val) if val is not None else "&mdash;"  # type: ignore[no-untyped-call]
        color = "var(--burgundy)" if val is not None and val < 0 else "var(--text-primary)"
        spark_html = ""
        # Sparkline for annualized return and Sharpe (use NAV trend)
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

    # Benchmark label block
    if data.benchmark_label:
        parts.append(
            f'<div style="margin-top:14px;padding-top:10px;'
            f'border-top:0.5px solid var(--slate-200)">'
            f'<div class="mg-ev">'
            f'<div class="mg-ev-label">Benchmark</div>'
            f'<div class="mg-ev-item">{_e(data.benchmark_label)}</div>'
            f"</div></div>"
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
        f"<span>p.&thinsp;2 of {total_pages}</span>"
        f"</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


# ── Page 3: Strategic Composition + Risk Profile ──


def _page_composition(
    data: FactSheetData,
    labels: dict[str, str],
    page_num: int,
    total_pages: int,
) -> str:
    """Composition page — 70/30 sidenote layout."""
    parts: list[str] = []

    # Page header bar
    parts.append(
        f'<div class="ph">'
        f'<span class="ph-fund">{_e(data.portfolio_name)}</span>'
        f'<span class="ph-page">p.&thinsp;{page_num} of {total_pages}</span>'
        f"</div>"
    )

    # Section header
    parts.append(
        f'<div class="ch-header">'
        f'<div class="ch-ord">Strategic Composition</div>'
        f'<div class="ch-title">{_e(data.portfolio_name)}</div>'
        f"</div>"
    )

    # 70/30 layout
    parts.append('<div class="ch-wrap">')

    # ── Main column (70%) ──
    parts.append('<div class="ch-main">')

    # Strategic allocation bars
    blocks = _alloc_blocks(data)
    if blocks:
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

    # Holdings table
    if data.holdings:
        parts.append('<h3 class="sh" style="margin-top:16px">Holdings by Strategy</h3>')
        parts.append(_holdings_table(data.holdings, labels))

    parts.append("</div>")  # close ch-main

    # ── Margin column (30%): Risk Profile ──
    parts.append('<div class="ch-margin">')

    parts.append('<div class="mg-ev-label">RISK PROFILE</div>')

    risk_items = [
        (labels["annualized_return"], _annualized_return(data), lambda v: _pct_display(v)),
        (labels["sharpe"], data.risk.sharpe, lambda v: f"{v:.2f}"),
        (labels["annualized_vol"], data.risk.annualized_vol, lambda v: f"{v * 100:.1f}%"),
        (labels["max_drawdown"], data.risk.max_drawdown, lambda v: f"({abs(v) * 100:.2f}%)"),
    ]

    for label, val, fmt in risk_items:
        display = fmt(val) if val is not None else "&mdash;"  # type: ignore[no-untyped-call]
        color = "var(--burgundy)" if val is not None and val < 0 else "var(--text-primary)"
        parts.append(
            f'<div class="mg-q">'
            f'<div class="mg-q-label">{_e(label)}</div>'
            f'<div class="mg-q-right">'
            f'<div class="mg-q-val" style="color:{color}">{display}</div>'
            f"</div></div>"
        )

    # Current regime (if available)
    if data.regimes:
        latest_regime = data.regimes[-1].regime
        regime_label = _REGIME_LABELS.get(latest_regime, latest_regime)
        parts.append(
            f'<div style="margin-top:14px;padding-top:10px;'
            f'border-top:0.5px solid var(--slate-200)">'
            f'<div class="mg-ev">'
            f'<div class="mg-ev-label">Current Regime</div>'
            f'<div class="mg-ev-item" style="font-weight:600;font-size:9px">'
            f"{_e(regime_label)}</div>"
            f"</div></div>"
        )

    # CVaR (if available)
    if data.risk.cvar_95 is not None:
        parts.append(
            f'<div style="margin-top:{"14px" if not data.regimes else "8px"};'
            f'{"padding-top:10px;border-top:0.5px solid var(--slate-200)" if not data.regimes else ""}">'
            f'<div class="mg-ev">'
            f'<div class="mg-ev-label">{_e(labels["cvar_95"])}</div>'
            f'<div class="mg-ev-item" style="font-weight:600;font-size:9px;'
            f'color:var(--burgundy)">{data.risk.cvar_95 * 100:.2f}%</div>'
            f"</div></div>"
        )

    parts.append("</div>")  # close ch-margin
    parts.append("</div>")  # close ch-wrap

    # Page footer
    parts.append(
        f'<div class="pf">'
        f"<span>Confidential &mdash; For authorized recipients only</span>"
        f"<span>p.&thinsp;{page_num} of {total_pages}</span>"
        f"</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


# ── Attribution page (optional) ──


def _page_attribution(
    data: FactSheetData,
    labels: dict[str, str],
    page_num: int,
    total_pages: int,
) -> str:
    """Attribution analysis page — full-width Tufte table."""
    if not data.attribution:
        return ""

    parts: list[str] = []

    parts.append(
        f'<div class="ph">'
        f'<span class="ph-fund">{_e(data.portfolio_name)}</span>'
        f'<span class="ph-page">p.&thinsp;{page_num} of {total_pages}</span>'
        f"</div>"
    )

    parts.append(
        '<div class="ch-header">'
        '<div class="ch-ord">Attribution Analysis</div>'
        '<div class="ch-title">Brinson-Fachler Decomposition</div>'
        "</div>"
    )

    parts.append(
        f'<div style="padding:14px 40px 0">'
        f"{_attribution_table(data, labels)}"
        f"</div>"
    )

    parts.append(
        f'<div class="pf">'
        f"<span>Confidential &mdash; For authorized recipients only</span>"
        f"<span>p.&thinsp;{page_num} of {total_pages}</span>"
        f"</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


# ── Risk & Returns page (stress + fees + monthly returns + disclaimer) ──


def _page_risk_returns(
    data: FactSheetData,
    labels: dict[str, str],
    language: Language,
    page_num: int,
    total_pages: int,
) -> str:
    """Stress scenarios + fee structure + monthly returns matrix + disclaimer."""
    parts: list[str] = []

    parts.append(
        f'<div class="ph">'
        f'<span class="ph-fund">{_e(data.portfolio_name)}</span>'
        f'<span class="ph-page">p.&thinsp;{page_num} of {total_pages}</span>'
        f"</div>"
    )

    parts.append(
        f'<div class="ch-header">'
        f'<div class="ch-ord">Risk Profile &amp; Returns</div>'
        f'<div class="ch-title">{_e(data.portfolio_name)}</div>'
        f"</div>"
    )

    parts.append('<div style="padding:14px 40px 0">')

    # Stress scenarios
    if data.stress:
        parts.append('<h3 class="sh">Historical Stress Scenarios</h3>')
        parts.append(f'<div style="margin:6px 0 16px">{_stress_table(data, labels)}</div>')

    # Fee structure
    if data.fee_drag:
        parts.append('<h3 class="sh">Cost Analysis</h3>')
        parts.append(f'<div style="margin:6px 0 16px">{_fee_section(data, labels)}</div>')

    # Monthly returns matrix
    matrix = _monthly_returns_matrix(data, labels, language)
    if matrix:
        parts.append(f'<h3 class="sh">{_e(labels["monthly_returns"])}</h3>')
        parts.append(f'<div style="margin:6px 0">{matrix}</div>')

    # Disclaimer
    parts.append(
        '<div class="disc">'
        '<div class="disc-title">Important Disclosures &amp; Disclaimer</div>'
        "<p>This Institutional Fact Sheet is produced by the InvestIntell quantitative "
        "research platform. All analytics, risk metrics, performance data, and "
        "portfolio assessments are derived from official regulatory filings "
        "(SEC EDGAR Form ADV, Form N-PORT, Form 13F), macroeconomic data sources, "
        "and proprietary quantitative models.</p>"
        "<p>This report does not constitute investment advice. Past performance is "
        "not indicative of future results. Recipients should conduct independent "
        "verification before making investment decisions.</p>"
        "<p><strong>Confidentiality:</strong> Proprietary and confidential. "
        "Unauthorized reproduction or distribution is strictly prohibited.</p>"
        "<p>&copy; InvestIntell. All rights reserved.</p>"
        "</div>"
    )

    parts.append("</div>")  # close content padding

    # Page footer
    bt = (
        f' <span class="backtest-note">*{_e(labels["backtest_note"])}</span>'
        if data.returns.is_backtest
        else ""
    )
    parts.append(
        f'<div class="pf">'
        f"<span>Confidential &mdash; For authorized recipients only{bt}</span>"
        f"<span>p.&thinsp;{page_num} of {total_pages}</span>"
        f"</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_fact_sheet_institutional(
    data: FactSheetData,
    *,
    language: Language = "en",
) -> str:
    """Render 3-5 page Institutional Fact Sheet as self-contained HTML.

    Parameters
    ----------
    data:
        Frozen ``FactSheetData`` with all fields including attribution, stress,
        regimes, and fee_drag.
    language:
        ``"pt"`` or ``"en"`` for bilingual labels and date formatting.

    Returns
    -------
    str
        Complete HTML ready for Playwright PDF rendering.
    """
    labels = LABELS[language]
    total_pages = _compute_total_pages(data)

    pages: list[str] = []
    pages.append(_cover_page(data, labels, language, total_pages))
    pages.append(_page_performance(data, labels, language, total_pages))
    pages.append(_page_composition(data, labels, 3, total_pages))

    page_num = 4
    if data.attribution:
        pages.append(_page_attribution(data, labels, page_num, total_pages))
        page_num += 1

    has_risk_page = (
        data.stress
        or data.fee_drag
        or (data.nav_series and len(data.nav_series) >= 2)
    )
    if has_risk_page:
        pages.append(_page_risk_returns(data, labels, language, page_num, total_pages))

    return (
        f"<!DOCTYPE html>"
        f'<html lang="{_e(language)}">'
        f"<head>"
        f'<meta charset="utf-8"/>'
        f"<title>{_e(data.portfolio_name)} &mdash; "
        f"{_e(labels['report_title_institutional'])}</title>"
        f"<style>{_CSS}</style>"
        f"</head>"
        f"<body>{''.join(pages)}</body>"
        f"</html>"
    )
