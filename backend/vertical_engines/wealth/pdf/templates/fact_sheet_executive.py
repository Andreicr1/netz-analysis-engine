"""Fact Sheet Executive HTML template (1-2 page A4, rendered via Playwright).

Receives a ``FactSheetData`` dataclass and returns a self-contained HTML
string ready for ``page.set_content()`` + ``page.pdf()``.

All user-supplied text is escaped via ``html.escape()``.
Bilingual PT/EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Any

from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language, format_date
from vertical_engines.wealth.fact_sheet.models import FactSheetData
from vertical_engines.wealth.pdf.svg_charts import NavPoint as SvgNavPoint
from vertical_engines.wealth.pdf.svg_charts import (
    allocation_bars,
    performance_line_chart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FONT_STACK = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def _e(text: Any) -> str:
    if text is None:
        return "&mdash;"
    return html.escape(str(text))


def _pct(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value * 100:+.{decimals}f}%"


def _pct_color(value: float | None) -> str:
    if value is None:
        return "#9ca3af"
    return "#059669" if value >= 0 else "#DC2626"


def _fmt_number(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value:,.{decimals}f}"


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = f"""\
@page {{ size: A4; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{
    font-family: {_FONT_STACK};
    font-size: 10px; color: #374151;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}
.page {{
    width: 210mm; height: 297mm;
    position: relative; overflow: hidden;
    page-break-after: always;
}}
.page:last-child {{ page-break-after: auto; }}
table {{ border-collapse: collapse; width: 100%; }}
th {{
    font-size: 8px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .06em;
    color: #6b7280; text-align: left;
    padding: 5px 6px; border-bottom: 1px solid #d1d5db;
}}
td {{
    font-size: 9px; padding: 4px 6px;
    border-bottom: 1px solid #f3f4f6; color: #374151;
}}
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
        f' <span style="color:#D97706">*{_e(labels["backtest_note"])}</span>'
        if backtest
        else ""
    )
    return (
        f'<div style="position:absolute;bottom:0;left:0;right:0;padding:10px 24px;'
        f"font-size:8px;color:#9ca3af;border-top:1px solid #e5e7eb;"
        f'display:flex;justify-content:space-between;align-items:center">'
        f"<span>{_e(labels['disclaimer'])}{bt}</span>"
        f"<span>p.&nbsp;{page} of {total}</span>"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------------------


def _kpi_card(label: str, value: float | None) -> str:
    color = _pct_color(value)
    display = _pct(value) if value is not None else "&mdash;"
    return (
        f'<div style="flex:1;text-align:center;padding:8px 4px">'
        f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:.06em;margin-bottom:3px">{_e(label)}</div>'
        f'<div style="font-size:16px;font-weight:600;color:{color}">{display}</div>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Returns table
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

    headers = "".join(
        f'<th style="text-align:right">{_e(lbl)}</th>' for lbl, _ in periods
    )

    def _row(name: str, vals: list[float | None]) -> str:
        cells = ""
        for v in vals:
            color = _pct_color(v)
            cells += f'<td style="text-align:right;color:{color}">{_pct(v)}</td>'
        return f"<tr><td style='font-weight:600'>{_e(name)}</td>{cells}</tr>"

    port_row = _row(labels["portfolio"], [v for _, v in periods])
    bm_row = _row("Benchmark", bm_vals)

    # Active row
    active_vals = []
    for (_, pv), bv in zip(periods, bm_vals, strict=True):
        if pv is not None and bv is not None:
            active_vals.append(pv - bv)
        else:
            active_vals.append(None)
    active_row = _row("Active", active_vals)

    return (
        f"<table><thead><tr>"
        f'<th style="width:70px">{_e(labels["returns"])}</th>'
        f"{headers}</tr></thead>"
        f"<tbody>{port_row}{bm_row}"
        f'<tr style="border-top:1px solid #d1d5db">'
        f"{active_row[4:]}"  # strip leading <tr>
        f"</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Risk cards
# ---------------------------------------------------------------------------


def _risk_cards(data: FactSheetData, labels: dict[str, str]) -> str:
    cards = [
        (labels["annualized_vol"], data.risk.annualized_vol, lambda v: f"{v * 100:.1f}%"),
        (labels["sharpe"], data.risk.sharpe, lambda v: f"{v:.2f}"),
        (labels["max_drawdown"], data.risk.max_drawdown, lambda v: f"{v * 100:.2f}%"),
        (labels["cvar_95"], data.risk.cvar_95, lambda v: f"{v * 100:.2f}%"),
    ]
    html_parts = ""
    for label, val, fmt in cards:
        display = fmt(val) if val is not None else "&mdash;"
        html_parts += (
            f'<div style="background:#f9fafb;border-radius:6px;padding:10px;text-align:center">'
            f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:4px">{_e(label)}</div>'
            f'<div style="font-size:14px;font-weight:700;color:#111827">{display}</div>'
            f"</div>"
        )
    return (
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin:8px 0">'
        f"{html_parts}</div>"
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
    rows = ""
    for h in items:
        rows += (
            f"<tr>"
            f"<td>{_e(h.fund_name)}</td>"
            f"<td>{_e(h.block_id)}</td>"
            f'<td style="text-align:right;font-weight:600">{h.weight * 100:.1f}%</td>'
            f"</tr>"
        )
    return (
        f"<table><thead><tr>"
        f"<th>{_e(labels['fund_name'])}</th>"
        f"<th>{_e(labels['block'])}</th>"
        f'<th style="text-align:right">{_e(labels["weight"])}</th>'
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
# Allocation colors
# ---------------------------------------------------------------------------

_ALLOC_COLORS = [
    "#185FA5", "#1D9E75", "#639922", "#BA7517",
    "#888780", "#D44C47", "#6366F1", "#EC4899",
]


def _alloc_blocks(data: FactSheetData) -> list[dict[str, Any]]:
    return [
        {
            "label": a.block_id.replace("_", " ").title(),
            "weight": a.weight,
            "color": _ALLOC_COLORS[i % len(_ALLOC_COLORS)],
        }
        for i, a in enumerate(data.allocations)
    ]


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _page1(data: FactSheetData, labels: dict[str, str], language: Language) -> str:
    # Header
    header = (
        f'<div style="background:#111827;padding:22px 24px">'
        f'<div style="font-size:9px;letter-spacing:.14em;color:#6B7FA8;'
        f'text-transform:uppercase;margin-bottom:4px">'
        f'{_e(labels["report_title_executive"])} &middot; FACT SHEET</div>'
        f'<div style="font-size:20px;font-weight:500;color:#F9FAFB;margin-bottom:2px">'
        f"{_e(data.portfolio_name)}</div>"
        f'<div style="font-size:11px;color:#6B7FA8">'
        f'{_e(labels["as_of"])} {format_date(data.as_of, language)} &middot; '
        f'{_e(labels["profile"])}: {_e(data.profile.title())}</div>'
        f"</div>"
    )

    # KPI strip
    kpi = (
        f'<div style="display:flex;border-bottom:1px solid #e5e7eb">'
        f'{_kpi_card(labels["mtd"], data.returns.mtd)}'
        f'{_kpi_card(labels["ytd"], data.returns.ytd)}'
        f'{_kpi_card(labels["1y"], data.returns.one_year)}'
        f'{_kpi_card(labels["since_inception"], data.returns.since_inception)}'
        f"</div>"
    )

    # Performance chart
    svg_points = _to_svg_nav(data)
    chart = performance_line_chart(svg_points, width=540, height=160)
    legend = (
        '<div style="display:flex;gap:14px;margin:4px 0 8px;font-size:9px;color:#6b7280">'
        '<span><svg width="16" height="2" style="vertical-align:middle">'
        '<line x1="0" y1="1" x2="16" y2="1" stroke="#185FA5" stroke-width="1.8"/></svg>'
        " Portfolio</span>"
        '<span><svg width="16" height="2" style="vertical-align:middle">'
        '<line x1="0" y1="1" x2="16" y2="1" stroke="#9ca3af" stroke-width="1" '
        'stroke-dasharray="4 3"/></svg>'
        f" {_e(data.benchmark_label or 'Benchmark')}</span>"
        "</div>"
    )

    chart_section = (
        f'<div style="margin:8px 0">{chart}</div>{legend}'
        if svg_points
        else ""
    )

    # Returns table
    returns_html = _returns_table(data, labels)

    # 2-column: allocation + holdings
    alloc_html = allocation_bars(_alloc_blocks(data), width=200)
    top_8 = _holdings_table(data.holdings, labels, limit=8)

    grid = (
        f'<div style="display:grid;grid-template-columns:220px 1fr;gap:16px;margin:10px 0">'
        f"<div>"
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:.03em;margin-bottom:6px">{_e(labels["allocation"])}</div>'
        f"{alloc_html}</div>"
        f"<div>"
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:.03em;margin-bottom:6px">{_e(labels["top_holdings"])}</div>'
        f"{top_8}</div>"
        f"</div>"
    )

    # Risk cards
    risk = _risk_cards(data, labels)

    # Manager commentary
    commentary = ""
    if data.manager_commentary:
        commentary = (
            f'<div style="margin-top:8px">'
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.03em;margin-bottom:4px">{_e(labels["manager_commentary"])}</div>'
            f'<p style="font-size:9px;line-height:1.5;color:#374151">'
            f"{_e(data.manager_commentary)}</p></div>"
        )

    total_pages = 2 if len(data.holdings) > 8 else 1

    return (
        f'<div class="page">'
        f"{header}"
        f'<div style="padding:0 24px">'
        f"{kpi}"
        f"{chart_section}"
        f'<div style="margin:8px 0">{returns_html}</div>'
        f"{grid}"
        f"{risk}"
        f"{commentary}"
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
            f'<div style="margin-top:12px;padding:10px;background:#FFFBEB;'
            f'border-left:3px solid #D97706;border-radius:0 4px 4px 0;'
            f'font-size:9px;color:#92400E">'
            f"{_e(labels['backtest_note'])}</div>"
        )

    return (
        f'<div class="page">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:14px 24px 10px;border-bottom:1px solid #e5e7eb;margin-bottom:12px">'
        f'<span style="font-size:11px;font-weight:600;color:#111827">'
        f"{_e(data.portfolio_name)}</span>"
        f'<span style="font-size:9px;color:#9ca3af">p.&nbsp;2 of 2</span>'
        f"</div>"
        f'<div style="padding:0 24px">'
        f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:.03em;margin-bottom:6px">'
        f'{_e(labels["top_holdings"])} ({_e(labels["weight"])})</div>'
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
