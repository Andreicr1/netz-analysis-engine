"""Shared PDF renderer for content-production engines.

Extracts the common render logic from InvestmentOutlook, FlashReport, and
ManagerSpotlight into a single reusable function. Each engine's ``render_pdf``
becomes a thin wrapper that calls ``render_content_pdf``.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language


def render_content_pdf(
    content_md: str,
    *,
    title: str,
    subtitle: str = "",
    language: Language = "pt",
) -> BytesIO:
    """Render markdown content as a branded Netz PDF.

    Parameters
    ----------
    content_md:
        Markdown text (``## heading``, ``# heading``, body lines).
    title:
        Cover title (e.g. "Investment Outlook").
    subtitle:
        Optional subtitle placed below the HR rule (e.g. fund name).
    language:
        ``"pt"`` or ``"en"`` for date formatting and labels.

    Returns
    -------
    BytesIO with the built PDF, seeked to position 0.

    """
    from datetime import date

    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, Spacer

    from ai_engine.pdf.pdf_base import (
        ORANGE,
        build_netz_styles,
        create_netz_document,
        netz_header_footer,
        safe_text,
    )
    from vertical_engines.wealth.fact_sheet.i18n import format_date

    labels = LABELS[language]
    doc_title = f"{title} — {subtitle}" if subtitle else title
    styles = build_netz_styles()
    buf = BytesIO()
    doc = create_netz_document(buf, title=doc_title)
    story: list[Any] = []

    # Cover
    story.append(Paragraph(title, styles["cover_title"]))
    story.append(Spacer(1, 3 * mm))
    story.append(
        HRFlowable(
            width="45%", thickness=2, color=ORANGE,
            spaceAfter=5 * mm, hAlign="CENTER",
        ),
    )

    if subtitle:
        story.append(Paragraph(safe_text(subtitle), styles["cover_subtitle"]))
        story.append(Spacer(1, 2 * mm))

    story.append(Paragraph(format_date(date.today(), language), styles["cover_meta"]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(labels["confidential"], styles["cover_confidential"]))
    story.append(Spacer(1, 6 * mm))

    # Content (split by lines for proper paragraph handling)
    for line in content_md.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 2 * mm))
        elif line.startswith("## "):
            story.append(Paragraph(safe_text(line[3:]), styles["section_heading"]))
        elif line.startswith("# "):
            story.append(Paragraph(safe_text(line[2:]), styles["cover_subtitle"]))
        else:
            story.append(Paragraph(safe_text(line), styles["body"]))

    # Disclaimer
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(labels["content_disclaimer"], styles["disclaimer"]))

    def _on_page(canvas: Any, doc_obj: Any) -> None:
        netz_header_footer(
            canvas, doc_obj, report_title=doc_title,
            confidentiality=labels["confidential"],
        )

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    buf.seek(0)
    return buf
