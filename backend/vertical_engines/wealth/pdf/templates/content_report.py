"""Generic content report HTML template — Netz Premium Institutional System Design Doctrine.

Used by three content engines:

- **Investment Outlook** (quarterly macro narrative)
- **Flash Report** (event-driven market flash)
- **Manager Spotlight** (deep-dive single fund manager)

Design pillars (aligned with Fact Sheet Institutional):

1. **Typography** — Playfair Display headings, Inter body, line-height 1.65.
2. **No SaaS widgets** — no coloured metric boxes.  Hairline separators only.
3. **Pull quotes** — markdown ``> blockquotes`` rendered as Playfair Display Italic
   callouts with oversized directional quotation mark.
4. **Tufte tables** — clean thead/tbody, no cell borders, alternating slate-50.
5. **Radar chart** — optional scoring-component spider web.
6. **Rich Navy header** — #0A192F with copper accent rule.

Receives markdown content and renders it with a branded header.
All user-supplied text is escaped via ``html.escape()``.
Bilingual PT/EN via ``i18n.LABELS[language]``.
"""

from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

from vertical_engines.wealth.fact_sheet.i18n import LABELS, Language, format_date
from vertical_engines.wealth.pdf.svg_charts import radar_chart

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _e(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def _apply_bold(text: str) -> str:
    """Replace **text** with <strong>text</strong> in already-escaped HTML."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)


# ---------------------------------------------------------------------------
# Markdown → HTML (with pull quotes + Tufte tables)
# ---------------------------------------------------------------------------


def _flush_table(result: list[str], rows: list[str]) -> None:
    """Render accumulated markdown table rows as a Tufte HTML table."""
    cells: list[list[str]] = []
    for row in rows:
        # Skip separator rows (only pipes, dashes, colons, spaces)
        stripped_content = row.strip("| \t")
        if stripped_content and all(c in "-: " for c in stripped_content):
            continue
        cols = [c.strip() for c in row.strip("|").split("|")]
        cells.append(cols)

    if len(cells) < 2:
        return

    headers = cells[0]
    data_rows = cells[1:]

    result.append('<table class="tt">')
    result.append("<thead><tr>")
    for h in headers:
        result.append(f"<th>{_e(h)}</th>")
    result.append("</tr></thead><tbody>")
    for row_cells in data_rows:
        result.append("<tr>")
        for i, cell in enumerate(row_cells):
            align = ' style="text-align:right"' if i > 0 else ""
            result.append(f"<td{align}>{_apply_bold(_e(cell))}</td>")
        result.append("</tr>")
    result.append("</tbody></table>")


def _md_to_html(content_md: str) -> str:
    """Convert simplified markdown to HTML.

    Handles: ``# / ##`` headings (Playfair Display), ``> blockquotes``
    (→ pull quotes), ``- / * / 1.`` lists, ``| table |`` rows (→ Tufte
    tables), ``**bold**``, paragraphs, empty-line spacers.
    """
    if not content_md:
        return ""

    lines = content_md.strip().split("\n")
    result: list[str] = []
    in_ul = False
    in_ol = False
    in_bq = False
    in_table = False
    table_rows: list[str] = []

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
            if in_table:
                _flush_table(result, table_rows)
                in_table = False
                table_rows = []
            result.append('<div class="v-sp"></div>')
            continue

        # ── Table row ──
        if stripped.startswith("|") and stripped.endswith("|"):
            _close_lists()
            if in_bq:
                result.append("</blockquote>")
                in_bq = False
            if not in_table:
                in_table = True
                table_rows = []
            table_rows.append(stripped)
            continue

        if in_table:
            _flush_table(result, table_rows)
            in_table = False
            table_rows = []

        # ── Blockquote → Pull quote ──
        if stripped.startswith("> "):
            _close_lists()
            if not in_bq:
                result.append('<blockquote class="pq">')
                result.append('<span class="pq-mark">\u201C</span>')
                in_bq = True
            text = _apply_bold(_e(stripped[2:]))
            result.append(f'<p class="pq-text">{text}</p>')
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
    if in_table:
        _flush_table(result, table_rows)

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
    width: 210mm; min-height: 297mm;
    position: relative; overflow: hidden;
    page-break-after: always; background: var(--white);
}
.page:last-child { page-break-after: auto; }

/* ══════════════════════  HEADER  ══════════════════════ */
.hd {
    background: var(--navy);
    padding: 34px 48px 28px;
    border-bottom: 2px solid var(--copper);
}
.hd-label {
    font-size: 7.5px; letter-spacing: 0.16em;
    color: var(--slate-500); text-transform: uppercase;
    margin-bottom: 10px;
}
.hd-title {
    font-family: 'Playfair Display', serif;
    font-size: 24px; font-weight: 700;
    color: var(--white); letter-spacing: 0.01em;
    line-height: 1.2;
}
.hd-subtitle {
    font-size: 13px; color: var(--slate-300);
    margin-top: 6px; letter-spacing: 0.01em;
}
.hd-date {
    font-size: 9px; color: var(--slate-500);
    margin-top: 10px; letter-spacing: 0.03em;
}

/* ══════════════════════  BODY  ══════════════════════ */
.body {
    padding: 28px 48px 72px;
}

/* ══════════════════════  TYPOGRAPHY  ══════════════════════ */
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
    font-size: 14px; font-weight: 700;
    color: var(--navy); margin: 22px 0 10px;
}
.sh {
    font-family: 'Playfair Display', serif;
    font-size: 12px; font-weight: 600;
    color: var(--slate-900); margin: 18px 0 8px;
    padding-bottom: 4px;
    border-bottom: 0.5px solid var(--slate-200);
}
.v-sp { height: 10px; }

/* ── Pull quote ── */
.pq {
    margin: 26px 15% 26px 0;
    padding: 20px 0 20px 30px;
    position: relative;
}
.pq-mark {
    position: absolute; left: 0; top: 6px;
    font-family: 'Playfair Display', serif;
    font-size: 48px; color: var(--slate-200); line-height: 1;
}
.pq-text {
    font-family: 'Playfair Display', serif;
    font-style: italic; font-size: 14px;
    line-height: 1.55; color: var(--slate-700);
    padding-left: 22px;
}

/* ── Tufte table ── */
.tt {
    border-collapse: collapse; width: 100%;
    margin: 12px 0; font-variant-numeric: tabular-nums;
}
.tt thead th {
    font-size: 7.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--slate-500); text-align: left;
    padding: 6px 8px 4px;
    border-bottom: 1.5px solid var(--navy); border-top: none;
}
.tt tbody td {
    font-size: 9px; padding: 5px 8px;
    border-bottom: none; color: var(--text-secondary);
}
.tt tbody tr:nth-child(even) td {
    background: var(--slate-50);
}

/* ── Radar container ── */
.radar-wrap {
    display: flex; justify-content: center;
    margin: 14px 0 20px;
}

/* ── Footer ── */
.ft {
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 10px 48px;
    font-size: 7px; color: var(--slate-400);
    border-top: 0.5px solid var(--slate-200);
    display: flex; justify-content: space-between;
    letter-spacing: 0.02em;
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_content_report(
    content_md: str,
    *,
    title: str,
    subtitle: str = "",
    language: Language = "en",
    scoring_components: dict[str, float] | None = None,
) -> str:
    """Render markdown content as a branded Netz HTML report.

    Parameters
    ----------
    content_md:
        Markdown text (``# heading``, ``## sub``, ``> quote``, ``**bold**``,
        ``- items``, ``| table |``, paragraphs).
    title:
        Cover title (e.g. "Investment Outlook", "Market Flash Report").
    subtitle:
        Optional subtitle (e.g. fund name for Manager Spotlight).
    language:
        ``"pt"`` or ``"en"`` for bilingual labels and dates.
    scoring_components:
        Optional dict of scoring-component name → score (0–100) for a radar
        chart rendered at the top of the body.

    Returns
    -------
    str
        Complete HTML ready for Playwright PDF rendering.
    """
    labels = LABELS[language]
    today = date.today()

    # ── Header ──
    subtitle_html = ""
    if subtitle:
        subtitle_html = f'<div class="hd-subtitle">{_e(subtitle)}</div>'

    header = (
        f'<div class="hd">'
        f'<div class="hd-label">{_e(labels["confidential"])}</div>'
        f'<div class="hd-title">{_e(title)}</div>'
        f"{subtitle_html}"
        f'<div class="hd-date">{format_date(today, language)}</div>'
        f"</div>"
    )

    # ── Optional radar chart ──
    radar_html = ""
    if scoring_components:
        radar_html = (
            f'<div class="radar-wrap">'
            f"{radar_chart(scoring_components, width=240, height=240)}"
            f"</div>"
        )

    # ── Content body ──
    content_html = _md_to_html(content_md)

    # ── Footer ──
    footer = (
        f'<div class="ft">'
        f"<span>{_e(labels['confidential'])}</span>"
        f"<span>{format_date(today, language)}</span>"
        f"</div>"
    )

    body = (
        f'<div class="page">'
        f"{header}"
        f'<div class="body">'
        f"{radar_html}"
        f"{content_html}"
        f"</div>"
        f"{footer}"
        f"</div>"
    )

    doc_title = f"{title} &mdash; {subtitle}" if subtitle else title

    return (
        f"<!DOCTYPE html>"
        f'<html lang="{_e(language)}">'
        f"<head>"
        f'<meta charset="utf-8"/>'
        f"<title>{_e(doc_title)}</title>"
        f"<style>{_CSS}</style>"
        f"</head>"
        f"<body>{body}</body>"
        f"</html>"
    )
