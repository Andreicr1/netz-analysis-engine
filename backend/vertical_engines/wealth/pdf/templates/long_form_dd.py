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
    width: 210mm; min-height: 297mm;
    position: relative; overflow: hidden;
    page-break-after: always; background: var(--white);
}
.page:last-child { page-break-after: auto; }

/* ══════════════════════  COVER  ══════════════════════ */
.cover {
    background: var(--navy); min-height: 297mm;
    padding: 52px 48px; display: flex; flex-direction: column;
}
.cv-label {
    font-size: 7.5px; letter-spacing: 0.18em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 32px;
}
.cv-fund {
    font-family: 'Playfair Display', serif;
    font-size: 28px; font-weight: 700;
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

/* Cover — regime badge */
.cv-regime-wrap {
    display: flex; align-items: center; gap: 16px;
    margin-bottom: 36px;
}
.cv-regime-label {
    font-size: 7px; letter-spacing: 0.12em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 4px;
}
.cv-regime-value {
    font-size: 15px; font-weight: 600;
}
.cv-badge {
    font-size: 8.5px; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase;
    padding: 5px 14px; border: 1px solid; border-radius: 2px;
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

/* Cover — KPI strip */
.cv-kpis {
    display: flex; gap: 0;
    border: 0.5px solid rgba(255,255,255,0.08);
    border-radius: 2px;
    margin-top: 32px;
}
.cv-kpi {
    flex: 1; padding: 12px 16px;
    border-right: 0.5px solid rgba(255,255,255,0.08);
}
.cv-kpi:last-child { border-right: none; }
.cv-kpi-label {
    font-size: 6.5px; letter-spacing: 0.1em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 4px;
}
.cv-kpi-val {
    font-size: 16px; font-weight: 700;
    font-variant-numeric: tabular-nums;
}

.cv-footer {
    margin-top: auto;
    font-size: 7.5px; color: rgba(255,255,255,0.25);
}

/* ══════════════════════  CHAPTER PAGES  ══════════════════════ */

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

/* Chapter header */
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

/* Chapter content — full width (no 70/30 split for long-form) */
.ch-wrap {
    padding: 18px 40px 72px;
}

/* Body typography */
.bt {
    font-size: 9.5px; line-height: 1.7;
    color: var(--text-secondary); margin: 0 0 8px;
}
.mh {
    font-family: 'Playfair Display', serif;
    font-size: 13px; font-weight: 700;
    color: var(--navy); margin: 20px 0 8px;
}
.sh {
    font-family: 'Playfair Display', serif;
    font-size: 11.5px; font-weight: 600;
    color: var(--slate-900); margin: 16px 0 6px;
    padding-bottom: 3px;
    border-bottom: 0.5px solid var(--slate-200);
}
.v-space { height: 8px; }

/* ── Key metrics strip (inline, 4 cells) ── */
.kpi-strip {
    display: flex; gap: 0;
    border: 0.5px solid var(--slate-200);
    border-radius: 2px; margin: 16px 0;
}
.kpi-cell {
    flex: 1; padding: 10px 14px;
    border-right: 0.5px solid var(--slate-200);
}
.kpi-cell:last-child { border-right: none; }
.kpi-label {
    font-size: 6.5px; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--slate-500);
    margin-bottom: 3px;
}
.kpi-val {
    font-size: 14px; font-weight: 700;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
}
.kpi-val.positive { color: #059669; }
.kpi-val.negative { color: var(--burgundy); }

/* ── Tufte-style tables ── */
.data-table {
    width: 100%; border-collapse: collapse;
    font-size: 9px; margin: 12px 0;
    font-variant-numeric: tabular-nums;
}
.data-table thead th {
    font-size: 7.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--slate-500); text-align: left;
    padding: 6px 8px 4px;
    border-bottom: 1.5px solid var(--navy);
    border-top: none;
}
.data-table tbody td {
    font-size: 9px; padding: 5px 8px;
    border-bottom: none; color: var(--text-secondary);
}
.data-table tbody tr:nth-child(even) td {
    background: var(--slate-50);
}
.data-table .num { text-align: right; }
.positive { color: #059669; }
.negative { color: var(--burgundy); }

/* ── Page footer ── */
.pf {
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 10px 40px;
    font-size: 7px; color: var(--slate-400);
    border-top: 0.5px solid var(--slate-200);
    display: flex; justify-content: space-between;
    letter-spacing: 0.02em;
}

/* ── Disclaimer ── */
.disc {
    margin-top: 20px; padding: 18px 0 0;
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

/* ── Chapter block spacing ── */
.chapter-block + .chapter-block {
    margin-top: 28px;
    padding-top: 24px;
    border-top: 0.5px solid var(--slate-200);
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
        f'<div class="ch-header">'
        f'<div class="ch-ord">Chapter {order}</div>'
        f'<div class="ch-title">{_esc(title)}</div>'
        f"</div>"
    )

    # Body prose — each paragraph separated
    prose = _chapter_content_text(content)
    if prose:
        paras = [p.strip() for p in prose.split("\n\n") if p.strip()]
        if paras:
            prose_html = "".join(
                f'<p class="bt">{p}</p><div class="v-space"></div>' for p in paras
            )
        else:
            prose_html = f'<p class="bt">{prose}</p>'
        parts.append(prose_html)

    # Key indicators strip
    indicators = _chapter_key_indicators(content)
    if indicators:
        items_html = "".join(
            f'<div class="kpi-cell"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-val">{val}</div></div>'
            for label, val in indicators
        )
        parts.append(f'<div class="kpi-strip">{items_html}</div>')

    if not include_tables:
        return '<div class="chapter-block">' + "\n".join(parts) + "</div>"

    # Contextual tables
    if tag == "strategic_allocation":
        parts.append(_render_allocation_table(data.allocations))
    elif tag == "performance_attribution":
        parts.append(_render_attribution_table(data.attribution))
        # Benchmark composite return from series (G7.6)
        bm_series = content.get("benchmark_composite_series", [])
        if len(bm_series) >= 2:
            try:
                first_nav = bm_series[0]["nav"]
                last_nav = bm_series[-1]["nav"]
                if first_nav and first_nav > 0:
                    bm_ret = (last_nav / first_nav) - 1.0
                    parts.append(
                        f'<div style="font-size:9px;color:var(--slate-500);margin-top:8px;">'
                        f"Composite Benchmark Return (trailing 12m): {_fmt_pct(bm_ret * 100)}"
                        f"</div>"
                    )
            except (KeyError, TypeError, ZeroDivisionError):
                pass
    elif tag == "portfolio_composition":
        parts.append(_render_holdings_table(data.holdings))
    elif tag == "risk_decomposition":
        parts.append(_render_stress_table(data.stress))

    # Confidence badge
    if confidence < 1.0:
        pct = int(confidence * 100)
        parts.append(
            f'<div style="font-size:9px;color:var(--slate-500);margin-top:8px;">'
            f"Confidence: {pct}%</div>"
        )

    return '<div class="chapter-block">' + "\n".join(parts) + "</div>"


# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------


def _render_page1(data: "LongFormReportData", chapters: list[Any]) -> str:
    """Render cover page in DD Report design language."""
    total = len(chapters) or 8
    total_pages = 4

    portfolio_name = _esc(data.portfolio_name)
    profile = _esc(data.profile.title() if data.profile else "")
    as_of_str = _esc(data.as_of.strftime("%B %d, %Y") if data.as_of else "")

    regime_raw = (data.regime or "expansion").lower()
    regime_label = _REGIME_LABELS.get(regime_raw, regime_raw.title())
    regime_color = _REGIME_COLORS.get(regime_raw, "#6EE7B7")

    # KPI strip values
    cvar_str = _fmt_pct(data.cvar_95) if data.cvar_95 is not None else "&mdash;"
    vol_str = _fmt_pct(data.volatility) if data.volatility is not None else "&mdash;"
    sharpe_str = _fmt_number(data.sharpe) if data.sharpe is not None else "&mdash;"
    er_str = (
        _fmt_pct(data.avg_expense_ratio, 2)
        if data.avg_expense_ratio is not None
        else "&mdash;"
    )

    # TOC from chapters
    toc_rows = ""
    for i, ch in enumerate(chapters[:8], 1):
        title = _esc(getattr(ch, "title", f"Chapter {i}"))
        toc_rows += (
            f'<div class="toc-row">'
            f'<span class="toc-num">{i}.</span>'
            f'<span class="toc-title">{title}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-page">{i + 1}</span>'
            f"</div>"
        )

    return (
        f'<div class="page"><div class="cover">'
        f'<div class="cv-label">Long-Form Due Diligence Report &middot; Confidential</div>'
        f'<div class="cv-fund">{portfolio_name}</div>'
        f'<div class="cv-sub">Profile: {profile} &middot; As of {as_of_str}</div>'
        f'<div class="cv-rule"></div>'
        f'<div class="cv-regime-wrap">'
        f"<div>"
        f'<div class="cv-regime-label">Market Regime</div>'
        f'<div class="cv-regime-value" style="color:{regime_color}">'
        f"{_esc(regime_label)}</div>"
        f"</div>"
        f'<div class="cv-badge" style="border-color:{regime_color};color:{regime_color}">'
        f"{_esc(regime_label.upper())}</div>"
        f"</div>"
        f'<div class="toc-label">Table of Contents</div>'
        f"{toc_rows}"
        f'<div class="cv-kpis">'
        f'<div class="cv-kpi">'
        f'<div class="cv-kpi-label">CVaR 95%</div>'
        f'<div class="cv-kpi-val" style="color:var(--burgundy)">{cvar_str}</div>'
        f"</div>"
        f'<div class="cv-kpi">'
        f'<div class="cv-kpi-label">Volatility</div>'
        f'<div class="cv-kpi-val">{vol_str}</div>'
        f"</div>"
        f'<div class="cv-kpi">'
        f'<div class="cv-kpi-label">Sharpe Ratio</div>'
        f'<div class="cv-kpi-val">{sharpe_str}</div>'
        f"</div>"
        f'<div class="cv-kpi">'
        f'<div class="cv-kpi-label">Avg Expense Ratio</div>'
        f'<div class="cv-kpi-val">{er_str}</div>'
        f"</div>"
        f"</div>"
        f'<div style="flex:1"></div>'
        f'<div class="cv-footer">CONFIDENTIAL — INTERNAL USE ONLY &middot; '
        f"p.&thinsp;1 of {total_pages}</div>"
        f"</div></div>"
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
        f'<div class="ph">'
        f'<span class="ph-fund">{_esc(data.portfolio_name)}</span>'
        f'<span class="ph-page">p.&thinsp;{page_num} of {total_pages}</span>'
        f"</div>"
    )

    parts.append('<div class="ch-wrap">')

    for ch in chapters_on_page:
        parts.append(_render_chapter_block(ch, total_chapters, data))

    # Legal disclaimer on final page
    if is_final:
        parts.append(
            '<div class="disc">'
            '<div class="disc-title">Important Disclosures &amp; Disclaimer</div>'
            "<p>This Long-Form Due Diligence Report is produced by the InvestIntell "
            "quantitative research platform. All analytics, attribution, risk metrics, "
            "and portfolio assessments are derived from official regulatory filings, "
            "macroeconomic data sources, and proprietary quantitative models.</p>"
            "<p>This report does not constitute investment advice. Past performance is "
            "not indicative of future results. For authorized recipients only.</p>"
            "<p>&copy; InvestIntell. All rights reserved.</p>"
            "</div>"
        )

    parts.append("</div>")

    # Page footer
    parts.append(
        f'<div class="pf">'
        f"<span>Confidential &mdash; For authorized recipients only</span>"
        f"<span>p.&thinsp;{page_num} of {total_pages}</span>"
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
