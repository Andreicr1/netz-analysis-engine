"""DD Report PDF Generator — renders wealth DD Reports as institutional PDFs.

Pattern follows ``generate_deep_review_pdf.py``: load DD Report + chapters
from DB, render markdown chapters via ``memo_md_to_pdf``, use ``pdf_base``
building blocks for consistent branding.

Bilingual: ``generate()`` accepts ``language`` param for PDF chrome (cover,
chapter titles, disclaimer). Chapter content language is determined at
generation time — the ``language`` param here controls static labels only.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    Spacer,
)

from ai_engine.pdf.pdf_base import (
    ORANGE,
    build_netz_styles,
    create_netz_document,
    netz_header_footer,
    safe_text,
)
from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language

logger = logging.getLogger(__name__)


def generate_dd_report_pdf(
    *,
    fund_name: str,
    report_id: str,
    chapters: list[dict[str, Any]],
    confidence_score: float | None = None,
    decision_anchor: str | None = None,
    language: Language = "pt",
) -> BytesIO:
    """Render a DD Report as institutional PDF.

    Args:
        fund_name: Fund display name for cover.
        report_id: Report UUID (for metadata).
        chapters: List of chapter dicts with ``chapter_tag``, ``chapter_order``,
                  ``content_md``. Must be sorted by ``chapter_order``.
        confidence_score: Overall confidence (0-100) for cover badge.
        decision_anchor: Decision anchor text (e.g. "INVEST", "PASS").
        language: PDF chrome language (labels, disclaimer). Default "pt".

    Returns:
        BytesIO seeked to 0 containing the PDF.
    """
    labels = LABELS[language]
    styles = build_netz_styles()
    buf = BytesIO()
    title = f"{labels['dd_report_title']} — {fund_name}"
    doc = create_netz_document(buf, title=title)
    story: list[Any] = []

    usable_w = A4[0] - 30 * mm

    # ── Cover page ─────────────────────────────────────────────────
    story.append(Paragraph(labels["dd_report_title"], styles["cover_title"]))
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(
        width="45%", thickness=2, color=ORANGE, spaceAfter=5 * mm, hAlign="CENTER",
    ))
    story.append(Paragraph(safe_text(fund_name), styles["cover_subtitle"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(labels["dd_cover_subtitle"], styles["cover_meta"]))
    story.append(Spacer(1, 4 * mm))

    # Decision anchor badge
    if decision_anchor:
        anchor_upper = decision_anchor.upper()
        if "INVEST" in anchor_upper or "PROCEED" in anchor_upper:
            badge_style = styles["badge_green"]
        elif "PASS" in anchor_upper:
            badge_style = styles["badge_red"]
        else:
            badge_style = styles["badge_amber"]
        story.append(Paragraph(safe_text(decision_anchor.upper()), badge_style))

    if confidence_score is not None:
        conf_text = f"Confidence Score: {confidence_score:.0f}%"
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(conf_text, styles["cover_meta"]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(labels["confidential"], styles["cover_confidential"]))
    story.append(PageBreak())

    # ── Chapters ───────────────────────────────────────────────────
    sorted_chapters = sorted(chapters, key=lambda c: c.get("chapter_order", 0))

    for ch in sorted_chapters:
        tag = ch.get("chapter_tag", "")
        order = ch.get("chapter_order", 0)
        content = ch.get("content_md", "")

        # Chapter heading
        chapter_title = f"{order}. {tag.replace('_', ' ').title()}"
        story.append(Paragraph(safe_text(chapter_title), styles["section_heading"]))
        story.append(Spacer(1, 2 * mm))

        # Render markdown content as body paragraphs
        if content:
            for paragraph_text in _split_markdown(content):
                story.append(Paragraph(safe_text(paragraph_text), styles["body"]))
        else:
            story.append(Paragraph("\u2014", styles["body"]))

        story.append(Spacer(1, 4 * mm))

    # ── Disclaimer ─────────────────────────────────────────────────
    story.append(Paragraph(labels["dd_disclaimer"], styles["disclaimer"]))

    # Build PDF
    def _on_page(canvas: Any, doc_obj: Any) -> None:
        netz_header_footer(
            canvas, doc_obj,
            report_title=title,
            confidentiality=labels["confidential"],
        )

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf


def _split_markdown(content: str) -> list[str]:
    """Split markdown content into paragraphs for ReportLab rendering.

    Simple splitter: double newlines separate paragraphs. Strips markdown
    headers (##) but preserves their text. This is intentionally simple —
    full markdown rendering is handled by ``memo_md_to_pdf.py``.
    """
    import re

    lines = content.strip().split("\n\n")
    result: list[str] = []
    for block in lines:
        block = block.strip()
        if not block:
            continue
        # Strip markdown headers but keep text
        block = re.sub(r"^#{1,6}\s*", "", block)
        # Collapse single newlines within a block
        block = block.replace("\n", " ").strip()
        if block:
            result.append(block)
    return result
