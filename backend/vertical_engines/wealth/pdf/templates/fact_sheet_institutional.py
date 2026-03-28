"""Fact Sheet Institutional HTML template (4-6 page A4, rendered via Playwright).

Extends the Executive layout with attribution, stress scenarios, regime overlay,
and fee drag analysis. Receives ``FactSheetData`` with institutional-only fields.

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

_REGIME_COLORS: dict[str, str] = {
    "expansion": "#059669",
    "contraction": "#D97706",
    "crisis": "#DC2626",
    "risk_off": "#D97706",
}

_REGIME_LABELS: dict[str, str] = {
    "expansion": "Expansion",
    "contraction": "Contraction",
    "crisis": "Crisis",
    "risk_off": "Risk Off",
}


def _e(text: Any) -> str:
    if text is None:
        return "&mdash;"
    return html.escape(str(text))


def _pct(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value * 100:+.{decimals}f}%"


def _pct_unsigned(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value * 100:.{decimals}f}%"


def _pct_color(value: float | None) -> str:
    if value is None:
        return "#9ca3af"
    return "#059669" if value >= 0 else "#DC2626"


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
# Shared components
# ---------------------------------------------------------------------------

_ALLOC_COLORS = [
    "#185FA5", "#1D9E75", "#639922", "#BA7517",
    "#888780", "#D44C47", "#6366F1", "#EC4899",
]


def _section_title(title: str) -> str:
    return (
        f'<div style="font-size:10px;font-weight:700;color:#111827;'
        f'letter-spacing:.03em;margin-bottom:6px;text-transform:uppercase">'
        f"{_e(title)}</div>"
    )


def _page_header(name: str, as_of: date, page: int, total: int) -> str:
    return (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:14px 24px 10px;border-bottom:1px solid #e5e7eb;margin-bottom:12px">'
        f'<span style="font-size:11px;font-weight:600;color:#111827">{_e(name)}</span>'
        f'<span style="font-size:9px;color:#9ca3af">'
        f"p.&nbsp;{page} of {total}</span>"
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
            "label": a.block_id.replace("_", " ").title(),
            "weight": a.weight,
            "color": _ALLOC_COLORS[i % len(_ALLOC_COLORS)],
        }
        for i, a in enumerate(data.allocations)
    ]


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
        f"{active_row[4:]}"
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
            f'<td style="font-weight:500">{_e(a.block_name)}</td>'
            f'<td style="text-align:right">{_pct(a.allocation_effect, decimals=3)}</td>'
            f'<td style="text-align:right">{_pct(a.selection_effect, decimals=3)}</td>'
            f'<td style="text-align:right">{_pct(a.interaction_effect, decimals=3)}</td>'
            f'<td style="text-align:right;font-weight:600;color:{color_te}">'
            f"{_pct(a.total_effect, decimals=3)}</td>"
            f"</tr>"
        )
        tot_alloc += a.allocation_effect
        tot_sel += a.selection_effect
        tot_inter += a.interaction_effect
        tot_total += a.total_effect

    footer = (
        f'<tfoot><tr style="border-top:1.5px solid #111827">'
        f'<td style="font-weight:700">Total</td>'
        f'<td style="text-align:right;font-weight:700">{_pct(tot_alloc, decimals=3)}</td>'
        f'<td style="text-align:right;font-weight:700">{_pct(tot_sel, decimals=3)}</td>'
        f'<td style="text-align:right;font-weight:700">{_pct(tot_inter, decimals=3)}</td>'
        f'<td style="text-align:right;font-weight:700;color:{_pct_color(tot_total)}">'
        f"{_pct(tot_total, decimals=3)}</td>"
        f"</tr></tfoot>"
    )

    return (
        f"<table><thead><tr>"
        f"<th>{_e(labels['block_name'])}</th>"
        f'<th style="text-align:right">{_e(labels["allocation_effect"])}</th>'
        f'<th style="text-align:right">{_e(labels["selection_effect"])}</th>'
        f'<th style="text-align:right">{_e(labels["interaction_effect"])}</th>'
        f'<th style="text-align:right">{_e(labels["total_effect"])}</th>'
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
            f'<td style="font-weight:500">{_e(s.name)}</td>'
            f'<td style="text-align:center;font-size:8px;color:#6b7280">'
            f"{s.start_date.strftime('%b %Y')} &ndash; {s.end_date.strftime('%b %Y')}</td>"
            f'<td style="text-align:right;color:{pr_color}">{_pct(s.portfolio_return)}</td>'
            f'<td style="text-align:right;color:{dd_color}">{_pct(s.max_drawdown)}</td>'
            f"</tr>"
        )

    return (
        f"<table><thead><tr>"
        f"<th>{_e(labels['scenario'])}</th>"
        f'<th style="text-align:center">{_e(labels["period"])}</th>'
        f'<th style="text-align:right">{_e(labels["portfolio_return"])}</th>'
        f'<th style="text-align:right">{_e(labels["max_drawdown"])}</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Regime overlay
# ---------------------------------------------------------------------------


def _regime_overlay(data: FactSheetData, labels: dict[str, str]) -> str:
    if not data.regimes:
        return ""

    bars = ""
    for r in data.regimes:
        color = _REGIME_COLORS.get(r.regime, "#9ca3af")
        label = _REGIME_LABELS.get(r.regime, r.regime)
        bars += (
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">'
            f'<div style="width:12px;height:12px;border-radius:2px;background:{color}"></div>'
            f'<span style="font-size:9px;color:#374151">'
            f"{r.regime_date.strftime('%b %Y')} &mdash; {_e(label)}</span>"
            f"</div>"
        )

    return (
        f'<div style="margin:8px 0">'
        f"{_section_title(labels['regime_chart_title'])}"
        f"{bars}</div>"
    )


# ---------------------------------------------------------------------------
# Fee drag section
# ---------------------------------------------------------------------------


def _fee_drag_section(data: FactSheetData, labels: dict[str, str]) -> str:
    fd = data.fee_drag
    if not fd:
        return ""

    # Summary cards
    summary = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;margin:6px 0">'
        f'<div style="background:#f9fafb;border-radius:6px;padding:8px;text-align:center">'
        f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">'
        f'{_e(labels["fd_instruments"])}</div>'
        f'<div style="font-size:13px;font-weight:700;color:#111827">'
        f'{fd.get("total_instruments", 0)}</div></div>'
        f'<div style="background:#f9fafb;border-radius:6px;padding:8px;text-align:center">'
        f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">'
        f'{_e(labels["fd_gross_return"])}</div>'
        f'<div style="font-size:13px;font-weight:700;color:#111827">'
        f'{_pct_unsigned(fd.get("weighted_gross_return"))}</div></div>'
        f'<div style="background:#f9fafb;border-radius:6px;padding:8px;text-align:center">'
        f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">'
        f'{_e(labels["fd_net_return"])}</div>'
        f'<div style="font-size:13px;font-weight:700;color:#111827">'
        f'{_pct_unsigned(fd.get("weighted_net_return"))}</div></div>'
        f'<div style="background:#f9fafb;border-radius:6px;padding:8px;text-align:center">'
        f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em">'
        f'{_e(labels["fd_drag_ratio"])}</div>'
        f'<div style="font-size:13px;font-weight:700;color:#DC2626">'
        f'{_pct_unsigned(fd.get("weighted_fee_drag_pct"))}</div></div>'
        f"</div>"
    )

    # Per-fund table
    instruments = fd.get("instruments", [])
    rows = ""
    for inst in instruments:
        fb = inst.get("fee_breakdown", {})
        eff = inst.get("fee_efficient", True)
        status_bg = "#D1FAE5" if eff else "#FEE2E2"
        status_fg = "#065F46" if eff else "#991B1B"
        status_text = labels["fc_efficient"] if eff else labels["fc_inefficient"]
        rows += (
            f"<tr>"
            f'<td style="font-weight:500">{_e(inst.get("name", ""))}</td>'
            f'<td style="text-align:right">{_pct_unsigned(fb.get("management"))}</td>'
            f'<td style="text-align:right">{_pct_unsigned(fb.get("performance"))}</td>'
            f'<td style="text-align:right">{_pct_unsigned(fb.get("other"))}</td>'
            f'<td style="text-align:right;font-weight:600">{_pct_unsigned(fb.get("total"))}</td>'
            f'<td style="text-align:right;color:#DC2626">{_pct_unsigned(inst.get("fee_drag_pct"))}</td>'
            f'<td><span style="display:inline-block;padding:1px 6px;border-radius:8px;'
            f"font-size:8px;font-weight:600;background:{status_bg};color:{status_fg}"
            f'">{_e(status_text)}</span></td>'
            f"</tr>"
        )

    table = (
        f"<table><thead><tr>"
        f"<th>{_e(labels['fc_fund'])}</th>"
        f'<th style="text-align:right">{_e(labels["fc_mgmt_fee"])}</th>'
        f'<th style="text-align:right">{_e(labels["fc_perf_fee"])}</th>'
        f'<th style="text-align:right">{_e(labels["fc_other_fee"])}</th>'
        f'<th style="text-align:right">{_e(labels["fc_total_fee"])}</th>'
        f'<th style="text-align:right">{_e(labels["fc_drag"])}</th>'
        f"<th>{_e(labels['fc_status'])}</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    ) if instruments else ""

    return (
        f"{_section_title(labels['fee_drag_analysis'])}"
        f"{summary}"
        f'<div style="margin-top:8px">{_section_title(labels["fee_comparison"])}</div>'
        f"{table}"
    )


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _compute_total_pages(data: FactSheetData) -> int:
    pages = 2  # page 1 (header+KPI+chart+returns) + page 2 (alloc+holdings+risk)
    if data.attribution:
        pages += 1  # page 3: attribution
    has_stress_or_regime_or_fee = data.stress or data.regimes or data.fee_drag
    if has_stress_or_regime_or_fee:
        pages += 1  # page 4: risk deep-dive
    if data.fee_drag and data.fee_drag.get("instruments"):
        if len(data.fee_drag.get("instruments", [])) > 6:
            pages += 1  # page 5: fee comparison overflow
    return pages


def _page1_inst(data: FactSheetData, labels: dict[str, str], language: Language, total_pages: int) -> str:
    header = (
        f'<div style="background:#111827;padding:22px 24px">'
        f'<div style="font-size:9px;letter-spacing:.14em;color:#6B7FA8;'
        f'text-transform:uppercase;margin-bottom:4px">'
        f'{_e(labels["report_title_institutional"])} &middot; FACT SHEET</div>'
        f'<div style="font-size:20px;font-weight:500;color:#F9FAFB;margin-bottom:2px">'
        f"{_e(data.portfolio_name)}</div>"
        f'<div style="font-size:11px;color:#6B7FA8">'
        f'{_e(labels["as_of"])} {format_date(data.as_of, language)} &middot; '
        f'{_e(labels["profile"])}: {_e(data.profile.title())}</div>'
        f"</div>"
    )

    kpi = (
        f'<div style="display:flex;border-bottom:1px solid #e5e7eb">'
        f'{_kpi_card(labels["mtd"], data.returns.mtd)}'
        f'{_kpi_card(labels["ytd"], data.returns.ytd)}'
        f'{_kpi_card(labels["1y"], data.returns.one_year)}'
        f'{_kpi_card(labels["since_inception"], data.returns.since_inception)}'
        f"</div>"
    )

    svg_points = _to_svg_nav(data)
    chart = performance_line_chart(svg_points, width=540, height=150)
    legend = (
        '<div style="display:flex;gap:14px;margin:4px 0 6px;font-size:9px;color:#6b7280">'
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
        f'<div style="margin:6px 0">{chart}</div>{legend}'
        if svg_points
        else ""
    )

    returns_html = _returns_table(data, labels)

    return (
        f'<div class="page">'
        f"{header}"
        f'<div style="padding:0 24px">'
        f"{kpi}"
        f"{chart_section}"
        f'<div style="margin:8px 0">{returns_html}</div>'
        f"</div>"
        f"{_page_footer(data.as_of, 1, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page2_inst(data: FactSheetData, labels: dict[str, str], total_pages: int) -> str:
    alloc_html = allocation_bars(_alloc_blocks(data), width=200)
    holdings_html = _holdings_table(data.holdings, labels)
    risk = _risk_cards(data, labels)

    commentary = ""
    if data.manager_commentary:
        commentary = (
            f'<div style="margin-top:8px">'
            f"{_section_title(labels['manager_commentary'])}"
            f'<p style="font-size:9px;line-height:1.5;color:#374151">'
            f"{_e(data.manager_commentary)}</p></div>"
        )

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, 2, total_pages)}"
        f'<div style="padding:0 24px">'
        f'<div style="display:grid;grid-template-columns:220px 1fr;gap:16px;margin-bottom:10px">'
        f"<div>{_section_title(labels['allocation'])}{alloc_html}</div>"
        f"<div>{_section_title(labels['top_holdings'])}{holdings_html}</div>"
        f"</div>"
        f"{_section_title(labels['risk_metrics'])}"
        f"{risk}"
        f"{commentary}"
        f"</div>"
        f"{_page_footer(data.as_of, 2, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page_attribution(data: FactSheetData, labels: dict[str, str], page_num: int, total_pages: int) -> str:
    if not data.attribution:
        return ""

    table = _attribution_table(data, labels)

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, page_num, total_pages)}"
        f'<div style="padding:0 24px">'
        f"{_section_title(labels['attribution'])}"
        f'<div style="margin:6px 0">{table}</div>'
        f"</div>"
        f"{_page_footer(data.as_of, page_num, total_pages, labels, backtest=data.returns.is_backtest)}"
        f"</div>"
    )


def _page_risk_deepdive(data: FactSheetData, labels: dict[str, str], page_num: int, total_pages: int) -> str:
    parts: list[str] = []

    if data.stress:
        parts.append(_section_title(labels["stress_scenarios"]))
        parts.append(f'<div style="margin:6px 0">{_stress_table(data, labels)}</div>')

    if data.regimes:
        parts.append(_regime_overlay(data, labels))

    if data.fee_drag:
        parts.append(f'<div style="margin-top:10px">{_fee_drag_section(data, labels)}</div>')

    if not parts:
        return ""

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, page_num, total_pages)}"
        f'<div style="padding:0 24px">'
        f"{''.join(parts)}"
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
