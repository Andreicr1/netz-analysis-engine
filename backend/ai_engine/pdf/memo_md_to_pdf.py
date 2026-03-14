"""Investment Memo Markdown → Institutional PDF (ReportLab / Unicode).

Converts a Deep Review markdown investment memo into a branded Netz
IC-grade PDF.  Supports tables, bullet lists, bold/italic, and the
standard 13-chapter structure.

Usage:
    python -m ai_engine.pdf.memo_md_to_pdf --input MEMO.md --output MEMO.pdf
    python -m ai_engine.pdf.memo_md_to_pdf --input MEMO.md          # auto-names .pdf
"""
from __future__ import annotations

import argparse
import os
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    Spacer,
)
from reportlab.platypus import (
    Image as RLImage,
)

from ai_engine.pdf.chart_renderer import (
    CHART_MARKER_RE as _CHART_MARKER_PATTERN,
)
from ai_engine.pdf.chart_renderer import (
    extract_chart_index,
    render_chart,
)
from ai_engine.pdf.pdf_base import (
    MED_GREY,
    _normalise_unicode_dashes,
    build_institutional_table,
    build_netz_styles,
    create_netz_document,
    netz_header_footer,
    safe_text,
)
from ai_engine.pdf.pdf_base import build_ic_cover_story as _pdf_base_cover

# ─────────────────────────────────────────────────────────────────────
# CHART MARKER SUPPORT
# <!-- CHART:type:title --> markers are replaced with RLImage flowables
# when chart data is available; otherwise a DATA_GAP note is inserted.
# CHARTDATA comments embedded in the markdown carry chart data so that
# PDFs can be regenerated from cached chapters without re-running LLM.
# ─────────────────────────────────────────────────────────────────────

_CHART_MARKER_RE = re.compile(_CHART_MARKER_PATTERN)
_CHART_DISPLAY_WIDTH  = 16 * cm   # A4 body width
_CHART_DISPLAY_HEIGHT =  8 * cm   # standard chart height


def _resolve_chart_marker(
    match: re.Match,
    chart_data_index: dict[str, dict],
    styles: dict,
) -> list[Any]:
    """Replace a CHART marker with an RLImage flowable or a DATA_GAP paragraph."""
    chart_type  = match.group("type")
    chart_title = match.group("title").strip()

    entry = chart_data_index.get(chart_title)
    if not entry:
        return [Paragraph(
            f"[DATA_GAP — chart '{safe_text(chart_title)}': insufficient data to render]",
            styles.get("data_gap", styles.get("disclaimer")),
        )]

    try:
        data = entry.get("data", entry)  # entry may be {type, title, data} or just the data dict
        png_buf = render_chart(chart_type, data)
        img = RLImage(png_buf, width=_CHART_DISPLAY_WIDTH, height=_CHART_DISPLAY_HEIGHT)
        return [Spacer(1, 4), img, Spacer(1, 6)]
    except Exception as exc:  # noqa: BLE001
        import logging as _log
        _log.getLogger(__name__).warning("chart render failed for '%s': %s", chart_title, exc)
        return [Paragraph(
            f"[DATA_GAP — chart '{safe_text(chart_title)}': {safe_text(str(exc))}]",
            styles.get("data_gap", styles.get("disclaimer")),
        )]


# ─────────────────────────────────────────────────────────────────────
# MARKDOWN PRE-PROCESSOR
# Normalises the LLM output before the story builder sees it.
# ─────────────────────────────────────────────────────────────────────

def _normalise_md(md: str) -> str:
    """Remove structural noise produced by the LLM pipeline:

    1. Collapse duplicate chapter headings.
       The LLM emits both a numbered heading and a plain heading, e.g.::

           ## 1. Executive Summary
           ## Executive Summary

       Keep only the *numbered* form; discard the plain echo.

    2. Remove orphan `---` dividers that follow a heading (they produce
       blank visual space and confuse the table-detector).

    3. Collapse runs of more than two blank lines to exactly two.
    """
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    # Regex for numbered chapter headings  (## 1. Title)
    _numbered = re.compile(r"^(#{1,2})\s+\d+\.\s+.+$")
    # Regex for plain chapter headings     (## Title)  — no leading digit+dot
    _plain_h  = re.compile(r"^(#{1,2})\s+(?!\d+\.\s)(.+)$")
    # HR divider
    _hr       = re.compile(r"^\s*-{3,}\s*$")

    while i < n:
        line = lines[i]

        # ── Numbered heading: look ahead for an immediate plain echo ──
        if _numbered.match(line.strip()):
            # Extract bare title text from numbered heading
            numbered_bare = re.sub(r"^#{1,2}\s+\d+\.\s*", "", line.strip()).strip().lower()
            out.append(line)
            i += 1
            # Skip any following blank lines + optional duplicate heading
            while i < n and not lines[i].strip():
                i += 1
            if i < n:
                next_stripped = lines[i].strip()
                # Case A: plain-echo heading (## Title without number)
                plain_match = _plain_h.match(next_stripped)
                if plain_match:
                    plain_bare = plain_match.group(2).strip().lower()
                    if plain_bare == numbered_bare or numbered_bare.endswith(plain_bare):
                        # It's the duplicate — skip it
                        i += 1
                        # Also skip the HR divider that immediately follows the echo
                        while i < n and not lines[i].strip():
                            i += 1
                        if i < n and _hr.match(lines[i]):
                            i += 1
                    # else: keep — it's a different heading
                # Case B: duplicate numbered heading (## N. Title repeated)
                elif _numbered.match(next_stripped):
                    dup_bare = re.sub(
                        r"^#{1,2}\s+\d+\.\s*", "", next_stripped
                    ).strip().lower()
                    if dup_bare == numbered_bare:
                        # Exact same chapter title repeated — skip the duplicate
                        i += 1
                        while i < n and not lines[i].strip():
                            i += 1
                        if i < n and _hr.match(lines[i]):
                            i += 1
            continue

        # ── HR directly after a heading line (already appended above) ──
        # Catch any remaining `---` that immediately follow a heading in out[]
        if _hr.match(line.strip()):
            # Only suppress if the previous non-blank output line was a heading
            prev = next((output_line for output_line in reversed(out) if output_line.strip()), "")
            if re.match(r"^#{1,4}\s+", prev.strip()):
                i += 1
                continue

        out.append(line)
        i += 1

    # Collapse runs of >2 blank lines
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return result


# ─────────────────────────────────────────────────────────────────────
# METADATA EXTRACTOR
# ─────────────────────────────────────────────────────────────────────

def _extract_metadata_table(md: str) -> dict[str, str]:
    """Extract the top-level metadata table (Field | Value) from the memo."""
    meta: dict[str, str] = {}
    in_table = False
    for line in md.split("\n"):
        stripped = line.strip()
        if stripped.startswith("| **") or stripped.startswith("|:---"):
            in_table = True
        if in_table and stripped.startswith("|"):
            cols = [c.strip() for c in stripped.split("|")]
            cols = [c for c in cols if c]
            if len(cols) >= 2:
                key = re.sub(r"\*\*", "", cols[0]).strip()
                val = re.sub(r"\*\*", "", cols[1]).strip()
                if key and not key.startswith(":---"):
                    meta[key] = val
        elif in_table and not stripped.startswith("|"):
            break
    return meta


# ─────────────────────────────────────────────────────────────────────
# MARKDOWN TABLE PARSER
# ─────────────────────────────────────────────────────────────────────

def _parse_md_table(lines: list[str]) -> list[list[str]] | None:
    """Parse a markdown table (|col|col|...) into list-of-rows."""
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            return rows if len(rows) >= 2 else None
        cols = [c.strip() for c in stripped.split("|")]
        cols = [c for c in cols if c != ""]
        if all(re.match(r"^:?-+:?$", c) for c in cols):
            continue
        if cols:
            rows.append(cols)
    return rows if len(rows) >= 2 else None


# ─────────────────────────────────────────────────────────────────────
# INLINE MARKDOWN → REPORTLAB XML
# ─────────────────────────────────────────────────────────────────────

def _md_inline(text: str) -> str:
    """Convert inline markdown (bold, italic, code) to reportlab XML.

    Also normalises Unicode dashes so compound words like "above-average"
    render correctly in Helvetica (WinAnsiEncoding).
    """
    text = _normalise_unicode_dashes(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__",     r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*",     r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r"<font face='Courier' size='8'>\1</font>", text)
    return text


# ─────────────────────────────────────────────────────────────────────
# MARKDOWN → STORY BUILDER
# ─────────────────────────────────────────────────────────────────────

# Headings to skip entirely (cover / ToC only)
_SKIP_HEADING_EXACT = {
    "table of contents",
    "investment memorandum",
}
# Headings to skip if they match the deal name (handled separately)
def _skip_deal_heading(heading: str, deal: str) -> bool:
    return heading.lower() == deal.lower()

def _build_story_from_md(
    md_text: str,
    styles: dict,
    *,
    deal_name: str = "",
    chart_data_index: dict[str, dict] | None = None,
) -> list[Any]:
    """Convert *pre-processed* markdown into a ReportLab Story list.

    Key rules:
    - Numbered ``## N. Title`` headings trigger a PageBreak + section_heading.
    - Plain ``## Title`` headings that are NOT skipped become section_headings
      WITHOUT a preceding PageBreak (they appear mid-chapter, e.g. summary
      repeated at the end — rare after normalisation).
    - ``### / ####`` become subsection headings.
    - Only ONE PageBreak per chapter boundary (no double-breaks).
    - ``<!-- CHART:type:title -->`` triggers chart rendering via chart_data_index.
    - ``<!-- CHARTDATA:json -->`` is stripped (data-only, invisible to readers).
    """
    story: list[Any] = []
    lines = md_text.split("\n")
    i = 0
    n = len(lines)

    found_first_chapter = False

    # Patterns
    _numbered_h = re.compile(r"^(#{1,2})\s+(\d+)\.\s+(.+)$")   # ## N. Title
    _any_h12    = re.compile(r"^(#{1,2})\s+(.+)$")              # ## Title
    _sub_h      = re.compile(r"^(#{3,6})\s+(.+)$")              # ### Title

    def _is_skip_heading(text: str) -> bool:
        t = text.lower().strip()
        if t in _SKIP_HEADING_EXACT:
            return True
        if t.startswith("investment memorandum"):
            return True
        if deal_name and t == deal_name.lower():
            return True
        return False

    while i < n:
        line  = lines[i]
        stripped = line.strip()

        # ── Numbered chapter heading  (## N. Title) ──────────────────
        m_num = _numbered_h.match(stripped)
        if m_num:
            heading_text = f"{m_num.group(2)}. {m_num.group(3).strip()}"
            heading_text = re.sub(r"\*\*", "", heading_text)
            if _is_skip_heading(m_num.group(3).strip()):
                i += 1
                continue
            if found_first_chapter:
                story.append(PageBreak())
            found_first_chapter = True
            story.append(Paragraph(safe_text(heading_text), styles["section_heading"]))
            i += 1
            continue

        # ── Plain H1/H2 heading  (## Title, no leading digit) ────────
        m_h12 = _any_h12.match(stripped)
        if m_h12 and not stripped.startswith("###"):
            heading_text = m_h12.group(2).strip()
            heading_text = re.sub(r"\*\*", "", heading_text)
            if _is_skip_heading(heading_text):
                i += 1
                continue
            # After normalisation these should be rare; treat as chapter start
            if found_first_chapter:
                story.append(PageBreak())
            found_first_chapter = True
            story.append(Paragraph(safe_text(heading_text), styles["section_heading"]))
            i += 1
            continue

        # Skip content before the first chapter
        if not found_first_chapter:
            i += 1
            continue

        # ── Sub-heading  (### or deeper) ─────────────────────────────
        m_sub = _sub_h.match(stripped)
        if m_sub:
            sub_text = re.sub(r"\*\*", "", m_sub.group(2).strip())
            story.append(Paragraph(safe_text(sub_text), styles["subsection"]))
            i += 1
            continue

        # ── HTML anchors (skip) ───────────────────────────────────────
        if stripped.startswith("<a ") or stripped.startswith("</a>"):
            i += 1
            continue

        # ── CHARTDATA comment (strip — data-only, never display) ─────
        if stripped.startswith("<!-- CHARTDATA:"):
            i += 1
            continue

        # ── CHART marker — render chart or DATA_GAP ──────────────────
        if stripped.startswith("<!-- CHART:"):
            m_chart = _CHART_MARKER_RE.match(stripped)
            if m_chart:
                flowables = _resolve_chart_marker(
                    m_chart, chart_data_index or {}, styles
                )
                story.extend(flowables)
                i += 1
                continue
            # Unknown HTML comment — skip
            i += 1
            continue

        # ── Horizontal rule ───────────────────────────────────────────
        if re.match(r"^-{3,}$", stripped) or re.match(r"^\*{3,}$", stripped):
            story.append(HRFlowable(
                width="100%", thickness=0.3, color=MED_GREY, spaceAfter=3 * mm,
            ))
            i += 1
            continue

        # ── Markdown table ────────────────────────────────────────────
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_lines: list[str] = []
            while i < n and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            parsed = _parse_md_table(table_lines)
            if parsed:
                num_cols  = max(len(r) for r in parsed)
                available = A4[0] - 30 * mm
                col_w     = available / num_cols
                cleaned   = [
                    [safe_text(_md_inline(re.sub(r"\*\*", "", c))) for c in row]
                    for row in parsed
                ]
                story.append(build_institutional_table(
                    cleaned,
                    col_widths=[col_w] * num_cols,
                    styles=styles,
                ))
                story.append(Spacer(1, 3 * mm))
            continue

        # ── Bullet / numbered list item ───────────────────────────────
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            bullet_text = re.sub(r"^[-*]\s+", "", stripped)
            bullet_text = re.sub(r"^\d+\.\s+", "", bullet_text)
            story.append(Paragraph(
                f"•  {_md_inline(safe_text(bullet_text))}", styles["body"],
            ))
            i += 1
            continue

        # ── Block quote ───────────────────────────────────────────────
        if stripped.startswith(">"):
            quote_text = stripped.lstrip("> ").strip()
            story.append(Paragraph(
                f"<i>{_md_inline(safe_text(quote_text))}</i>", styles["disclaimer"],
            ))
            i += 1
            continue

        # ── Empty line → small spacer (one per run) ───────────────────
        if not stripped:
            i += 1
            continue

        # ── Regular paragraph (accumulate consecutive body lines) ─────
        para_lines: list[str] = []
        while i < n:
            cl = lines[i].strip()
            if not cl:
                i += 1
                break
            # Stop on any special line
            if (cl.startswith("#") or cl.startswith("|") or cl.startswith("<a ")
                    or re.match(r"^[-*]\s+", cl) or re.match(r"^\d+\.\s+", cl)
                    or re.match(r"^-{3,}$", cl)):
                break
            para_lines.append(cl)
            i += 1

        if para_lines:
            story.append(Paragraph(
                _md_inline(safe_text(" ".join(para_lines))),
                styles["body"],
            ))

    return story


# ─────────────────────────────────────────────────────────────────────
# HEADER / FOOTER WRAPPER
# Page 1 = cover (no header).
# Page 2 = ToC  → we want header here too, so leave default behaviour.
# ─────────────────────────────────────────────────────────────────────

def _make_hf(report_title: str):
    def _hf(canvas: Any, doc_inner: Any) -> None:
        netz_header_footer(
            canvas, doc_inner,
            report_title=report_title,
            confidentiality="CONFIDENTIAL — FOR INVESTMENT COMMITTEE USE ONLY",
        )
    return _hf


# ─────────────────────────────────────────────────────────────────────
# MAIN PDF GENERATOR
# ─────────────────────────────────────────────────────────────────────

def generate_memo_pdf(
    md_path: str,
    output_path: str | None = None,
) -> str:
    """Read a markdown investment memo and produce an institutional PDF."""
    with open(md_path, "r", encoding="utf-8") as f:
        raw_md = f.read()

    # 1. Pre-process: normalise Unicode dashes + remove LLM structural noise
    md_text = _normalise_unicode_dashes(_normalise_md(raw_md))

    # 2. Extract metadata
    meta          = _extract_metadata_table(md_text)
    deal_name     = meta.get("Deal Name", "")
    if not deal_name:
        h1 = re.search(r"^#\s+Investment Memorandum\s*[—–-]\s*(.+)$", md_text, re.MULTILINE)
        deal_name = h1.group(1).strip() if h1 else "Unknown Deal"

    recommendation = meta.get("IC Recommendation", "CONDITIONAL")
    generated      = meta.get("Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    version_tag    = meta.get("Version Tag", "")

    # 3. Build document
    styles       = build_netz_styles()
    buf          = BytesIO()
    report_title = f"Investment Memorandum — {deal_name}"
    doc          = create_netz_document(buf, title=report_title)
    _hf          = _make_hf(report_title)

    # ── Extract chart data index from embedded CHARTDATA comments ─────
    # Chart data is embedded as <!-- CHARTDATA:{...} --> adjacent to each
    # <!-- CHART:type:title --> marker. Scanning once here means charts
    # render even on PDF regeneration from cached chapter markdown.
    chart_data_index = extract_chart_index(md_text)

    story: list[Any] = []

    # ── Cover page ────────────────────────────────────────────────────
    story.extend(_pdf_base_cover(
        report_type="Investment Memorandum",
        deal_name=deal_name,
        sponsor="",
        signal=recommendation,
        generated_at=generated,
        version_tag=version_tag,
        styles=styles,
    ))
    story.append(PageBreak())

    # ── Table of Contents ─────────────────────────────────────────────
    story.append(Paragraph("Table of Contents", styles["section_heading"]))
    story.append(Spacer(1, 4 * mm))
    for m in re.finditer(r"^##\s+(\d+)\.\s+(.+)$", md_text, re.MULTILINE):
        ch_num   = m.group(1)
        ch_title = re.sub(r"\*\*", "", m.group(2).strip())
        story.append(Paragraph(
            f"<b>{safe_text(ch_num)}.</b>  {safe_text(ch_title)}",
            styles["body"],
        ))
    story.append(PageBreak())

    # ── Body chapters ─────────────────────────────────────────────────
    story.extend(_build_story_from_md(
        md_text, styles, deal_name=deal_name, chart_data_index=chart_data_index,
    ))

    # ── Disclaimer ────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(
        width="100%", thickness=0.3, color=MED_GREY, spaceAfter=3 * mm,
    ))
    story.append(Paragraph(
        "DISCLAIMER: This memorandum was generated by Netz International's AI-assisted "
        "underwriting pipeline and is intended as a decision-support tool for the "
        "Investment Committee. It does not constitute investment advice. All factual "
        "claims are grounded in the ingested Evidence Pack; items marked 'not confirmed "
        "in provided documentation' require further sponsor disclosure. AI-generated "
        "content may contain errors or omissions. This document is confidential and "
        "intended for authorised IC personnel only.",
        styles["disclaimer"],
    ))

    # ── Build PDF ─────────────────────────────────────────────────────
    doc.build(story, onFirstPage=_hf, onLaterPages=_hf)

    if not output_path:
        output_path = os.path.splitext(md_path)[0] + ".pdf"

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())

    return output_path


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert Investment Memo Markdown to Institutional PDF"
    )
    parser.add_argument("--input",  "-i", required=True, help="Input .md file")
    parser.add_argument("--output", "-o", help="Output .pdf file (auto-named if omitted)")
    args = parser.parse_args()

    print("\n" + "=" * 72)
    print("  NETZ AI - INVESTMENT MEMO PDF (Markdown -> ReportLab)")
    print("=" * 72)

    if not os.path.exists(args.input):
        print(f"  ERROR: File not found: {args.input}")
        return

    print(f"\n  Input:  {args.input}")
    print(f"  Size:   {os.path.getsize(args.input)/1024:.1f} KB")

    out = generate_memo_pdf(args.input, args.output)

    print(f"\n  Output: {out}")
    print(f"  Size:   {os.path.getsize(out)/1024:.1f} KB")
    print("\n" + "=" * 72 + "\n")


if __name__ == "__main__":
    main()
