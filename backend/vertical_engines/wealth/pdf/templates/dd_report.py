"""DD Report HTML template (multi-page A4, 8 chapters, rendered via Playwright).

Receives chapter data from ``dd_report/models.py`` and renders a professional
due diligence report with cover, table of contents, and markdown chapters.

All user-supplied text is escaped via ``html.escape()``.
Bilingual PT/EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language, format_date

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FONT_STACK = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def _e(text: Any) -> str:
    if text is None:
        return "&mdash;"
    return html.escape(str(text))


def _md_to_html(content_md: str | None) -> str:
    """Convert simplified markdown to HTML paragraphs.

    Handles: ## headings, **bold**, - list items, and paragraph breaks.
    """
    if not content_md:
        return '<p style="color:#9ca3af;font-style:italic">No content available.</p>'

    lines = content_md.strip().split("\n")
    result: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                result.append("</ul>")
                in_list = False
            result.append('<div style="height:6px"></div>')
            continue

        if stripped.startswith("## "):
            if in_list:
                result.append("</ul>")
                in_list = False
            text = _e(stripped[3:])
            result.append(
                f'<h3 style="font-size:11px;font-weight:600;color:#111827;'
                f'margin:8px 0 4px">{text}</h3>'
            )
        elif stripped.startswith("# "):
            if in_list:
                result.append("</ul>")
                in_list = False
            text = _e(stripped[2:])
            result.append(
                f'<h2 style="font-size:12px;font-weight:700;color:#111827;'
                f'margin:10px 0 4px">{text}</h2>'
            )
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result.append(
                    '<ul style="margin:4px 0;padding-left:16px;font-size:10px;'
                    'line-height:1.55;color:#374151">'
                )
                in_list = True
            text = _apply_bold(_e(stripped[2:]))
            result.append(f"<li>{text}</li>")
        else:
            if in_list:
                result.append("</ul>")
                in_list = False
            text = _apply_bold(_e(stripped))
            result.append(
                f'<p style="font-size:10px;line-height:1.55;color:#374151;'
                f'margin:0 0 4px">{text}</p>'
            )

    if in_list:
        result.append("</ul>")

    return "\n".join(result)


def _apply_bold(text: str) -> str:
    """Replace **text** with <strong>text</strong> in already-escaped HTML."""
    return re.sub(
        r"\*\*(.+?)\*\*",
        r"<strong>\1</strong>",
        text,
    )


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = f"""\
@page {{ size: A4; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{
    font-family: {_FONT_STACK};
    font-size: 10px; color: #374151; line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}
.page {{
    width: 210mm; min-height: 297mm;
    position: relative; overflow: hidden;
    page-break-after: always;
}}
.page:last-child {{ page-break-after: auto; }}
"""


# ---------------------------------------------------------------------------
# Decision anchor badge
# ---------------------------------------------------------------------------


def _decision_badge(anchor: str | None) -> str:
    if not anchor:
        return ""
    upper = anchor.upper()
    if upper in ("APPROVE", "INVEST", "PROCEED"):
        bg, fg = "#D1FAE5", "#065F46"
    elif upper in ("REJECT", "PASS", "DECLINE"):
        bg, fg = "#FEE2E2", "#991B1B"
    else:
        bg, fg = "#FEF3C7", "#92400E"
    return (
        f'<span style="display:inline-block;padding:4px 14px;border-radius:12px;'
        f"font-size:11px;font-weight:700;letter-spacing:.06em;"
        f'background:{bg};color:{fg}">{_e(upper)}</span>'
    )


# ---------------------------------------------------------------------------
# Confidence gauge
# ---------------------------------------------------------------------------


def _confidence_gauge(score: float) -> str:
    pct = int(score * 100)
    if score >= 0.8:
        color = "#059669"
    elif score >= 0.6:
        color = "#D97706"
    else:
        color = "#DC2626"

    bar_width = max(5, int(score * 100))
    return (
        f'<div style="margin:12px 0">'
        f'<div style="font-size:9px;color:#6B7FA8;text-transform:uppercase;'
        f'letter-spacing:.08em;margin-bottom:4px">Confidence Score</div>'
        f'<div style="display:flex;align-items:center;gap:10px">'
        f'<div style="flex:1;height:8px;background:#1F2937;border-radius:4px;overflow:hidden">'
        f'<div style="height:100%;width:{bar_width}%;background:{color};'
        f'border-radius:4px"></div></div>'
        f'<span style="font-size:14px;font-weight:700;color:{color}">{pct}%</span>'
        f"</div></div>"
    )


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _cover_page(data: DDReportPDFData, labels: dict[str, str], language: Language, total_pages: int) -> str:
    chapters = _sorted_chapters(data)

    # TOC
    toc_items = ""
    for ch in chapters:
        order = _ch_order(ch)
        title = _ch_title(ch)
        toc_items += (
            f'<div style="display:flex;gap:8px;padding:3px 0;font-size:10px;'
            f'border-bottom:0.5px solid #1F2937">'
            f'<span style="color:#6B7FA8;width:20px">{order}.</span>'
            f'<span style="color:#D1D5DB">{_e(title)}</span>'
            f"</div>"
        )

    # Metadata
    meta = (
        f'<div style="display:flex;gap:16px;margin-top:12px;font-size:9px;color:#6B7FA8">'
        f"<span>{format_date(data.as_of, language)}</span>"
        f"</div>"
    )

    return (
        f'<div class="page">'
        f'<div style="background:#111827;height:100%;padding:40px 36px;'
        f'display:flex;flex-direction:column">'
        # Top label
        f'<div style="font-size:9px;letter-spacing:.14em;color:#6B7FA8;'
        f'text-transform:uppercase;margin-bottom:8px">'
        f'{_e(labels["dd_report_title"])} &middot; CONFIDENTIAL</div>'
        # Fund name
        f'<div style="font-size:22px;font-weight:500;color:#F9FAFB;margin-bottom:4px">'
        f"{_e(data.fund_name)}</div>"
        # Subtitle
        f'<div style="font-size:12px;color:#6B7FA8;margin-bottom:8px">'
        f"Prepared {format_date(data.as_of, language)} &middot; "
        f"Pending Investment Committee Review</div>"
        # TOC
        f'<div style="margin-top:20px">'
        f'<div style="font-size:9px;letter-spacing:.1em;color:#6B7FA8;'
        f'text-transform:uppercase;margin-bottom:8px">Table of Contents</div>'
        f"{toc_items}</div>"
        # Metadata
        f"{meta}"
        # Spacer
        f'<div style="flex:1"></div>'
        # Footer
        f'<div style="font-size:8px;color:#4B5E7A">'
        f"{_e(labels['confidential'])} &middot; p.&nbsp;1 of {total_pages}</div>"
        f"</div></div>"
    )


def _chapter_page(
    data: DDReportPDFData,
    chapters_on_page: list[Any],
    page_num: int,
    total_pages: int,
    labels: dict[str, str],
    *,
    is_final: bool = False,
) -> str:
    parts: list[str] = []

    # Page header
    parts.append(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:14px 24px 10px;border-bottom:1px solid #e5e7eb;margin-bottom:12px">'
        f'<span style="font-size:11px;font-weight:600;color:#111827">'
        f"{_e(data.fund_name)}</span>"
        f'<span style="font-size:9px;color:#9ca3af">'
        f"p.&nbsp;{page_num} of {total_pages}</span>"
        f"</div>"
    )

    parts.append('<div style="padding:4px 28px 64px">')

    for ch in chapters_on_page:
        order = _ch_order(ch)
        title = _ch_title(ch)
        content = _ch_content_md(ch)
        evidence = _ch_evidence(ch)
        quant = _ch_quant(ch)
        critic_iter = _ch_critic_iter(ch)
        critic_status = _ch_critic_status(ch)

        # Chapter header
        parts.append(
            f'<div style="border-left:3px solid #185FA5;padding-left:14px;margin-bottom:14px">'
            f'<div style="font-size:9px;text-transform:uppercase;letter-spacing:.1em;'
            f'color:#6B7280;margin-bottom:2px">Chapter {order}</div>'
            f'<div style="font-size:14px;font-weight:500;color:#111827">{_e(title)}</div>'
            f"</div>"
        )

        # Content
        parts.append(f'<div style="margin-bottom:8px">{_md_to_html(content)}</div>')

        # Evidence refs box
        if evidence:
            refs_list = ""
            for key, val in evidence.items():
                refs_list += f"<li>{_e(key)}: {_e(str(val))}</li>"
            parts.append(
                f'<div style="background:#EFF6FF;border-left:3px solid #185FA5;'
                f'padding:8px 12px;margin:8px 0;border-radius:0 4px 4px 0">'
                f'<div style="font-size:8px;font-weight:700;color:#1D4ED8;'
                f'text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">'
                f"Evidence Sources</div>"
                f'<ul style="font-size:9px;color:#374151;padding-left:14px;'
                f'margin:0;line-height:1.5">{refs_list}</ul>'
                f"</div>"
            )

        # Quant data box
        if quant:
            quant_cards = ""
            for key, val in quant.items():
                quant_cards += (
                    f'<div style="background:#f9fafb;border-radius:4px;padding:6px 10px;'
                    f'text-align:center">'
                    f'<div style="font-size:8px;color:#6b7280;text-transform:uppercase">'
                    f"{_e(key.replace('_', ' '))}</div>"
                    f'<div style="font-size:11px;font-weight:600;color:#111827">'
                    f"{_e(str(val))}</div></div>"
                )
            parts.append(
                f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin:6px 0">'
                f"{quant_cards}</div>"
            )

        parts.append('<div style="height:24px;border-top:0.5px solid #f3f4f6;margin-top:4px"></div>')

    # Disclaimer on final page
    if is_final:
        parts.append(
            '<div style="margin-top:12px;padding:14px 16px;background:#f9fafb;'
            'border:0.5px solid #e5e7eb;border-radius:4px;'
            'font-size:8px;line-height:1.7;color:#6B7280">'
            '<div style="font-weight:700;font-size:9px;color:#374151;'
            'margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em">'
            "Important Disclosures &amp; Disclaimer</div>"
            "<p>This Due Diligence Report is produced by the InvestIntell quantitative "
            "research platform. All analytics, risk metrics, performance data, and "
            "portfolio assessments are derived from official regulatory filings "
            "(SEC EDGAR Form ADV, Form N-PORT, Form 13F), macroeconomic data sources, "
            "and proprietary quantitative models processed through institutional-grade "
            "statistical engines.</p>"
            '<p style="margin-top:6px">Narrative commentary reflects the analytical output '
            "of the research platform and has been reviewed by the investment team prior "
            "to distribution. This report does not constitute investment advice, an offer "
            "to sell, or a solicitation to buy any securities or financial instruments.</p>"
            '<p style="margin-top:6px">Past performance is not indicative of future results. '
            "All analyses involve judgment and inherent uncertainty. Recipients should "
            "conduct independent verification before making investment decisions.</p>"
            '<p style="margin-top:6px"><strong>Confidentiality:</strong> This document is '
            "proprietary and confidential. Unauthorized reproduction or distribution is "
            "strictly prohibited.</p>"
            '<p style="margin-top:6px">&copy; InvestIntell. All rights reserved.</p>'
            "</div>"
        )

    parts.append("</div>")

    # Page footer
    parts.append(
        f'<div style="position:absolute;bottom:0;left:0;right:0;padding:8px 24px;'
        f"font-size:8px;color:#9ca3af;border-top:0.5px solid #e5e7eb;"
        f'display:flex;justify-content:space-between">'
        f"<span>Confidential &mdash; For authorized recipients only</span>"
        f"<span>p.&nbsp;{page_num} of {total_pages}</span>"
        f"</div>"
    )

    return f'<div class="page">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# Chapter data accessors (support both ChapterResult and dict)
# ---------------------------------------------------------------------------


def _ch_order(ch: Any) -> int:
    if isinstance(ch, dict):
        return ch.get("chapter_order", ch.get("order", 0))
    return getattr(ch, "order", getattr(ch, "chapter_order", 0))


def _ch_title(ch: Any) -> str:
    if isinstance(ch, dict):
        tag = ch.get("chapter_tag", ch.get("tag", ""))
        return ch.get("title", tag.replace("_", " ").title())
    tag = getattr(ch, "tag", getattr(ch, "chapter_tag", ""))
    return getattr(ch, "title", tag.replace("_", " ").title())


def _ch_content_md(ch: Any) -> str | None:
    if isinstance(ch, dict):
        return ch.get("content_md")
    return getattr(ch, "content_md", None)


def _ch_evidence(ch: Any) -> dict[str, Any]:
    if isinstance(ch, dict):
        return ch.get("evidence_refs", {})
    return getattr(ch, "evidence_refs", {}) or {}


def _ch_quant(ch: Any) -> dict[str, Any]:
    if isinstance(ch, dict):
        return ch.get("quant_data", {})
    return getattr(ch, "quant_data", {}) or {}


def _ch_critic_iter(ch: Any) -> int:
    if isinstance(ch, dict):
        return ch.get("critic_iterations", 0)
    return getattr(ch, "critic_iterations", 0)


def _ch_critic_status(ch: Any) -> str:
    if isinstance(ch, dict):
        return ch.get("critic_status", "pending")
    return getattr(ch, "critic_status", "pending")


def _sorted_chapters(data: DDReportPDFData) -> list[Any]:
    return sorted(data.chapters, key=lambda c: _ch_order(c))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_dd_report(data: DDReportPDFData, *, language: str = "en") -> str:
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

    # Distribute chapters across pages: ~2-3 chapters per page
    # Cover = page 1, then chapters spread across remaining pages
    chapter_groups: list[list[Any]] = []
    i = 0
    while i < len(chapters):
        # 2 chapters per page (generous spacing)
        group = chapters[i : i + 2]
        chapter_groups.append(group)
        i += 2

    total_pages = 1 + len(chapter_groups)  # cover + chapter pages

    pages: list[str] = []
    pages.append(_cover_page(data, labels, language, total_pages))

    for gi, group in enumerate(chapter_groups):
        page_num = gi + 2
        is_final = gi == len(chapter_groups) - 1
        pages.append(
            _chapter_page(
                data, group, page_num, total_pages, labels,
                is_final=is_final,
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
