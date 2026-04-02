"""DD Report HTML template — Netz Premium Institutional System Design Doctrine.

Multi-page A4 Due Diligence report (8 chapters) with:

- **Cover page**: Rich Navy (#0A192F), Playfair Display fund name, copper accent
  rule, confidence gauge, decision badge, leader-dot TOC with page references.
- **Chapter pages**: 70 / 30 manuscript sidenote layout — main prose left,
  evidence sources and quant sparklines in the right margin.
- **Radar chart**: optional scoring-component spider web (executive summary).
- **Sparklines**: optional Tufte word-sized trend lines alongside margin metrics.
- **Pull quotes**: markdown ``> blockquotes`` rendered as Playfair Display Italic
  callouts with oversized directional quotation mark.
- **Hairline-separated data cards**: no SaaS-widget backgrounds.
- **Typography**: Playfair Display (headings/quotes), Inter (body/metrics).

Rendered via Playwright Chromium ``page.pdf()``.
All user-supplied text escaped via ``html.escape()``.
Bilingual PT / EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language, format_date
from vertical_engines.wealth.pdf.svg_charts import radar_chart, sparkline_svg

# ---------------------------------------------------------------------------
# Data model (inline to avoid circular imports with dd_report.models)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DDReportPDFData:
    """All data needed to render a DD Report PDF."""

    fund_name: str
    fund_id: str
    as_of: date
    confidence_score: float  # 0-1 (e.g. 0.82 = 82%)
    decision_anchor: str | None  # "approve" | "reject" | "review"
    chapters: list[Any]  # list[ChapterResult] or list[dict]
    language: str = "en"
    # Optional visual-breather data
    scoring_components: dict[str, float] | None = None  # radar chart data
    sparkline_data: dict[str, list[float]] | None = None  # metric → trend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _e(text: Any) -> str:
    if text is None:
        return "&mdash;"
    return html.escape(str(text))


def _apply_bold(text: str) -> str:
    """Replace **text** with <strong>text</strong> in already-escaped HTML."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


def _md_to_html(content_md: str | None) -> str:
    """Convert simplified markdown to HTML with pull-quote detection.

    Handles: ``# / ## headings``, ``> blockquotes`` (→ pull quotes),
    ``- / * / 1.`` lists, ``**bold**``, paragraphs, empty-line spacers.
    Headings use Playfair Display; body uses Inter.
    """
    if not content_md:
        return '<p class="no-content">No content available.</p>'

    lines = content_md.strip().split("\n")
    result: list[str] = []
    in_ul = False
    in_ol = False
    in_bq = False

    def _close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            result.append("</ul>")
            in_ul = False
        if in_ol:
            result.append("</ol>")
            in_ol = False

    for raw_line in lines:
        stripped = raw_line.strip()

        # ── Empty line ──
        if not stripped:
            _close_lists()
            if in_bq:
                result.append("</blockquote>")
                in_bq = False
            result.append('<div class="v-space"></div>')
            continue

        # ── Blockquote → Pull quote ──
        if stripped.startswith("> "):
            _close_lists()
            if not in_bq:
                result.append('<blockquote class="pull-quote">')
                result.append('<span class="q-mark">\u201C</span>')
                in_bq = True
            text = _apply_bold(_e(stripped[2:]))
            result.append(f'<p class="q-text">{text}</p>')
            continue

        if in_bq:
            result.append("</blockquote>")
            in_bq = False

        # ── Headings ──
        if stripped.startswith("## "):
            _close_lists()
            text = _apply_bold(_e(stripped[3:]))
            result.append(f'<h3 class="sh">{text}</h3>')
        elif stripped.startswith("# "):
            _close_lists()
            text = _apply_bold(_e(stripped[2:]))
            result.append(f'<h2 class="mh">{text}</h2>')

        # ── Unordered list ──
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if in_ol:
                result.append("</ol>")
                in_ol = False
            if not in_ul:
                result.append('<ul class="bl">')
                in_ul = True
            text = _apply_bold(_e(stripped[2:]))
            result.append(f"<li>{text}</li>")

        # ── Ordered list ──
        elif len(stripped) > 2 and stripped[0].isdigit() and ". " in stripped[:5]:
            if in_ul:
                result.append("</ul>")
                in_ul = False
            if not in_ol:
                result.append('<ol class="bl">')
                in_ol = True
            idx = stripped.index(". ")
            text = _apply_bold(_e(stripped[idx + 2 :]))
            result.append(f"<li>{text}</li>")

        # ── Paragraph ──
        else:
            _close_lists()
            text = _apply_bold(_e(stripped))
            result.append(f'<p class="bt">{text}</p>')

    _close_lists()
    if in_bq:
        result.append("</blockquote>")

    return "\n".join(result)


# ---------------------------------------------------------------------------
# CSS — Netz Premium Institutional System Design Doctrine
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

/* Cover — confidence & decision */
.cv-meta {
    display: flex; align-items: center;
    gap: 32px; margin-bottom: 36px;
}
.cv-conf-label {
    font-size: 7px; letter-spacing: 0.12em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 5px;
}
.cv-conf-track {
    height: 3px; background: rgba(255,255,255,0.07);
    border-radius: 1.5px; overflow: hidden;
    margin-bottom: 4px; width: 140px;
}
.cv-conf-fill { height: 100%; border-radius: 1.5px; }
.cv-conf-val {
    font-size: 22px; font-weight: 700;
    font-variant-numeric: tabular-nums;
}
.cv-badge {
    font-size: 8.5px; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase;
    padding: 5px 16px; border: 1px solid; border-radius: 2px;
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

/* Chapter header (full-width, above the 70/30 split) */
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
.no-content {
    color: var(--slate-400); font-style: italic; font-size: 9px;
}

/* ── Pull quote ── */
.pull-quote {
    margin: 22px 0; padding: 16px 0 16px 28px;
    position: relative;
}
.q-mark {
    position: absolute; left: 0; top: 2px;
    font-family: 'Playfair Display', serif;
    font-size: 44px; color: var(--slate-200); line-height: 1;
}
.q-text {
    font-family: 'Playfair Display', serif;
    font-style: italic; font-size: 13px;
    line-height: 1.55; color: var(--slate-700);
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

/* ── Radar container ── */
.radar-wrap {
    display: flex; justify-content: center; margin: 8px 0 14px;
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
"""


# ---------------------------------------------------------------------------
# Chapter data accessors (support both ChapterResult and dict)
# ---------------------------------------------------------------------------


def _ch_order(ch: Any) -> int:
    if isinstance(ch, dict):
        return int(ch.get("chapter_order") or ch.get("order") or 0)
    raw: Any = getattr(ch, "order", getattr(ch, "chapter_order", 0))
    return int(raw)


def _ch_title(ch: Any) -> str:
    if isinstance(ch, dict):
        tag: str = ch.get("chapter_tag", ch.get("tag", "")) or ""
        return str(ch.get("title", tag.replace("_", " ").title()))
    tag_attr: str = getattr(ch, "tag", getattr(ch, "chapter_tag", "")) or ""
    return str(getattr(ch, "title", tag_attr.replace("_", " ").title()))


def _ch_content_md(ch: Any) -> str | None:
    if isinstance(ch, dict):
        return ch.get("content_md")
    return getattr(ch, "content_md", None)


def _ch_evidence(ch: Any) -> dict[str, Any]:
    if isinstance(ch, dict):
        result: dict[str, Any] = ch.get("evidence_refs", {})
        return result
    return dict(getattr(ch, "evidence_refs", {}) or {})


def _ch_quant(ch: Any) -> dict[str, Any]:
    if isinstance(ch, dict):
        result: dict[str, Any] = ch.get("quant_data", {})
        return result
    return dict(getattr(ch, "quant_data", {}) or {})


def _ch_critic_iter(ch: Any) -> int:
    if isinstance(ch, dict):
        return int(ch.get("critic_iterations", 0))
    return int(getattr(ch, "critic_iterations", 0))


def _ch_critic_status(ch: Any) -> str:
    if isinstance(ch, dict):
        return str(ch.get("critic_status", "pending"))
    return str(getattr(ch, "critic_status", "pending"))


def _sorted_chapters(data: DDReportPDFData) -> list[Any]:
    return sorted(data.chapters, key=lambda c: _ch_order(c))


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------


def _cover_page(
    data: DDReportPDFData,
    labels: dict[str, str],
    language: Language,
    total_pages: int,
) -> str:
    chapters = _sorted_chapters(data)

    # ── Confidence gauge ──
    pct = int(data.confidence_score * 100)
    if data.confidence_score >= 0.8:
        conf_color = "#059669"
    elif data.confidence_score >= 0.6:
        conf_color = "#D97706"
    else:
        conf_color = "#DC2626"

    conf_width = max(5, int(data.confidence_score * 100))

    confidence_html = (
        f"<div>"
        f'<div class="cv-conf-label">Confidence Score</div>'
        f'<div class="cv-conf-track">'
        f'<div class="cv-conf-fill" style="width:{conf_width}%;background:{conf_color}"></div>'
        f"</div>"
        f'<div class="cv-conf-val" style="color:{conf_color}">{pct}%</div>'
        f"</div>"
    )

    # ── Decision badge ──
    badge_html = ""
    if data.decision_anchor:
        upper = data.decision_anchor.upper()
        if upper in ("APPROVE", "INVEST", "PROCEED"):
            badge_c = "#059669"
        elif upper in ("REJECT", "PASS", "DECLINE"):
            badge_c = "#DC2626"
        else:
            badge_c = "#D97706"
        badge_html = (
            f'<div class="cv-badge" style="border-color:{badge_c};color:{badge_c}">'
            f"{_e(upper)}</div>"
        )

    # ── Table of Contents with leader dots ──
    toc_items = ""
    for ch in chapters:
        order = _ch_order(ch)
        title = _ch_title(ch)
        page = order + 1
        toc_items += (
            f'<div class="toc-row">'
            f'<span class="toc-num">{order}.</span>'
            f'<span class="toc-title">{_e(title)}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-page">{page}</span>'
            f"</div>"
        )

    return (
        f'<div class="page"><div class="cover">'
        # Label
        f'<div class="cv-label">'
        f'{_e(labels["dd_report_title"])} &middot; Confidential</div>'
        # Fund name
        f'<div class="cv-fund">{_e(data.fund_name)}</div>'
        # Subtitle
        f'<div class="cv-sub">'
        f"Prepared {format_date(data.as_of, language)} &middot; "
        f"Pending Investment Committee Review</div>"
        # Copper accent rule
        f'<div class="cv-rule"></div>'
        # Confidence + Decision row
        f'<div class="cv-meta">{confidence_html}{badge_html}</div>'
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


# ---------------------------------------------------------------------------
# Chapter page (one chapter per page, 70/30 sidenote layout)
# ---------------------------------------------------------------------------


def _chapter_page(
    data: DDReportPDFData,
    ch: Any,
    page_num: int,
    total_pages: int,
    labels: dict[str, str],
    *,
    is_first_chapter: bool = False,
    is_final: bool = False,
) -> str:
    order = _ch_order(ch)
    title = _ch_title(ch)
    content = _ch_content_md(ch)
    evidence = _ch_evidence(ch)
    quant = _ch_quant(ch)

    parts: list[str] = []

    # ── Page header ──
    parts.append(
        f'<div class="ph">'
        f'<span class="ph-fund">{_e(data.fund_name)}</span>'
        f'<span class="ph-page">p.&thinsp;{page_num} of {total_pages}</span>'
        f"</div>"
    )

    # ── Chapter header (full width) ──
    parts.append(
        f'<div class="ch-header">'
        f'<div class="ch-ord">Chapter {order}</div>'
        f'<div class="ch-title">{_e(title)}</div>'
        f"</div>"
    )

    # ── 70 / 30 layout ──
    parts.append('<div class="ch-wrap">')

    # --- Main content (70 %) ---
    parts.append('<div class="ch-main">')

    # Radar chart on first chapter when scoring data available
    if is_first_chapter and data.scoring_components:
        parts.append(
            f'<div class="radar-wrap">'
            f"{radar_chart(data.scoring_components, width=200, height=200)}"
            f"</div>"
        )

    # Markdown body
    parts.append(_md_to_html(content))

    # Disclaimer on final page
    if is_final:
        parts.append(
            '<div class="disc">'
            '<div class="disc-title">Important Disclosures &amp; Disclaimer</div>'
            "<p>This Due Diligence Report is produced by the InvestIntell quantitative "
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

    parts.append("</div>")  # close ch-main

    # --- Margin content (30 %) ---
    parts.append('<div class="ch-margin">')

    # Evidence sources
    if evidence:
        parts.append('<div class="mg-ev">')
        parts.append('<div class="mg-ev-label">Evidence Sources</div>')
        for key, val in evidence.items():
            parts.append(
                f'<div class="mg-ev-item">'
                f"<strong>{_e(key)}:</strong> {_e(str(val))}"
                f"</div>"
            )
        parts.append("</div>")

    # Quant metrics with optional sparklines
    if quant:
        spark_data = data.sparkline_data or {}
        for key, val in quant.items():
            spark_html = ""
            if key in spark_data and spark_data[key]:
                spark_html = sparkline_svg(
                    spark_data[key], width=50, height=12,
                )
            parts.append(
                f'<div class="mg-q">'
                f'<div class="mg-q-label">{_e(key.replace("_", " "))}</div>'
                f'<div class="mg-q-right">'
                f"{spark_html}"
                f'<div class="mg-q-val">{_e(str(val))}</div>'
                f"</div></div>"
            )

    # Critic status (subtle indicator)
    critic_iter = _ch_critic_iter(ch)
    critic_status = _ch_critic_status(ch)
    if critic_iter > 0:
        status_color = "#059669" if critic_status == "accepted" else "#D97706"
        parts.append(
            f'<div style="margin-top:14px;padding-top:10px;'
            f'border-top:0.5px solid var(--slate-200)">'
            f'<div class="mg-ev-label">Critic Review</div>'
            f'<div class="mg-ev-item">'
            f'<span style="color:{status_color};font-weight:600">'
            f"{_e(critic_status.title())}</span>"
            f" &middot; {critic_iter} iteration{'s' if critic_iter != 1 else ''}"
            f"</div></div>"
        )

    parts.append("</div>")  # close ch-margin
    parts.append("</div>")  # close ch-wrap

    # ── Page footer ──
    parts.append(
        f'<div class="pf">'
        f"<span>Confidential &mdash; For authorized recipients only</span>"
        f"<span>p.&thinsp;{page_num} of {total_pages}</span>"
        f"</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_dd_report(data: DDReportPDFData, *, language: Language = "en") -> str:
    """Render a complete DD Report as self-contained HTML.

    Parameters
    ----------
    data:
        ``DDReportPDFData`` with fund info, confidence, decision, and chapters.
    language:
        ``"pt"`` or ``"en"`` for bilingual labels.

    Returns
    -------
    str
        Complete HTML ready for Playwright PDF rendering.
    """
    labels = LABELS[language]
    chapters = _sorted_chapters(data)

    # One chapter per page — generous whitespace, premium layout
    total_pages = 1 + len(chapters)  # cover + one page per chapter

    pages: list[str] = []
    pages.append(_cover_page(data, labels, language, total_pages))

    for i, ch in enumerate(chapters):
        page_num = i + 2
        pages.append(
            _chapter_page(
                data,
                ch,
                page_num,
                total_pages,
                labels,
                is_first_chapter=(i == 0),
                is_final=(i == len(chapters) - 1),
            )
        )

    return (
        f"<!DOCTYPE html>"
        f'<html lang="{_e(language)}">'
        f"<head>"
        f'<meta charset="utf-8"/>'
        f"<title>{_e(labels['dd_report_title'])} &mdash; {_e(data.fund_name)}</title>"
        f"<style>{_CSS}</style>"
        f"</head>"
        f"<body>{''.join(pages)}</body>"
        f"</html>"
    )
