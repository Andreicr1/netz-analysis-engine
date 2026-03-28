"""Monthly Client Report HTML template (4-page A4, rendered via Playwright).

Receives a ``MonthlyReportData`` dataclass and returns a self-contained HTML
string ready for ``page.set_content()`` + ``page.pdf()``.

All user-supplied text is escaped via ``html.escape()``.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Any

from vertical_engines.wealth.monthly_report.models import MonthlyReportData
from vertical_engines.wealth.pdf.svg_charts import (
    DrawdownPoint,  # noqa: F401 — re-export for caller convenience
    NavPoint,  # noqa: F401
    allocation_bars,
    drawdown_chart,
    performance_line_chart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FONT_STACK = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def _e(text: Any) -> str:
    """Escape text for HTML output."""
    if text is None:
        return ""
    return html.escape(str(text))


def _pct(value: float | None, *, decimals: int = 2, sign: bool = True) -> str:
    """Format a float as a percentage string."""
    if value is None:
        return "n/a"
    fmt = f"{'+'if sign and value >= 0 else ''}{value * 100:.{decimals}f}%"
    return fmt


def _pct_color(value: float | None) -> str:
    """Return CSS color for positive/negative returns."""
    if value is None:
        return "#9ca3af"
    return "#6EE7B7" if value >= 0 else "#FCA5A5"


def _pct_color_dark(value: float | None) -> str:
    """Darker palette for light backgrounds."""
    if value is None:
        return "#9ca3af"
    return "#3B6D11" if value >= 0 else "#A32D2D"


def _bps(value: float | None) -> str:
    """Format basis points."""
    if value is None:
        return "n/a"
    v = value * 10_000
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.0f} bps"


def _regime_pill(regime: str) -> str:
    """Render a regime indicator pill."""
    colors = {
        "NORMAL": ("#6EE7B7", "#064E3B"),
        "RISK_OFF": ("#FDE68A", "#78350F"),
        "CRISIS": ("#FCA5A5", "#7F1D1D"),
    }
    bg, fg = colors.get(regime.upper(), ("#e5e7eb", "#374151"))
    return (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:10px;'
        f"font-size:9px;font-weight:600;letter-spacing:.06em;"
        f"border:1px solid #2D3F5E;background:{bg};color:{fg};"
        f'">{_e(regime)}</span>'
    )


def _status_badge(status: str) -> str:
    """Render a status badge for holdings."""
    styles = {
        "Core": "background:#D1FAE5;color:#065F46",
        "New": "background:#DBEAFE;color:#1E40AF",
        "Reduced": "background:#FEF3C7;color:#92400E",
    }
    st = styles.get(status, "background:#f3f4f6;color:#374151")
    return (
        f'<span style="display:inline-block;padding:1px 7px;border-radius:8px;'
        f'font-size:8px;font-weight:600;{st}">{_e(status)}</span>'
    )


def _urgency_color(urgency: str) -> str:
    """Border color for watch item urgency."""
    return "#F59E0B" if urgency == "monitor" else "#9ca3af"


def _urgency_dot(urgency: str) -> str:
    """Colored dot for watch items."""
    c = "#F59E0B" if urgency == "monitor" else "#9ca3af"
    return f'<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:{c};margin-right:5px;vertical-align:middle"></span>'


def _urgency_label(urgency: str) -> str:
    return "Monitor" if urgency == "monitor" else "Track"


def _short_month(as_of: date) -> str:
    return as_of.strftime("%b %Y")


def _page_footer(as_of: date, page: int, total: int = 4, *, backtest: bool = False) -> str:
    """Render page footer with legal text."""
    bt = ' <span style="color:#D97706">*Inception period uses backtested data.</span>' if backtest else ""
    return (
        f'<div style="position:absolute;bottom:0;left:0;right:0;padding:10px 24px;'
        f"font-size:8px;color:#9ca3af;border-top:1px solid #e5e7eb;"
        f'display:flex;justify-content:space-between;align-items:center">'
        f"<span>Confidential. For institutional use only. Not investment advice.{bt}</span>"
        f"<span>{_short_month(as_of)} &middot; p.&nbsp;{page} of {total}</span>"
        f"</div>"
    )


def _page_header(portfolio_name: str, as_of: date, page: int, total: int = 4) -> str:
    """Render a light page header for pages 2-4."""
    return (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:14px 24px 10px;border-bottom:1px solid #e5e7eb;margin-bottom:12px">'
        f'<span style="font-size:11px;font-weight:600;color:#111827">{_e(portfolio_name)}</span>'
        f'<span style="font-size:9px;color:#9ca3af">'
        f"{_short_month(as_of)} &middot; p.&nbsp;{page} of {total}</span>"
        f"</div>"
    )


def _section_title(title: str) -> str:
    return (
        f'<div style="font-size:11px;font-weight:700;color:#111827;'
        f'letter-spacing:.03em;margin-bottom:8px;text-transform:uppercase">'
        f"{_e(title)}</div>"
    )


def _prose(text: str) -> str:
    """Render a paragraph of narrative text."""
    return (
        f'<p style="font-size:10px;line-height:1.55;color:#374151;margin:0 0 8px">'
        f"{_e(text)}</p>"
    )


def _activity_card(ticker: str, action: str, narrative: str) -> str:
    """Render a portfolio activity card."""
    action_colors = {
        "Added": ("#D1FAE5", "#065F46"),
        "Trimmed": ("#FEF3C7", "#92400E"),
        "Removed": ("#FEE2E2", "#991B1B"),
    }
    bg, fg = action_colors.get(action, ("#f3f4f6", "#374151"))
    return (
        f'<div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:6px">'
        f'<span style="display:inline-block;padding:2px 8px;border-radius:8px;'
        f"font-size:9px;font-weight:600;white-space:nowrap;"
        f'background:{bg};color:{fg}">{_e(action)}</span>'
        f'<div style="font-size:10px;color:#374151;line-height:1.45">'
        f'<span style="font-weight:600;font-family:monospace;font-size:9px;'
        f'color:#111827">{_e(ticker)}</span> '
        f"{_e(narrative)}</div></div>"
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = f"""
@page {{
    size: A4;
    margin: 0;
}}
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}
html, body {{
    font-family: {_FONT_STACK};
    font-size: 10px;
    color: #374151;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}
.page {{
    width: 210mm;
    height: 297mm;
    position: relative;
    overflow: hidden;
    page-break-after: always;
}}
.page:last-child {{
    page-break-after: auto;
}}
table {{
    border-collapse: collapse;
    width: 100%;
}}
th {{
    font-size: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: #6b7280;
    text-align: left;
    padding: 5px 6px;
    border-bottom: 1px solid #d1d5db;
}}
td {{
    font-size: 9px;
    padding: 4px 6px;
    border-bottom: 1px solid #f3f4f6;
    color: #374151;
}}
"""


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _page_cover(data: MonthlyReportData) -> str:
    """Page 1 — Cover with narrative, sidebar, allocations."""

    # Performance strip columns
    def _perf_col(label: str, port_val: float, bm_val: float, *, border_left: bool = False) -> str:
        bl = "border-left:1px solid #2D3F5E;padding-left:16px;" if border_left else ""
        return (
            f'<div style="{bl}">'
            f'<div style="font-size:8px;color:#6B7FA8;text-transform:uppercase;'
            f'letter-spacing:.08em;margin-bottom:3px">{label}</div>'
            f'<div style="font-size:16px;font-weight:600;color:{_pct_color(port_val)}">'
            f"{_pct(port_val)}</div>"
            f'<div style="font-size:9px;color:#4B5E7A;margin-top:1px">'
            f"BM {_pct(bm_val)}</div>"
            f"</div>"
        )

    perf_strip = (
        '<div style="display:flex;gap:20px;padding:12px 0">'
        + _perf_col("Month", data.month_return, data.month_bm_return)
        + _perf_col("YTD", data.ytd_return, data.ytd_bm_return, border_left=True)
        + _perf_col("Since Inception", data.inception_return, data.inception_bm_return, border_left=True)
        + "</div>"
    )

    # Header
    header = (
        f'<div style="background:#111827;padding:22px 24px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
        f"<div>"
        f'<div style="font-size:9px;letter-spacing:.14em;color:#6B7FA8;'
        f'text-transform:uppercase;margin-bottom:4px">Monthly Portfolio Report</div>'
        f'<div style="font-size:20px;font-weight:500;color:#F9FAFB;margin-bottom:2px">'
        f"{_e(data.portfolio_name)}</div>"
        f'<div style="font-size:12px;color:#6B7FA8">{_e(data.report_month)}</div>'
        f"</div>"
        f"<div>{_regime_pill(data.regime)}</div>"
        f"</div>"
        f"{perf_strip}"
        f"</div>"
    )

    # Sidebar — snapshot KVs
    kv_rows = ""
    for k, v in (data.snapshot_kv or {}).items():
        kv_rows += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:3px 0;font-size:9px;border-bottom:1px solid #f3f4f6">'
            f'<span style="color:#6b7280">{_e(k)}</span>'
            f'<span style="font-weight:600;color:#111827">{_e(v)}</span>'
            f"</div>"
        )

    # Allocation bars
    alloc_dicts = [{"label": a.label, "weight": a.weight, "color": a.color} for a in data.allocations]
    alloc_html = allocation_bars(alloc_dicts, width=170)

    # Core holdings sidebar
    core_rows = ""
    for h in data.core_holdings:
        core_rows += (
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'padding:3px 0;font-size:9px;border-bottom:1px solid #f3f4f6">'
            f'<span style="font-family:monospace;font-size:8px;color:#111827;'
            f'font-weight:600">{_e(h.ticker)}</span>'
            f'<span style="color:#6b7280">{h.weight * 100:.1f}%</span>'
            f"</div>"
        )

    # Watch items sidebar
    watch_html = ""
    for wi in data.watch_items:
        watch_html += (
            f'<div style="font-size:9px;color:#374151;padding:2px 0">'
            f"{_urgency_dot(wi.urgency)}{_e(wi.text)}</div>"
        )

    sidebar = (
        f'<div>'
        f'{_section_title("Portfolio Snapshot")}'
        f'<div style="margin-bottom:12px">{kv_rows}</div>'
        f'{_section_title("Allocation")}'
        f'<div style="margin-bottom:12px">{alloc_html}</div>'
        f'{_section_title("Core Holdings")}'
        f'<div style="margin-bottom:12px">{core_rows}</div>'
        f'{_section_title("Watch Items")}'
        f"{watch_html}"
        f"</div>"
    )

    # Activities
    activities_html = ""
    for act in data.portfolio_activities:
        activities_html += _activity_card(act.ticker, act.action, act.narrative)

    # Main column
    main_col = (
        f'{_section_title("Manager&rsquo;s Note")}'
        f"{_prose(data.manager_note)}"
        f'{_section_title("Macro Commentary")}'
        f"{_prose(data.macro_commentary)}"
        f'{_section_title("Portfolio Activity")}'
        f"{_prose(data.portfolio_activity_intro)}"
        f'<div style="margin:6px 0 10px">{activities_html}</div>'
        f'{_section_title("Looking Ahead")}'
        f"{_prose(data.forward_positioning)}"
    )

    body = (
        f'<div style="display:grid;grid-template-columns:1fr 200px;gap:18px;padding:14px 24px">'
        f"<div>{main_col}</div>"
        f"{sidebar}"
        f"</div>"
    )

    return (
        f'<div class="page">'
        f"{header}"
        f"{body}"
        f"{_page_footer(data.as_of, 1, backtest=data.is_backtest)}"
        f"</div>"
    )


def _page_performance(data: MonthlyReportData) -> str:
    """Page 2 — Cumulative chart, trailing returns table, period strip."""

    chart_svg = performance_line_chart(data.nav_series, width=580, height=180)

    legend = (
        '<div style="display:flex;gap:14px;margin:6px 0 10px;font-size:9px;color:#6b7280">'
        '<span><svg width="16" height="2" style="vertical-align:middle">'
        '<line x1="0" y1="1" x2="16" y2="1" stroke="#185FA5" stroke-width="1.8"/></svg>'
        " Portfolio</span>"
        '<span><svg width="16" height="2" style="vertical-align:middle">'
        '<line x1="0" y1="1" x2="16" y2="1" stroke="#9ca3af" stroke-width="1" '
        'stroke-dasharray="4 3"/></svg>'
        " Benchmark</span>"
        "</div>"
    )

    # Monthly returns table — trailing 12 months
    m_headers = "".join(
        f'<th style="text-align:center;padding:4px 3px;font-size:7px;'
        f'{"font-weight:700" if i == len(data.monthly_returns) - 1 else ""}'
        f'">{_e(r.period_label)}</th>'
        for i, r in enumerate(data.monthly_returns)
    )

    def _ret_cell(val: float | None, *, bold: bool = False) -> str:
        if val is None:
            return '<td style="text-align:center;font-size:8px;color:#d1d5db">—</td>'
        c = _pct_color_dark(val)
        fw = "font-weight:600;" if bold else ""
        return (
            f'<td style="text-align:center;font-size:8px;color:{c};{fw}">'
            f"{_pct(val, decimals=1)}</td>"
        )

    port_cells = "".join(
        _ret_cell(r.portfolio_return, bold=(i == len(data.monthly_returns) - 1))
        for i, r in enumerate(data.monthly_returns)
    )
    bm_cells = "".join(
        _ret_cell(r.benchmark_return, bold=(i == len(data.monthly_returns) - 1))
        for i, r in enumerate(data.monthly_returns)
    )
    active_cells = ""
    for i, r in enumerate(data.monthly_returns):
        if r.portfolio_return is not None and r.benchmark_return is not None:
            diff = r.portfolio_return - r.benchmark_return
            active_cells += _ret_cell(diff, bold=(i == len(data.monthly_returns) - 1))
        else:
            active_cells += '<td style="text-align:center;font-size:8px;color:#d1d5db">—</td>'

    returns_table = (
        f"<table>"
        f"<thead><tr><th style='width:60px;font-size:7px'>Period</th>{m_headers}</tr></thead>"
        f"<tbody>"
        f'<tr><td style="font-size:8px;font-weight:600">Portfolio</td>{port_cells}</tr>'
        f'<tr><td style="font-size:8px;font-weight:600">Benchmark</td>{bm_cells}</tr>'
        f'<tr style="border-top:1px solid #d1d5db">'
        f'<td style="font-size:8px;font-weight:600">Active</td>{active_cells}</tr>'
        f"</tbody></table>"
    )

    # Cumulative period strip
    period_keys = ["1m", "3m", "ytd", "1y", "itd"]
    period_labels = {"1m": "1M", "3m": "3M", "ytd": "YTD", "1y": "1Y", "itd": "ITD"}
    strip_cols = ""
    for pk in period_keys:
        vals = data.trailing_periods.get(pk, {})
        p_val = vals.get("portfolio")
        b_val = vals.get("benchmark")
        strip_cols += (
            f'<div style="text-align:center;flex:1;'
            f'{"border-left:1px solid #e5e7eb;" if pk != "1m" else ""}'
            f'padding:8px 4px">'
            f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:3px">{period_labels.get(pk, pk)}</div>'
            f'<div style="font-size:13px;font-weight:600;'
            f'color:{_pct_color_dark(p_val)}">{_pct(p_val)}</div>'
            f'<div style="font-size:9px;color:#9ca3af;margin-top:1px">'
            f"BM {_pct(b_val)}</div></div>"
        )

    period_strip = (
        f'<div style="display:flex;background:#f9fafb;border-radius:6px;'
        f'margin:10px 0">{strip_cols}</div>'
    )

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, 2)}"
        f'<div style="padding:0 24px">'
        f'{_section_title("Cumulative Performance")}'
        f'<div style="margin:4px 0 6px">{chart_svg}</div>'
        f"{legend}"
        f'{_section_title("Monthly Returns &mdash; Trailing 12 Months")}'
        f'<div style="margin:4px 0">{returns_table}</div>'
        f"{period_strip}"
        f"</div>"
        f'{_page_footer(data.as_of, 2, backtest=data.is_backtest)}'
        f"</div>"
    )


def _page_attribution_risk(data: MonthlyReportData) -> str:
    """Page 3 — Attribution table + risk metrics + drawdown chart."""

    # Attribution section
    attr_rows = ""
    for row in data.attribution_rows:
        alloc_v = row.get("allocation", 0.0)
        sel_v = row.get("selection", 0.0)
        tot_v = row.get("total", 0.0)
        attr_rows += (
            f"<tr>"
            f'<td style="font-weight:500">{_e(row.get("block_name", ""))}</td>'
            f'<td style="text-align:right;color:{_pct_color_dark(alloc_v)}">'
            f"{_pct(alloc_v, decimals=1)}</td>"
            f'<td style="text-align:right;color:{_pct_color_dark(sel_v)}">'
            f"{_pct(sel_v, decimals=1)}</td>"
            f'<td style="text-align:right;font-weight:600;color:{_pct_color_dark(tot_v)}">'
            f"{_pct(tot_v, decimals=1)}</td>"
            f"</tr>"
        )

    total_a = data.attribution_total.get("allocation", 0.0)
    total_s = data.attribution_total.get("selection", 0.0)
    total_t = data.attribution_total.get("total", 0.0)

    attr_table = (
        f"<table>"
        f"<thead><tr>"
        f"<th>Asset Block</th>"
        f'<th style="text-align:right">Allocation</th>'
        f'<th style="text-align:right">Selection</th>'
        f'<th style="text-align:right">Total Contribution</th>'
        f"</tr></thead>"
        f"<tbody>{attr_rows}</tbody>"
        f"<tfoot><tr style='border-top:1.5px solid #111827'>"
        f'<td style="font-weight:700">Total</td>'
        f'<td style="text-align:right;font-weight:700;color:{_pct_color_dark(total_a)}">'
        f"{_pct(total_a, decimals=1)}</td>"
        f'<td style="text-align:right;font-weight:700;color:{_pct_color_dark(total_s)}">'
        f"{_pct(total_s, decimals=1)}</td>"
        f'<td style="text-align:right;font-weight:700;color:{_pct_color_dark(total_t)}">'
        f"{_pct(total_t, decimals=1)}</td>"
        f"</tr></tfoot>"
        f"</table>"
    )

    attribution_section = (
        f'{_section_title("Attribution — Brinson-Fachler")}'
        f"{_prose(data.attribution_narrative)}"
        f'<div style="margin:6px 0">{attr_table}</div>'
        f'<div style="font-size:8px;color:#9ca3af;margin-bottom:14px">'
        f"Attribution decomposes active return into allocation and selection effects "
        f"relative to policy benchmark.</div>"
    )

    # Risk metrics cards
    def _risk_card(label: str, value: float | None, fmt_fn: Any) -> str:
        display = fmt_fn(value) if value is not None else "n/a"
        return (
            f'<div style="background:#f9fafb;border-radius:6px;padding:10px;text-align:center">'
            f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase;'
            f'letter-spacing:.06em;margin-bottom:4px">{label}</div>'
            f'<div style="font-size:16px;font-weight:700;color:#111827">{display}</div>'
            f"</div>"
        )

    def _fmt_vol(v: float) -> str:
        return f"{v * 100:.1f}%"

    def _fmt_sharpe(v: float) -> str:
        return f"{v:.2f}"

    def _fmt_dd(v: float) -> str:
        return f"{v * 100:.2f}%"

    def _fmt_cvar(v: float) -> str:
        return f"{v * 100:.2f}%"

    risk_cards = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:6px 0">'
        f'{_risk_card("Volatility", data.volatility, _fmt_vol)}'
        f'{_risk_card("Sharpe", data.sharpe, _fmt_sharpe)}'
        f'{_risk_card("Max Drawdown", data.max_drawdown, _fmt_dd)}'
        f'{_risk_card("CVaR 95", data.cvar_95, _fmt_cvar)}'
        f"</div>"
    )

    # Drawdown chart
    dd_svg = drawdown_chart(data.drawdown_series, width=260, height=140)

    # Stress table
    stress_rows = ""
    for sc in data.stress_scenarios:
        pr = sc.get("portfolio_return", 0.0)
        md = sc.get("max_drawdown", 0.0)
        stress_rows += (
            f"<tr>"
            f'<td style="font-weight:500">{_e(sc.get("name", ""))}</td>'
            f'<td style="text-align:right;color:{_pct_color_dark(pr)}">'
            f"{_pct(pr, decimals=1)}</td>"
            f'<td style="text-align:right;color:{_pct_color_dark(md)}">'
            f"{_pct(md, decimals=1)}</td>"
            f"</tr>"
        )

    stress_table = (
        f'<table style="font-size:9px;margin-top:8px">'
        f"<thead><tr>"
        f"<th>Scenario</th>"
        f'<th style="text-align:right">Portfolio</th>'
        f'<th style="text-align:right">Max DD</th>'
        f"</tr></thead>"
        f"<tbody>{stress_rows}</tbody>"
        f"</table>"
    )

    risk_section = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">'
        f"<div>"
        f'{_section_title("Risk Metrics")}'
        f"{_prose(data.risk_narrative)}"
        f"{risk_cards}"
        f"</div>"
        f"<div>"
        f'{_section_title("Drawdown Profile")}'
        f'<div style="margin:4px 0">{dd_svg}</div>'
        f'{_section_title("Simulated Stress Scenarios")}'
        f"{stress_table}"
        f"</div>"
        f"</div>"
    )

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, 3)}"
        f'<div style="padding:0 24px">'
        f"{attribution_section}"
        f"{risk_section}"
        f"</div>"
        f"{_page_footer(data.as_of, 3, backtest=data.is_backtest)}"
        f"</div>"
    )


def _page_holdings_outlook(data: MonthlyReportData) -> str:
    """Page 4 — Full holdings table + forward positioning + watchpoints."""

    # Holdings table
    h_rows = ""
    for h in data.all_holdings:
        yr_ret = _pct(h.one_year_return, decimals=1) if h.one_year_return is not None else "n/a"
        yr_color = _pct_color_dark(h.one_year_return)
        er = f"{h.expense_ratio * 100:.2f}%" if h.expense_ratio is not None else "n/a"
        h_rows += (
            f"<tr>"
            f'<td style="font-weight:500">{_e(h.fund_name)}</td>'
            f'<td style="font-size:8px;color:#6b7280">{_e(h.strategy)}</td>'
            f'<td style="text-align:right">{h.weight * 100:.1f}%</td>'
            f'<td style="text-align:right;color:{yr_color}">{yr_ret}</td>'
            f'<td style="text-align:right;color:#6b7280">{er}</td>'
            f"<td>{_status_badge(h.status)}</td>"
            f"</tr>"
        )

    holdings_table = (
        f"<table>"
        f"<thead><tr>"
        f"<th>Fund</th>"
        f"<th>Strategy</th>"
        f'<th style="text-align:right">Weight</th>'
        f'<th style="text-align:right">1Y Return</th>'
        f'<th style="text-align:right">Exp. Ratio</th>'
        f"<th>Status</th>"
        f"</tr></thead>"
        f"<tbody>{h_rows}</tbody>"
        f"</table>"
    )

    # Forward positioning — split into paragraphs
    fwd_paragraphs = ""
    for para in data.forward_positioning.split("\n\n"):
        stripped = para.strip()
        if stripped:
            fwd_paragraphs += _prose(stripped)

    # Watchpoints
    wp_cards = ""
    for wp in data.watchpoints:
        border_c = _urgency_color(wp.urgency)
        label = _urgency_label(wp.urgency)
        wp_cards += (
            f'<div style="border-left:3px solid {border_c};padding:6px 10px;'
            f'margin-bottom:6px;background:#fafafa;border-radius:0 4px 4px 0">'
            f'<div style="font-size:8px;font-weight:600;color:{border_c};'
            f'text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">'
            f"{label}</div>"
            f'<div style="font-size:9px;color:#374151;line-height:1.45">'
            f"{_e(wp.text)}</div>"
            f"</div>"
        )

    bottom_grid = (
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">'
        f"<div>"
        f'{_section_title("Forward Positioning")}'
        f"{fwd_paragraphs}"
        f"</div>"
        f"<div>"
        f'{_section_title("Key Watchpoints Q2")}'
        f"{wp_cards}"
        f"</div>"
        f"</div>"
    )

    # Disclosure footer
    disclosure = (
        '<div style="margin-top:14px;padding:10px;background:#f9fafb;'
        'border-radius:4px;font-size:8px;color:#9ca3af;line-height:1.5">'
        "This report is generated for institutional investors and qualified "
        "purchasers only. Past performance does not guarantee future results. "
        "All returns are net of management fees unless otherwise stated. "
        "Risk metrics are based on historical data and may not reflect future "
        "conditions. Simulated stress scenarios are hypothetical and do not "
        "represent actual losses. Portfolio allocations are subject to change "
        "without notice."
        "</div>"
    )

    return (
        f'<div class="page">'
        f"{_page_header(data.portfolio_name, data.as_of, 4)}"
        f'<div style="padding:0 24px">'
        f'{_section_title("Holdings")}'
        f'<div style="margin:4px 0 8px">{holdings_table}</div>'
        f"{bottom_grid}"
        f"{disclosure}"
        f"</div>"
        f"{_page_footer(data.as_of, 4, backtest=data.is_backtest)}"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_monthly_client(data: MonthlyReportData, *, language: str = "en") -> str:
    """Render the 4-page Monthly Client Report as a self-contained HTML string.

    Parameters
    ----------
    data:
        Fully-populated ``MonthlyReportData`` dataclass.
    language:
        ISO language code (reserved for future i18n; currently only ``"en"``).

    Returns
    -------
    str
        Complete HTML document ready for Playwright ``page.set_content()``
        followed by ``page.pdf()``.
    """
    pages = (
        _page_cover(data)
        + _page_performance(data)
        + _page_attribution_risk(data)
        + _page_holdings_outlook(data)
    )

    return (
        f"<!DOCTYPE html>"
        f'<html lang="{_e(language)}">'
        f"<head>"
        f'<meta charset="utf-8"/>'
        f"<title>{_e(data.portfolio_name)} &mdash; Monthly Report "
        f"{_e(data.report_month)}</title>"
        f"<style>{_CSS}</style>"
        f"</head>"
        f"<body>{pages}</body>"
        f"</html>"
    )
