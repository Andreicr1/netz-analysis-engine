"""Long-Form Due Diligence Report HTML template.

Renders a 4-page A4 PDF layout via Playwright.
Page 1: Cover with sidebar navigation + first chapter.
Pages 2-4: Remaining chapters (2-8) in full-width layout.

All CSS is inline. No external resources. html.escape() on every user string.
"""

from __future__ import annotations

import html
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from vertical_engines.wealth.long_form_report.models import LongFormReportData


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

_REGIME_COLORS: dict[str, str] = {
    "expansion": "#6EE7B7",
    "contraction": "#FCA5A5",
    "crisis": "#F87171",
    "risk_off": "#FCD34D",
}

_REGIME_LABELS: dict[str, str] = {
    "expansion": "Expansion",
    "contraction": "Contraction",
    "crisis": "Crisis",
    "risk_off": "Risk Off",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _esc(value: Any) -> str:
    """Escape a value for HTML output."""
    if value is None:
        return "&mdash;"
    return html.escape(str(value))


def _fmt_pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value:,.{decimals}f}%"


def _fmt_bps(value: float | None) -> str:
    if value is None:
        return "&mdash;"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:,.0f} bps"


def _fmt_number(value: float | int | None, decimals: int = 2) -> str:
    if value is None:
        return "&mdash;"
    return f"{value:,.{decimals}f}"


def _fmt_date(d: date) -> str:
    return d.strftime("%B %d, %Y")


def _chapter_content_text(content: dict[str, Any]) -> str:
    """Extract readable prose from a chapter content dict."""
    if not content:
        return ""

    # Priority keys that contain the main narrative
    for key in ("summary", "global_summary", "narrative", "overview", "analysis"):
        if key in content and isinstance(content[key], str):
            return html.escape(content[key])

    # Fall back: concatenate all string values
    parts: list[str] = []
    for _k, v in content.items():
        if isinstance(v, str) and v.strip():
            parts.append(html.escape(v))
    return "<br><br>".join(parts)


def _chapter_key_indicators(content: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract key indicators from a chapter content dict."""
    indicators: list[tuple[str, str]] = []
    for key in ("key_indicators", "indicators", "metrics", "key_metrics"):
        raw = content.get(key)
        if isinstance(raw, dict):
            for k, v in raw.items():
                label = k.replace("_", " ").title()
                indicators.append((label, _esc(v)))
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    label = item.get("label", item.get("name", ""))
                    val = item.get("value", "")
                    indicators.append((_esc(label), _esc(val)))
    return indicators


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
@page { size: A4; margin: 0; }
html, body {
    width: 210mm; min-height: 297mm;
    font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
    font-size: 12px; color: #1F2937; line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}

.page {
    width: 210mm; min-height: 297mm;
    position: relative;
    page-break-after: always;
    overflow: hidden;
}
.page:last-child { page-break-after: auto; }

/* ---------- Cover header ---------- */
.cover-header {
    background: #111827;
    padding: 20px 24px;
    display: flex; justify-content: space-between; align-items: flex-start;
}
.cover-header-left { flex: 1; }
.cover-label {
    font-size: 9px; letter-spacing: .12em;
    color: #6B7FA8; text-transform: uppercase;
    margin-bottom: 6px;
}
.cover-title {
    font-size: 22px; font-weight: 600;
    color: #F9FAFB; margin-bottom: 4px;
}
.cover-subtitle {
    font-size: 11px; color: #6B7FA8;
}
.regime-box {
    border: 0.5px solid #2D3F5E;
    border-radius: 6px;
    padding: 8px 14px;
    text-align: center;
    flex-shrink: 0;
    margin-left: 16px;
}
.regime-label {
    font-size: 8px; letter-spacing: .1em;
    color: #6B7FA8; text-transform: uppercase;
    margin-bottom: 2px;
}
.regime-value {
    font-size: 14px; font-weight: 600;
}

/* ---------- Cover body grid ---------- */
.cover-body {
    display: grid;
    grid-template-columns: 180px 1fr;
    min-height: calc(297mm - 88px);
}
.sidebar {
    background: #f9fafb;
    border-right: 0.5px solid #e5e7eb;
    padding: 16px 12px;
    font-size: 10px;
}
.sidebar-heading {
    font-size: 8px; font-weight: 700;
    letter-spacing: .1em; color: #6B7280;
    text-transform: uppercase;
    margin-bottom: 8px; margin-top: 14px;
}
.sidebar-heading:first-child { margin-top: 0; }
.toc-item {
    padding: 4px 8px;
    border-radius: 4px;
    margin-bottom: 2px;
    color: #374151;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.toc-item.active {
    background: #EFF6FF;
    color: #1D4ED8;
    font-weight: 500;
}
.stat-row {
    display: flex; justify-content: space-between;
    padding: 4px 0;
    border-bottom: 0.5px solid #e5e7eb;
}
.stat-label { color: #6B7280; font-size: 9px; }
.stat-value { font-weight: 600; font-size: 10px; color: #111827; }

.main-content {
    padding: 20px;
    display: flex; flex-direction: column;
}

/* ---------- Chapter header ---------- */
.chapter-header {
    border-left: 3px solid #185FA5;
    padding-left: 12px;
    margin-bottom: 14px;
}
.chapter-number {
    font-size: 9px; text-transform: uppercase;
    letter-spacing: .1em; color: #6B7280;
    margin-bottom: 2px;
}
.chapter-title {
    font-size: 16px; font-weight: 500;
    color: #111827;
}

/* ---------- Chapter body ---------- */
.chapter-body {
    font-size: 12px; line-height: 1.7;
    color: #374151; flex: 1;
}

/* ---------- Key indicators callout ---------- */
.key-indicators {
    background: #EFF6FF;
    border-left: 3px solid #185FA5;
    padding: 10px 14px;
    margin: 12px 0;
    display: flex; flex-wrap: wrap; gap: 16px;
}
.ki-item {}
.ki-label {
    font-size: 9px; color: #6B7280;
    text-transform: uppercase; letter-spacing: .05em;
}
.ki-value {
    font-size: 13px; font-weight: 600; color: #111827;
}

/* ---------- Tables ---------- */
.data-table {
    width: 100%; border-collapse: collapse;
    font-size: 10px; margin: 10px 0;
}
.data-table th {
    text-align: left; font-weight: 600;
    padding: 6px 8px; font-size: 9px;
    text-transform: uppercase; letter-spacing: .05em;
    color: #6B7280;
    border-bottom: 1px solid #D1D5DB;
}
.data-table td {
    padding: 5px 8px;
    border-bottom: 0.5px solid #e5e7eb;
    color: #374151;
}
.data-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.positive { color: #059669; }
.negative { color: #DC2626; }

/* ---------- Footer nav (cover) ---------- */
.footer-nav {
    border-top: 0.5px solid #e5e7eb;
    padding: 10px 0;
    display: flex; justify-content: space-between;
    font-size: 10px; color: #2563EB;
    margin-top: auto;
}
.footer-nav a { color: #2563EB; text-decoration: none; }

/* ---------- Page header (pages 2-4) ---------- */
.page-header {
    display: flex; justify-content: space-between;
    padding: 12px 24px;
    font-size: 11px; color: #6b7280;
    border-bottom: 0.5px solid #e5e7eb;
}

/* ---------- Page content (pages 2-4) ---------- */
.page-content {
    padding: 16px 24px;
}

/* ---------- Page footer ---------- */
.page-footer {
    position: absolute; bottom: 0; left: 0; right: 0;
    border-top: 0.5px solid #e5e7eb;
    padding: 8px 24px;
    display: flex; justify-content: space-between;
    font-size: 8px; color: #9CA3AF;
}

/* ---------- Disclaimer ---------- */
.disclaimer {
    background: #f9fafb;
    border: 0.5px solid #e5e7eb;
    border-radius: 4px;
    padding: 14px 16px;
    margin-top: 16px;
    font-size: 8px; line-height: 1.6;
    color: #6B7280;
}
.disclaimer-title {
    font-weight: 700; font-size: 9px;
    color: #374151; margin-bottom: 6px;
    text-transform: uppercase; letter-spacing: .05em;
}
"""


# ---------------------------------------------------------------------------
# Table renderers
# ---------------------------------------------------------------------------


def _render_allocation_table(
    allocations: list[Any],
) -> str:
    """Render allocation block table."""
    if not allocations:
        return ""
    rows: list[str] = []
    for a in allocations:
        pw = getattr(a, "portfolio_weight", 0) or 0
        bw = getattr(a, "benchmark_weight", 0) or 0
        aw = getattr(a, "active_weight", 0) or 0
        css = "positive" if aw > 0 else ("negative" if aw < 0 else "")
        rows.append(
            f"<tr>"
            f'<td>{_esc(getattr(a, "block_name", ""))}</td>'
            f'<td class="num">{_fmt_pct(pw)}</td>'
            f'<td class="num">{_fmt_pct(bw)}</td>'
            f'<td class="num {css}">{_fmt_pct(aw)}</td>'
            f"</tr>"
        )
    return (
        '<table class="data-table">'
        "<thead><tr>"
        "<th>Block</th><th class=\"num\">Portfolio</th>"
        "<th class=\"num\">Benchmark</th><th class=\"num\">Active</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_attribution_table(
    attribution: list[Any],
) -> str:
    """Render Brinson-Fachler attribution table."""
    if not attribution:
        return ""
    rows: list[str] = []
    for a in attribution:
        ae = getattr(a, "allocation_effect", 0) or 0
        se = getattr(a, "selection_effect", 0) or 0
        te = getattr(a, "total_effect", 0) or 0
        css_te = "positive" if te > 0 else ("negative" if te < 0 else "")
        rows.append(
            f"<tr>"
            f'<td>{_esc(getattr(a, "block_name", ""))}</td>'
            f'<td class="num">{_fmt_pct(ae, 3)}</td>'
            f'<td class="num">{_fmt_pct(se, 3)}</td>'
            f'<td class="num {css_te}">{_fmt_pct(te, 3)}</td>'
            f"</tr>"
        )
    return (
        '<table class="data-table">'
        "<thead><tr>"
        "<th>Block</th><th class=\"num\">Allocation</th>"
        "<th class=\"num\">Selection</th><th class=\"num\">Total</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_holdings_table(holdings: list[dict[str, Any]]) -> str:
    """Render top holdings table."""
    if not holdings:
        return ""
    rows: list[str] = []
    for h in holdings:
        rows.append(
            f"<tr>"
            f'<td>{_esc(h.get("fund_name", ""))}</td>'
            f'<td>{_esc(h.get("ticker", ""))}</td>'
            f'<td>{_esc(h.get("block_id", ""))}</td>'
            f'<td class="num">{_fmt_pct(h.get("weight"))}</td>'
            f"</tr>"
        )
    return (
        '<table class="data-table">'
        "<thead><tr>"
        "<th>Fund</th><th>Ticker</th><th>Block</th><th class=\"num\">Weight</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_stress_table(stress: list[dict[str, Any]]) -> str:
    """Render stress scenario table."""
    if not stress:
        return ""
    rows: list[str] = []
    for s in stress:
        pr = s.get("portfolio_return")
        md = s.get("max_drawdown")
        css_pr = "negative" if pr is not None and pr < 0 else ""
        css_md = "negative" if md is not None and md < 0 else ""
        rows.append(
            f"<tr>"
            f'<td>{_esc(s.get("name", ""))}</td>'
            f'<td class="num {css_pr}">{_fmt_pct(pr)}</td>'
            f'<td class="num {css_md}">{_fmt_pct(md)}</td>'
            f"</tr>"
        )
    return (
        '<table class="data-table">'
        "<thead><tr>"
        "<th>Scenario</th><th class=\"num\">Portfolio Return</th>"
        "<th class=\"num\">Max Drawdown</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# Chapter renderer
# ---------------------------------------------------------------------------


def _render_chapter_block(
    chapter: Any,
    total: int,
    data: "LongFormReportData",
    *,
    include_tables: bool = True,
) -> str:
    """Render a single chapter section (header + body + optional tables)."""
    order = getattr(chapter, "order", 0)
    tag = getattr(chapter, "tag", "")
    title = getattr(chapter, "title", "")
    content = getattr(chapter, "content", {}) or {}
    confidence = getattr(chapter, "confidence", 1.0)

    parts: list[str] = []

    # Chapter header
    parts.append(
        f'<div class="chapter-header">'
        f'<div class="chapter-number">Chapter {order} of {total}</div>'
        f'<div class="chapter-title">{_esc(title)}</div>'
        f"</div>"
    )

    # Body prose
    prose = _chapter_content_text(content)
    if prose:
        parts.append(f'<div class="chapter-body"><p>{prose}</p></div>')

    # Key indicators callout
    indicators = _chapter_key_indicators(content)
    if indicators:
        items_html = "".join(
            f'<div class="ki-item"><div class="ki-label">{label}</div>'
            f'<div class="ki-value">{val}</div></div>'
            for label, val in indicators
        )
        parts.append(f'<div class="key-indicators">{items_html}</div>')

    if not include_tables:
        return "\n".join(parts)

    # Contextual tables
    if tag == "strategic_allocation":
        parts.append(_render_allocation_table(data.allocations))
    elif tag == "performance_attribution":
        parts.append(_render_attribution_table(data.attribution))
    elif tag == "portfolio_composition":
        parts.append(_render_holdings_table(data.holdings))
    elif tag == "risk_decomposition":
        parts.append(_render_stress_table(data.stress))

    # Confidence badge
    if confidence < 1.0:
        pct = int(confidence * 100)
        parts.append(
            f'<div style="font-size:9px;color:#6B7280;margin-top:8px;">'
            f"Confidence: {pct}%</div>"
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------


def _render_page1(data: "LongFormReportData", chapters: list[Any]) -> str:
    """Render page 1 — cover with sidebar + first chapter."""
    regime_color = _REGIME_COLORS.get(data.regime, "#9CA3AF")
    regime_label = _REGIME_LABELS.get(data.regime, _esc(data.regime))
    total = len(chapters) or 8

    # Sidebar: table of contents
    toc_items: list[str] = []
    for i, ch in enumerate(chapters):
        title = _esc(getattr(ch, "title", f"Chapter {i + 1}"))
        active = "active" if i == 0 else ""
        toc_items.append(
            f'<div class="toc-item {active}">'
            f"{i + 1}. {title}</div>"
        )
    # Pad to 8 if fewer chapters provided
    for i in range(len(chapters), 8):
        toc_items.append(
            f'<div class="toc-item">{i + 1}. &mdash;</div>'
        )

    # Sidebar: key stats
    stats = [
        ("Active Return", _fmt_bps(data.active_return_bps)),
        ("CVaR 95%", _fmt_pct(data.cvar_95)),
        ("Avg ER", _fmt_pct(data.avg_expense_ratio)),
        ("Instruments", str(data.instrument_count)),
    ]
    stats_html = "".join(
        f'<div class="stat-row">'
        f'<span class="stat-label">{label}</span>'
        f'<span class="stat-value">{val}</span></div>'
        for label, val in stats
    )

    # First chapter
    ch1 = chapters[0] if chapters else None
    ch1_html = ""
    if ch1:
        ch1_html = _render_chapter_block(ch1, total, data)

    # First chapter key indicators from top-level data (always show)
    cover_indicators = (
        f'<div class="key-indicators">'
        f'<div class="ki-item"><div class="ki-label">Active Return</div>'
        f'<div class="ki-value">{_fmt_bps(data.active_return_bps)}</div></div>'
        f'<div class="ki-item"><div class="ki-label">CVaR 95%</div>'
        f'<div class="ki-value">{_fmt_pct(data.cvar_95)}</div></div>'
        f'<div class="ki-item"><div class="ki-label">Volatility</div>'
        f'<div class="ki-value">{_fmt_pct(data.volatility)}</div></div>'
        f'<div class="ki-item"><div class="ki-label">Sharpe</div>'
        f'<div class="ki-value">{_fmt_number(data.sharpe)}</div></div>'
        f"</div>"
    )

    # Footer nav
    next_title = _esc(getattr(chapters[1], "title", "")) if len(chapters) > 1 else ""
    footer_nav = (
        f'<div class="footer-nav">'
        f"<span></span>"
        f"<span>2. {next_title} &rarr;</span>"
        f"</div>"
    )

    return (
        f'<div class="page">'
        # Cover header
        f'<div class="cover-header">'
        f'<div class="cover-header-left">'
        f'<div class="cover-label">Long-Form Due Diligence Report &middot; Confidential</div>'
        f'<div class="cover-title">{_esc(data.portfolio_name)}</div>'
        f'<div class="cover-subtitle">Prepared {_fmt_date(data.as_of)} &middot; '
        f"AI-generated, pending IC approval</div>"
        f"</div>"
        f'<div class="regime-box">'
        f'<div class="regime-label">Regime</div>'
        f'<div class="regime-value" style="color:{regime_color}">{regime_label}</div>'
        f"</div>"
        f"</div>"
        # Body grid
        f'<div class="cover-body">'
        # Sidebar
        f'<div class="sidebar">'
        f'<div class="sidebar-heading">Contents</div>'
        + "".join(toc_items)
        + '<div class="sidebar-heading">Key Stats</div>'
        + stats_html
        + "</div>"
        # Main content
        '<div class="main-content">'
        + ch1_html
        + cover_indicators
        + footer_nav
        + "</div>"
        "</div>"
        "</div>"
    )


def _render_inner_page(
    data: "LongFormReportData",
    chapters_on_page: list[Any],
    total_chapters: int,
    page_num: int,
    total_pages: int,
    *,
    is_final: bool = False,
) -> str:
    """Render an inner page (pages 2-4)."""
    parts: list[str] = []

    # Page header
    parts.append(
        f'<div class="page-header">'
        f"<span>{_esc(data.portfolio_name)}</span>"
        f"<span>Page {page_num} of {total_pages}</span>"
        f"</div>"
    )

    parts.append('<div class="page-content">')

    for ch in chapters_on_page:
        parts.append(_render_chapter_block(ch, total_chapters, data))
        parts.append('<div style="margin-bottom:16px;"></div>')

    # Legal disclaimer on final page
    if is_final:
        parts.append(
            '<div class="disclaimer">'
            '<div class="disclaimer-title">Important Disclosures &amp; Disclaimer</div>'
            "<p>This Long-Form Due Diligence Report has been generated by an "
            "AI-powered analytical engine and is intended solely for use by "
            "qualified institutional investors and investment professionals. "
            "The content herein does not constitute investment advice, an offer "
            "to sell, or a solicitation of an offer to buy any securities or "
            "financial instruments.</p>"
            "<p style=\"margin-top:6px;\">All data, analytics, risk metrics, and "
            "performance attributions are derived from publicly available sources "
            "and proprietary quantitative models. While every effort has been made "
            "to ensure accuracy, the analytical engine may produce outputs that "
            "contain errors, omissions, or forward-looking statements subject to "
            "inherent uncertainty. Past performance is not indicative of future "
            "results.</p>"
            "<p style=\"margin-top:6px;\">The AI-generated narrative, risk "
            "assessments, and recommendations presented in this report are pending "
            "review and approval by the Investment Committee (IC). No investment "
            "decisions should be made solely on the basis of this report without "
            "independent verification and IC sign-off.</p>"
            "<p style=\"margin-top:6px;\">Confidentiality: This document is "
            "proprietary and confidential. Unauthorized reproduction, distribution, "
            "or disclosure of any part of this report is strictly prohibited. "
            "Recipients should treat this document in accordance with their "
            "organization&rsquo;s information security policies.</p>"
            "<p style=\"margin-top:6px;\">&copy; Netz Analytics. All rights reserved.</p>"
            "</div>"
        )

    parts.append("</div>")

    # Page footer
    parts.append(
        f'<div class="page-footer">'
        f"<span>Confidential &mdash; AI-generated, pending IC approval</span>"
        f"<span>Page {page_num} of {total_pages}</span>"
        f"</div>"
    )

    return '<div class="page">' + "\n".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_long_form_dd(data: "LongFormReportData", *, language: str = "en") -> str:
    """Render a complete Long-Form Due Diligence Report as self-contained HTML.

    Parameters
    ----------
    data:
        Frozen dataclass with all report data (portfolio, chapters, allocations, etc.).
    language:
        Language code (reserved for future i18n; currently only "en").

    Returns
    -------
    str
        Complete HTML string ready for Playwright PDF rendering.
    """
    chapters = sorted(data.chapters, key=lambda c: getattr(c, "order", 0))
    total_chapters = len(chapters) or 8
    total_pages = 4

    # Page 1: cover + chapter 1
    page1 = _render_page1(data, chapters)

    # Distribute chapters 2-8 across pages 2-4
    # Page 2: chapters 2-3
    # Page 3: chapters 4-6
    # Page 4: chapters 7-8 (final, includes disclaimer)
    remaining = chapters[1:]  # chapters after the first

    page2_chapters = remaining[0:2]   # chapters 2-3
    page3_chapters = remaining[2:5]   # chapters 4-6
    page4_chapters = remaining[5:]    # chapters 7-8

    page2 = _render_inner_page(
        data, page2_chapters, total_chapters,
        page_num=2, total_pages=total_pages,
    )
    page3 = _render_inner_page(
        data, page3_chapters, total_chapters,
        page_num=3, total_pages=total_pages,
    )
    page4 = _render_inner_page(
        data, page4_chapters, total_chapters,
        page_num=4, total_pages=total_pages,
        is_final=True,
    )

    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=210mm">'
        "<title>Long-Form DD Report &mdash; "
        f"{_esc(data.portfolio_name)}</title>"
        f"<style>{_CSS}</style>"
        "</head>"
        "<body>"
        + page1
        + page2
        + page3
        + page4
        + "</body></html>"
    )
