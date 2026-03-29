"""Fact Sheet Institutional HTML template (4-6 page A4, rendered via Playwright).

Extends the Executive layout with attribution, stress scenarios, regime overlay,
fee structure analysis, and monthly returns matrix.

Design: Netz Premium Institutional — Playfair Display headings, Inter body,
navy/slate palette, Tufte tables, asymmetric 30/70 grid layout (page 2+),
area-chart SVG with regime bands, 75/25 chart+risk architectural block.

All user-supplied text is escaped via ``html.escape()``.
Bilingual PT/EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
from datetime import date
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
from vertical_engines.wealth.pdf.svg_charts import RegimeSpan
from vertical_engines.wealth.pdf.svg_charts import (
    allocation_bars,
    performance_line_chart,
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
    --slate-300: #CBD5E1;
    --slate-200: #E2E8F0;
    --slate-100: #F1F5F9;
    --slate-50: #F8FAFC;
    --copper: #B48608;
    --copper-light: #D4A017;
    --burgundy: #8B0000;
    --burgundy-light: #991B1B;
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

/* --- Masthead (page 1) --- */
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

/* --- Continuation page header --- */
.page-header {
    display: flex; justify-content: space-between;
    align-items: center;
    padding: 16px 28px 12px;
    border-bottom: 1px solid var(--slate-200);
    margin-bottom: 0;
}
.page-header-name {
    font-family: 'Playfair Display', serif;
    font-size: 13px; font-weight: 600;
    color: var(--text-primary);
}
.page-header-pager {
    font-size: 8px; color: var(--slate-400);
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

/* --- Chart + Risk grid (75/25) --- */
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

/* --- Asymmetric grid (30/70) for page 2 --- */
.grid-asym {
    display: grid;
    grid-template-columns: 30% 70%;
    min-height: calc(297mm - 90px);
}
.sidebar {
    background: var(--slate-50);
    padding: 20px 18px 60px;
    border-right: 1px solid var(--slate-200);
}
.main-frame {
    background: var(--white);
    padding: 20px 24px 60px;
}

/* --- Monthly returns matrix --- */
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
"""

# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------

_ALLOC_COLORS = [
    "#0A192F", "#1E3A5F", "#2D5F8A", "#3D7CB5",
    "#64748B", "#8B7355", "#4A6741", "#6B5B73",
]


def _section_title(title: str) -> str:
    return f'<div class="sec-title">{_e(title)}</div>'


def _page_header(name: str, as_of: date, page: int, total: int) -> str:
    return (
        f'<div class="page-header">'
        f'<span class="page-header-name">{_e(name)}</span>'
        f'<span class="page-header-pager">p.&nbsp;{page}/{total}</span>'
        f"</div>"
    )


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


def _kpi_card(label: str, value: float | None) -> str:
    color = _pct_color(value)
    display = _pct_display(value) if value is not None else "&mdash;"
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-label">{_e(label)}</div>'
        f'<div class="kpi-value" style="color:{color}">{display}</div>'
        f"</div>"
    )


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
        return si
    return (1 + si) ** (1 / years) - 1


def _chart_risk_block(
    data: FactSheetData,
    labels: dict[str, str],
    *,
    regimes: list[RegimeSpan] | None = None,
) -> str:
    """Render chart (75%) + stacked risk metrics (25%) side by side."""
    svg_points = _to_svg_nav(data)
    chart_svg = performance_line_chart(
        svg_points, width=500, height=210, regimes=regimes,
    )

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
# Attribution table (Tufte, "Asset Class" label)
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

    # Summary row — 3 cards only (instruments, gross, net). No drag ratio.
    summary = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:8px 0 12px">'
        f'<div style="background:var(--slate-50);padding:8px 10px;text-align:center">'
        f'<div style="font-size:7.5px;color:var(--slate-500);text-transform:uppercase;'
        f'letter-spacing:0.05em;font-weight:500">{_e(labels["fd_instruments"])}</div>'
        f'<div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-top:2px">'
        f'{fd.get("total_instruments", 0)}</div></div>'
        f'<div style="background:var(--slate-50);padding:8px 10px;text-align:center">'
        f'<div style="font-size:7.5px;color:var(--slate-500);text-transform:uppercase;'
        f'letter-spacing:0.05em;font-weight:500">{_e(labels["fd_gross_return"])}</div>'
        f'<div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-top:2px">'
        f'{_pct_unsigned(fd.get("weighted_gross_return"))}</div></div>'
        f'<div style="background:var(--slate-50);padding:8px 10px;text-align:center">'
        f'<div style="font-size:7.5px;color:var(--slate-500);text-transform:uppercase;'
        f'letter-spacing:0.05em;font-weight:500">{_e(labels["fd_net_return"])}</div>'
        f'<div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-top:2px">'
        f'{_pct_unsigned(fd.get("weighted_net_return"))}</div></div>'
        f"</div>"
    )

    # Per-fund table: Fund, Mgmt Fee, Perf Fee, Other, Total ONLY
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

    return (
        f"{_section_title(labels['fee_drag_analysis'])}"
        f"{summary}"
        f'<div style="margin-top:6px">{_section_title(labels["fee_comparison"])}</div>'
        f"{table}"
    )


# ---------------------------------------------------------------------------
# Monthly returns matrix (Year × Month + YTD)
# ---------------------------------------------------------------------------


def _monthly_returns_matrix(data: FactSheetData, labels: dict[str, str], language: Language) -> str:
    """Classic industry-standard monthly returns table.

    Rows = years (reverse chronological), columns = Jan–Dec + YTD.
    """
    nav = data.nav_series
    if not nav or len(nav) < 2:
        return ""

    # Collect last NAV per calendar month
    monthly_nav: dict[tuple[int, int], float] = {}
    for p in nav:
        monthly_nav[(p.nav_date.year, p.nav_date.month)] = p.nav

    sorted_keys = sorted(monthly_nav)
    if len(sorted_keys) < 2:
        return ""

    # Compute month-over-month returns
    monthly_ret: dict[tuple[int, int], float] = {}
    for i in range(1, len(sorted_keys)):
        k = sorted_keys[i]
        kp = sorted_keys[i - 1]
        monthly_ret[k] = monthly_nav[k] / monthly_nav[kp] - 1

    years = sorted({k[0] for k in sorted_keys}, reverse=True)
    months_hdr = MONTHS_SHORT.get(language, MONTHS_SHORT["en"])

    # YTD per year: cumulative from Dec prev year (or first available) to last month
    def _ytd_for_year(yr: int) -> float | None:
        yr_keys = [(y, m) for y, m in sorted_keys if y == yr]
        if not yr_keys:
            return None
        last_nav = monthly_nav[yr_keys[-1]]
        # Previous Dec
        prev_dec = monthly_nav.get((yr - 1, 12))
        if prev_dec is not None:
            return last_nav / prev_dec - 1
        # Inception year: use first available NAV of that year
        first_nav = monthly_nav[yr_keys[0]]
        if first_nav == last_nav:
            return None
        return last_nav / first_nav - 1

    # Build header
    hdr = '<th style="text-align:left;width:36px">Year</th>'
    for m in months_hdr:
        hdr += f'<th style="text-align:center">{m}</th>'
    hdr += '<th style="text-align:center">YTD</th>'

    # Build rows
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
        # YTD column
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
        f"{_section_title(labels['monthly_returns'])}"
        f'<table class="matrix"><thead><tr>{hdr}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _compute_total_pages(data: FactSheetData) -> int:
    pages = 2  # page 1 (header+KPI+chart+returns) + page 2 (30/70 grid)
    if data.attribution:
        pages += 1
    has_stress_or_fee = data.stress or data.fee_drag
    if has_stress_or_fee:
        pages += 1
    # Monthly returns matrix always gets its own page if we have NAV data
    if data.nav_series and len(data.nav_series) >= 2:
        pages += 1
    return pages


def _page1_inst(
    data: FactSheetData,
    labels: dict[str, str],
    language: Language,
    total_pages: int,
) -> str:
    """Page 1: Masthead, chart+risk 75/25 block, returns table, commentary."""
    header = (
        f'<div class="masthead">'
        f'<div class="masthead-label">'
        f'{_e(labels["report_title_institutional"])} &middot; FACT SHEET</div>'
        f'<div class="masthead-name">{_e(data.portfolio_name)}</div>'
        f'<div class="masthead-meta">'
        f'{_e(labels["as_of"])} {format_date(data.as_of, language)}'
        f' &nbsp;&bull;&nbsp; {_e(labels["profile"])}: {_e(data.profile.title())}'
        f"</div></div>"
    )

    # Chart + Risk 75/25 block with regime bands
    regime_spans = _build_regime_spans(data)
    chart_risk = _chart_risk_block(data, labels, regimes=regime_spans)
    regime_leg = _regime_legend(data)

    returns_html = _returns_table(data, labels)

    # Manager commentary — first page, right after returns
    commentary = ""
    if data.manager_commentary:
        commentary = (
            f'<div style="margin:10px 0 0">'
            f"{_section_title(labels['manager_commentary'])}"
            f'<p style="font-size:9.5px;line-height:1.6;color:var(--text-secondary);'
            f'font-style:italic">{_e(data.manager_commentary)}</p></div>'
        )

    return (
        f'<div class="page">'
        f"{header}"
        f'<div style="padding:0 28px">'
        f"{chart_risk}"
        f"{regime_leg}"
        f'<div style="margin:6px 0">{returns_html}</div>'
        f"{commentary}"
        f"</div>"
        f"{_page_footer(data.as_of, 1, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page2_inst(
    data: FactSheetData,
    labels: dict[str, str],
    total_pages: int,
) -> str:
    """Page 2: Asymmetric 30/70 — sidebar (allocation) / main (holdings + commentary)."""

    # --- Sidebar (30%): allocation only ---
    sidebar_parts = ""
    sidebar_parts += (
        f'<div class="sec-title" style="border-bottom-color:var(--slate-300)">'
        f'{_e(labels["allocation"])}</div>'
    )
    sidebar_parts += allocation_bars(_alloc_blocks(data), width=155)

    # --- Main frame (70%): holdings ---
    main_parts = ""
    main_parts += _section_title(labels["top_holdings"])
    main_parts += _holdings_table(data.holdings, labels)

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, 2, total_pages)}"
        f'<div class="grid-asym">'
        f'<div class="sidebar">{sidebar_parts}</div>'
        f'<div class="main-frame">{main_parts}</div>'
        f"</div>"
        f"{_page_footer(data.as_of, 2, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page_attribution(
    data: FactSheetData,
    labels: dict[str, str],
    page_num: int,
    total_pages: int,
) -> str:
    """Attribution analysis page — full-width Tufte table."""
    if not data.attribution:
        return ""

    table = _attribution_table(data, labels)

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, page_num, total_pages)}"
        f'<div style="padding:20px 28px">'
        f"{_section_title(labels['attribution'])}"
        f'<div style="margin:8px 0">{table}</div>'
        f"</div>"
        f"{_page_footer(data.as_of, page_num, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page_risk_deepdive(
    data: FactSheetData,
    labels: dict[str, str],
    page_num: int,
    total_pages: int,
) -> str:
    """Stress scenarios + fee structure (client-safe)."""
    parts: list[str] = []

    if data.stress:
        parts.append(_section_title(labels["stress_scenarios"]))
        parts.append(f'<div style="margin:6px 0 16px">{_stress_table(data, labels)}</div>')

    if data.fee_drag:
        parts.append(f'<div style="margin-top:12px">{_fee_section(data, labels)}</div>')

    if not parts:
        return ""

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, page_num, total_pages)}"
        f'<div style="padding:20px 28px">'
        f"{''.join(parts)}"
        f"</div>"
        f"{_page_footer(data.as_of, page_num, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page_monthly_matrix(
    data: FactSheetData,
    labels: dict[str, str],
    language: Language,
    page_num: int,
    total_pages: int,
) -> str:
    """Monthly returns matrix — final page before disclaimer."""
    matrix = _monthly_returns_matrix(data, labels, language)
    if not matrix:
        return ""

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, page_num, total_pages)}"
        f'<div style="padding:20px 28px">'
        f"{matrix}"
        f"</div>"
        f"{_page_footer(data.as_of, page_num, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_fact_sheet_institutional(
    data: FactSheetData,
    *,
    language: Language = "en",
) -> str:
    """Render 4-6 page Institutional Fact Sheet as self-contained HTML.

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
    pages.append(_page1_inst(data, labels, language, total_pages))
    pages.append(_page2_inst(data, labels, total_pages))

    page_num = 3
    if data.attribution:
        pages.append(_page_attribution(data, labels, page_num, total_pages))
        page_num += 1

    risk_page = _page_risk_deepdive(data, labels, page_num, total_pages)
    if risk_page:
        pages.append(risk_page)
        page_num += 1

    matrix_page = _page_monthly_matrix(data, labels, language, page_num, total_pages)
    if matrix_page:
        pages.append(matrix_page)

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
