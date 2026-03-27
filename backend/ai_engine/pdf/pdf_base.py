"""Shared PDF base — institutional ReportLab styles, header/footer, logos, and helpers.

All Netz PDF generators import from this module to ensure consistent
branding, colour palette, and layout across Deep Review, Periodic Review,
IC Memorandum, and any future report types.

Engine: reportlab.platypus (UTF-8, A4, declarative Story[]).

Brand palette (Netz brand book 2026):
  #020F59  primary navy  — page titles, table headers
  #001B5C  deep navy     — section heading bg, header navy block
  #FF975A  orange        — footer accent stripe, cover rules
  #FCFDFD  off-white     — near-white fill
  Aileron  typeface      — approximated with Helvetica in ReportLab
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, cast

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import (
    Image as RLImage,
)

# ─────────────────────────────────────────────────────────────────────
# LOGO PATHS
# ─────────────────────────────────────────────────────────────────────

_HERE      = os.path.dirname(os.path.abspath(__file__))
_LOGOS_DIR = os.path.join(_HERE, "..", "..", "public", "logos")

_LOGO_NETZ_SVG = os.path.normpath(os.path.join(_LOGOS_DIR, "Logo Netz.svg"))
LOGO_NETZ   = _LOGO_NETZ_SVG if os.path.isfile(_LOGO_NETZ_SVG) else os.path.normpath(os.path.join(_LOGOS_DIR, "Logo Netz.png"))
LOGO_NECKER = os.path.normpath(os.path.join(_LOGOS_DIR, "Logo Necker.png"))

_LOGO_HEIGHT_COVER  = 9 * mm   # cover page logo height (reduced for density)
_LOGO_HEIGHT_HEADER =  7 * mm   # running header logo height


def _logo_image(path: str, height: float) -> Any | None:
    """Platypus flowable scaled to *height*, preserving aspect ratio.
    Supports PNG/JPEG via ReportLab RLImage and SVG via svglib.
    """
    if not os.path.isfile(path):
        return None
    if path.lower().endswith(".svg"):
        try:
            from reportlab.graphics import renderPDF  # noqa: F401 (validates import)
            from svglib.svglib import svg2rlg  # pyright: ignore[reportMissingImports]
            drawing = svg2rlg(path)
            if drawing is None:
                return None
            scale = height / drawing.height
            drawing.width  *= scale
            drawing.height *= scale
            drawing.transform = (scale, 0, 0, scale, 0, 0)
            return drawing
        except Exception:
            return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            w_px, h_px = im.size
        ratio = w_px / h_px
        return RLImage(path, width=height * ratio, height=height)
    except Exception:
        try:
            img = RLImage(path)
            img.drawHeight = height
            img.drawWidth  = height * (img.imageWidth / img.imageHeight)
            return img
        except Exception:
            return None


def _logo_on_canvas(
    canvas: Any, path: str,
    x: float, y: float, height: float,
    max_width: float | None = None,
) -> float:
    """Draw logo at canvas coords (x, y-bottom). Returns rendered width, 0 on failure.
    Supports PNG/JPEG via drawImage and SVG via svglib renderPDF.
    """
    if not os.path.isfile(path):
        return 0.0
    # SVG path: render via svglib
    if path.lower().endswith(".svg"):
        try:
            from reportlab.graphics import renderPDF
            from svglib.svglib import svg2rlg  # pyright: ignore[reportMissingImports]
            drawing = svg2rlg(path)
            if drawing is None:
                return 0.0
            scale = height / drawing.height
            width = drawing.width * scale
            if max_width:
                scale = min(scale, max_width / drawing.width)
                width = drawing.width * scale
            canvas.saveState()
            canvas.translate(x, y)
            canvas.scale(scale, scale)
            renderPDF.draw(drawing, canvas, 0, 0)
            canvas.restoreState()
            return width
        except Exception:
            return 0.0
    # Raster path: PNG / JPEG
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as im:
            w_px, h_px = im.size
        ratio  = w_px / h_px
        width  = height * ratio
        if max_width:
            width = min(width, max_width)
            height = width / ratio
        canvas.drawImage(
            path, x, y, width=width, height=height,
            mask="auto", preserveAspectRatio=True,
        )
        return width
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────
# COLOUR PALETTE — Netz Brand (brand book 2026)
# ─────────────────────────────────────────────────────────────────────

NAVY        = colors.HexColor("#020F59")   # primary navy — titles, table headers
NAVY_DEEP   = colors.HexColor("#001B5C")   # deep navy — section heading bg, header block
ORANGE      = colors.HexColor("#FF975A")   # brand orange — footer stripe, cover accent
OFF_WHITE   = colors.HexColor("#FCFDFD")   # near-white fill

DARK_GREY   = colors.Color(50  / 255, 50  / 255, 50  / 255)
MED_GREY    = colors.Color(120 / 255, 120 / 255, 130 / 255)
LIGHT_BG    = colors.Color(240 / 255, 242 / 255, 248 / 255)
GREEN       = colors.Color(22  / 255, 120 / 255, 50  / 255)
AMBER       = colors.Color(200 / 255, 140 / 255, 0   / 255)
RED         = colors.Color(180 / 255, 30  / 255, 30  / 255)
WHITE       = colors.white

ACCENT = NAVY   # legacy alias


# ─────────────────────────────────────────────────────────────────────
# PARAGRAPH STYLES
# ─────────────────────────────────────────────────────────────────────

def build_netz_styles() -> dict[str, ParagraphStyle]:
    """Return the canonical Netz institutional paragraph styles."""
    base = getSampleStyleSheet()
    return {
        # ── Cover ────────────────────────────────────────────────────
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontSize=24, leading=30,
            textColor=NAVY, fontName="Helvetica-Bold",
            alignment=TA_CENTER, spaceAfter=4 * mm,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontSize=15, leading=19,
            textColor=NAVY, fontName="Helvetica-Bold",   # navy — same tone as report title
            alignment=TA_CENTER, spaceAfter=3 * mm,
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta",
            parent=base["Normal"],
            fontSize=9, leading=13,
            textColor=MED_GREY, alignment=TA_CENTER, spaceAfter=2 * mm,
        ),
        "cover_addressee": ParagraphStyle(
            "CoverAddressee",
            parent=base["Normal"],
            fontSize=10, leading=14,
            textColor=NAVY, fontName="Helvetica-Oblique",
            alignment=TA_CENTER, spaceAfter=1 * mm,
        ),
        "cover_confidential": ParagraphStyle(
            "CoverConfidential",
            parent=base["Normal"],
            fontSize=8, leading=11,
            textColor=MED_GREY, fontName="Helvetica-Bold",
            alignment=TA_CENTER, spaceAfter=2 * mm,
        ),
        # ── Body ─────────────────────────────────────────────────────
        "section_heading": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading1"],
            fontSize=12, leading=16,
            textColor=WHITE, fontName="Helvetica-Bold",
            backColor=NAVY_DEEP,
            spaceBefore=8 * mm, spaceAfter=3 * mm,
            borderPadding=cast("Any", (2 * mm, 3 * mm, 2 * mm, 3 * mm)),
        ),
        "subsection": ParagraphStyle(
            "SubSection",
            parent=base["Heading2"],
            fontSize=10, leading=13,
            textColor=NAVY, fontName="Helvetica-Bold",
            spaceBefore=4 * mm, spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=9, leading=13,
            textColor=DARK_GREY, spaceAfter=3 * mm,
        ),
        "body_bold": ParagraphStyle(
            "BodyBold",
            parent=base["Normal"],
            fontSize=9, leading=13,
            textColor=DARK_GREY, fontName="Helvetica-Bold", spaceAfter=3 * mm,
        ),
        "disclaimer": ParagraphStyle(
            "Disclaimer",
            parent=base["Normal"],
            fontSize=7, leading=9,
            textColor=MED_GREY, fontName="Helvetica-Oblique", spaceBefore=4 * mm,
        ),
        "data_gap": ParagraphStyle(
            "DataGap",
            parent=base["Normal"],
            fontSize=8, leading=11,
            textColor=colors.HexColor("#CC4400"),  # burnt orange — visible but not alarming
            fontName="Helvetica-Oblique",
            spaceBefore=2 * mm, spaceAfter=2 * mm,
            borderPadding=cast("Any", (1 * mm, 2 * mm, 1 * mm, 2 * mm)),
        ),
        # ── Table ────────────────────────────────────────────────────
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontSize=8, leading=10,
            textColor=WHITE, fontName="Helvetica-Bold",
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["Normal"],
            fontSize=8, leading=10, textColor=DARK_GREY,
        ),
        # ── Signal badges ─────────────────────────────────────────────
        "badge_green": ParagraphStyle(
            "BadgeGreen",
            parent=base["Normal"],
            fontSize=13, leading=17,
            textColor=GREEN, fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
        "badge_amber": ParagraphStyle(
            "BadgeAmber",
            parent=base["Normal"],
            fontSize=13, leading=17,
            textColor=AMBER, fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
        "badge_red": ParagraphStyle(
            "BadgeRed",
            parent=base["Normal"],
            fontSize=13, leading=17,
            textColor=RED, fontName="Helvetica-Bold", alignment=TA_CENTER,
        ),
    }


# ─────────────────────────────────────────────────────────────────────
# COLOUR / SEVERITY HELPERS
# ─────────────────────────────────────────────────────────────────────

def severity_color(severity: str) -> colors.Color:
    sev = (severity or "").upper()
    if sev in {"HIGH", "SPECULATIVE", "CRITICAL"}:
        return RED
    if sev in {"MEDIUM", "MODERATE", "AMBER"}:
        return AMBER
    return GREEN


def severity_badge_style(
    severity: str, styles: dict[str, ParagraphStyle],
) -> ParagraphStyle:
    sev = (severity or "").upper()
    if sev in {"HIGH", "SPECULATIVE", "CRITICAL"}:
        return styles["badge_red"]
    if sev in {"MEDIUM", "MODERATE", "AMBER"}:
        return styles["badge_amber"]
    return styles["badge_green"]


def _color_tuple(c: colors.Color) -> tuple[float, float, float]:
    return (c.red, c.green, c.blue)


# ─────────────────────────────────────────────────────────────────────
# TABLE BUILDER
# ─────────────────────────────────────────────────────────────────────

def build_institutional_table(
    data: list[list[Any]],
    col_widths: list[float] | None = None,
    *,
    styles: dict[str, ParagraphStyle] | None = None,
) -> Table:
    """Build a consistently styled institutional table. First row = header."""
    _styles = styles or build_netz_styles()
    wrapped: list[list[Any]] = []
    for row_idx, row in enumerate(data):
        style = _styles["table_header"] if row_idx == 0 else _styles["table_cell"]
        wrapped.append([
            Paragraph(str(cell), style) if isinstance(cell, str) else cell
            for cell in row
        ])
    tbl = Table(wrapped, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1,  0), NAVY),
        ("TEXTCOLOR",      (0, 0), (-1,  0), WHITE),
        ("FONTNAME",       (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1,  0), 8),
        ("BOTTOMPADDING",  (0, 0), (-1,  0), 4),
        ("TOPPADDING",     (0, 0), (-1,  0), 4),
        ("BACKGROUND",     (0, 1), (-1, -1), LIGHT_BG),
        ("TEXTCOLOR",      (0, 1), (-1, -1), DARK_GREY),
        ("FONTSIZE",       (0, 1), (-1, -1), 8),
        ("TOPPADDING",     (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING",  (0, 1), (-1, -1), 3),
        ("GRID",           (0, 0), (-1, -1), 0.25, MED_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_BG, WHITE]),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


# ─────────────────────────────────────────────────────────────────────
# COVER PAGE BUILDER
# ─────────────────────────────────────────────────────────────────────

def build_ic_cover_story(
    *,
    report_type: str,
    deal_name: str,
    sponsor: str,
    signal: str,
    signal_rationale: str = "",
    generated_at: str,
    model_version: str = "",
    critic_score: float | None = None,
    version_tag: str = "",
    styles: dict[str, ParagraphStyle] | None = None,
    page_width: float = A4[0],
    left_margin: float = 15 * mm,
    right_margin: float = 15 * mm,
) -> list[Any]:
    """Return cover-page Story elements (caller appends PageBreak as needed).

    Layout:
      [Navy bg | Netz logo white]  ···  [Necker logo]   ← logo row
      ───────────────── thin navy rule ─────────────────
      CONFIDENTIAL notice
      ↕ spacer
      Report type (large navy title)
      ──── orange accent rule (45%) ────
      Deal name (orange bold)
      Sponsor line
      ↕ spacer
      MEMORANDUM  /  To the Members of the Investment Committee
      ↕ spacer
      [  IC SIGNAL BADGE (filled colour)  ]
      ↕ spacer
      Meta: generated | version | model | critic score
      ─── closing rule ───
    """
    _styles = styles or build_netz_styles()
    story: list[Any] = []
    usable_w = page_width - left_margin - right_margin

    # ── Logo row ────────────────────────────────────────────────────
    # Left: Netz logo (SVG already has blue background — no extra block)
    # Right: Necker logo (right-aligned)
    netz_img   = _logo_image(LOGO_NETZ,   _LOGO_HEIGHT_COVER)
    necker_img = _logo_image(LOGO_NECKER, _LOGO_HEIGHT_COVER)

    base_ss = getSampleStyleSheet()
    fallback_style = ParagraphStyle(
        "LogoFallback", parent=base_ss["Normal"],
        fontSize=11, textColor=NAVY, fontName="Helvetica-Bold",
    )
    left_cell  = netz_img   or Paragraph("NETZ",   fallback_style)
    right_cell = necker_img or Paragraph("NECKER", _styles["cover_meta"])

    logo_row_h = _LOGO_HEIGHT_COVER + 4 * mm   # row height with padding

    logo_tbl = Table(
        [[left_cell, right_cell]],
        colWidths=[usable_w / 2, usable_w / 2],
        rowHeights=[logo_row_h],
    )
    logo_tbl.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (0, 0), "LEFT"),
        ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (0, 0), 0),
        ("RIGHTPADDING",  (0, 0), (0, 0), 0),
        ("LEFTPADDING",   (1, 0), (1, 0), 0),
        ("RIGHTPADDING",  (1, 0), (1, 0), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))
    story.append(logo_tbl)

    # ── Thin navy rule under logo row ───────────────────────────────
    story.append(HRFlowable(
        width="100%", thickness=0.6, color=NAVY, spaceAfter=4 * mm,
    ))

    # ── Confidentiality notice ──────────────────────────────────────
    story.append(Paragraph(
        "CONFIDENTIAL — FOR INVESTMENT COMMITTEE USE ONLY",
        _styles["cover_confidential"],
    ))
    story.append(Spacer(1, 16 * mm))

    # ── Report type ─────────────────────────────────────────────────
    story.append(Paragraph(report_type, _styles["cover_title"]))
    story.append(Spacer(1, 3 * mm))

    # ── Orange accent rule ──────────────────────────────────────────
    story.append(HRFlowable(
        width="45%", thickness=2, color=ORANGE,
        spaceAfter=5 * mm, hAlign="CENTER",
    ))

    # ── Deal name + sponsor ─────────────────────────────────────────
    story.append(Paragraph(safe_text(deal_name), _styles["cover_subtitle"]))
    story.append(Spacer(1, 1 * mm))
    if sponsor:
        story.append(Paragraph(
            f"Sponsor / Manager: {safe_text(sponsor)}", _styles["cover_meta"],
        ))
    story.append(Spacer(1, 12 * mm))

    # ── Addressee block ─────────────────────────────────────────────
    story.append(Paragraph("MEMORANDUM", _styles["cover_meta"]))
    story.append(Spacer(1, 1 * mm))
    story.append(Paragraph(
        "To the Members of the Investment Committee",
        _styles["cover_addressee"],
    ))
    story.append(Paragraph("Netz Private Credit Fund", _styles["cover_addressee"]))
    story.append(Spacer(1, 12 * mm))

    # ── IC Signal badge (filled-colour table cell) ──────────────────
    sig_upper = (signal or "CONDITIONAL").upper()
    if "INVEST" in sig_upper or "PROCEED" in sig_upper:
        sig_color, sig_label = GREEN, "IC RECOMMENDATION: INVEST"
    elif "PASS" in sig_upper:
        sig_color, sig_label = RED,   "IC RECOMMENDATION: PASS — GATE BLOCKED"
    else:
        sig_color, sig_label = AMBER, "IC RECOMMENDATION: CONDITIONAL"

    badge_inner = ParagraphStyle(
        "BadgeInner", parent=base_ss["Normal"],
        fontSize=12, leading=15, textColor=WHITE,
        fontName="Helvetica-Bold", alignment=TA_CENTER,
    )
    badge_cell = Table(
        [[Paragraph(safe_text(sig_label), badge_inner)]],
        colWidths=[110 * mm], rowHeights=[10 * mm],
    )
    badge_cell.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), sig_color),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    # Centre the badge across the usable width
    badge_wrap = Table([[badge_cell]], colWidths=[usable_w])
    badge_wrap.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(badge_wrap)

    if signal_rationale:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(safe_text(signal_rationale[:220]), _styles["cover_meta"]))

    story.append(Spacer(1, 10 * mm))

    # ── Meta block (removed per IC feedback — clean cover) ──────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.3, color=MED_GREY, spaceAfter=0))

    return story


# ─────────────────────────────────────────────────────────────────────
# HEADER / FOOTER
#
#  Header (pages 2+):
#    ┌──────────────────────────────────────────────────────────┐
#    │ Netz logo (SVG w/ built-in bg) │ report title │ Necker   │
#    └──────────────────────────────────────────────────────────┘
#    ──── thin navy rule ────
#
#  Footer (all pages):
#    ════ 1.5 mm orange (#FF975A) stripe — full page width ════
#    generated date (L)   confidentiality (C)   Page N (R)
# ─────────────────────────────────────────────────────────────────────

_HEADER_H       = 13 * mm   # total height of header band
_FOOTER_STRIPE  =  1.5 * mm # orange stripe thickness
_FOOTER_TEXT_Y  = 11 * mm   # y-position of footer text baseline


def netz_header_footer(
    canvas: Any,
    doc: Any,
    *,
    report_title: str = "Netz Report",
    confidentiality: str = "CONFIDENTIAL \u2014 INTERNAL USE ONLY",
) -> None:
    """Draw branded header (p2+) and footer (all pages) on every page."""
    canvas.saveState()
    w, h = A4
    lm = 15 * mm
    rm = 15 * mm

    # ──────────────────────────────────────────────────────────────
    # HEADER  (pages 2+)
    # ──────────────────────────────────────────────────────────────
    if doc.page > 1:
        hdr_bottom = h - _HEADER_H

        # 1. Netz logo (SVG already has blue background — no navy block)
        logo_h       = _LOGO_HEIGHT_HEADER
        logo_padding = lm
        logo_y       = hdr_bottom + (_HEADER_H - logo_h) / 2
        _logo_on_canvas(
            canvas, LOGO_NETZ,
            x=logo_padding, y=logo_y, height=logo_h,
            max_width=40 * mm,
        )

        # 2. Report title — centred in the header
        title_area_cx = w / 2
        title_y       = hdr_bottom + (_HEADER_H - 7) / 2
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColorRGB(*_color_tuple(NAVY))
        canvas.drawCentredString(title_area_cx, title_y, report_title)

        # 4. Necker logo — right-aligned
        if os.path.isfile(LOGO_NECKER):
            try:
                from PIL import Image as PILImage
                with PILImage.open(LOGO_NECKER) as im:
                    ratio = im.size[0] / im.size[1]
                n_h = _LOGO_HEIGHT_HEADER
                n_w = n_h * ratio
                n_y = hdr_bottom + (_HEADER_H - n_h) / 2
                canvas.drawImage(
                    LOGO_NECKER,
                    w - rm - n_w, n_y,
                    width=n_w, height=n_h,
                    mask="auto", preserveAspectRatio=True,
                )
            except Exception:
                canvas.setFont("Helvetica", 6)
                canvas.setFillColorRGB(*_color_tuple(MED_GREY))
                canvas.drawRightString(w - rm, title_y, "NECKER")

        # 5. Thin navy separator rule below header band
        canvas.setStrokeColorRGB(*_color_tuple(NAVY))
        canvas.setLineWidth(0.5)
        canvas.line(0, hdr_bottom, w, hdr_bottom)

    # ──────────────────────────────────────────────────────────────
    # FOOTER  (all pages)
    #   orange stripe sits at the top of the footer zone, full width
    # ──────────────────────────────────────────────────────────────
    stripe_y = _FOOTER_TEXT_Y + 5 * mm   # just above the text

    # Orange accent stripe — full page width, no side margins
    canvas.setFillColorRGB(*_color_tuple(ORANGE))
    canvas.rect(0, stripe_y, w, _FOOTER_STRIPE, stroke=0, fill=1)

    # Footer text
    text_y = stripe_y - 4 * mm
    canvas.setFont("Helvetica", 6)
    canvas.setFillColorRGB(*_color_tuple(MED_GREY))
    canvas.drawString(
        lm, text_y,
        f"Prepared {datetime.now(UTC).strftime('%B %d, %Y')}",
    )
    canvas.drawCentredString(w / 2, text_y, confidentiality)
    canvas.drawRightString(w - rm, text_y, f"Page {doc.page}")

    canvas.restoreState()


# ─────────────────────────────────────────────────────────────────────
# DOCUMENT FACTORY
# ─────────────────────────────────────────────────────────────────────

def create_netz_document(buffer: BytesIO, *, title: str = "Netz Report") -> SimpleDocTemplate:
    """Return a pre-configured A4 SimpleDocTemplate with standard Netz margins."""
    return SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=22 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        title=title,
        author="Netz Private Credit OS",
        subject="Investment Committee Memorandum",
    )


# ─────────────────────────────────────────────────────────────────────
# SAFE TEXT HELPER
# ─────────────────────────────────────────────────────────────────────

def _normalise_unicode_dashes(text: str) -> str:
    """Replace Unicode dash variants that fall outside WinAnsiEncoding with
    ASCII or WinAnsi-safe equivalents so ReportLab's built-in Helvetica can
    render them (prevents black-block glyphs).

    Preserves EN DASH (U+2013) and EM DASH (U+2014) which ARE in WinAnsi.
    """
    return (
        text
        .replace("\u2010", "-")     # HYPHEN → HYPHEN-MINUS
        .replace("\u2011", "-")     # NON-BREAKING HYPHEN → HYPHEN-MINUS
        .replace("\u2012", "\u2013")  # FIGURE DASH → EN DASH (WinAnsi-safe)
        .replace("\u2015", "\u2014")  # HORIZONTAL BAR → EM DASH
        .replace("\u2212", "-")     # MINUS SIGN → HYPHEN-MINUS
        .replace("\u00AD", "-")     # SOFT HYPHEN → HYPHEN-MINUS
        .replace("\uFE58", "\u2014")  # SMALL EM DASH → EM DASH
        .replace("\uFE63", "-")     # SMALL HYPHEN-MINUS → HYPHEN-MINUS
        .replace("\uFF0D", "-")     # FULLWIDTH HYPHEN-MINUS → HYPHEN-MINUS
    )


def safe_text(value: Any, default: str = "\u2014") -> str:
    """Coerce *value* to a ReportLab-safe XML string.

    Normalises Unicode dashes that fall outside Helvetica's WinAnsiEncoding
    (prevents black-block glyphs) and escapes XML entities.
    """
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    text = _normalise_unicode_dashes(text)
    text = (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return text
