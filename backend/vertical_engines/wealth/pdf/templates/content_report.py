"""Generic content report HTML template (1-3 page A4, rendered via Playwright).

Used by three content engines:
- Investment Outlook
- Flash Report
- Manager Spotlight

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FONT_STACK = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def _e(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def _md_to_html(content_md: str) -> str:
    """Convert simplified markdown to HTML.

    Handles: ## headings, **bold**, - list items, and paragraph breaks.
    """
    if not content_md:
        return ""

    lines = content_md.strip().split("\n")
    result: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                result.append("</ul>")
                in_list = False
            result.append('<div style="height:10px"></div>')
            continue

        if stripped.startswith("## "):
            if in_list:
                result.append("</ul>")
                in_list = False
            text = _apply_bold(_e(stripped[3:]))
            result.append(
                f'<h3 style="font-size:12px;font-weight:600;color:#111827;'
                f'margin:16px 0 6px;border-bottom:1px solid #e5e7eb;'
                f'padding-bottom:4px">{text}</h3>'
            )
        elif stripped.startswith("# "):
            if in_list:
                result.append("</ul>")
                in_list = False
            text = _apply_bold(_e(stripped[2:]))
            result.append(
                f'<h2 style="font-size:13px;font-weight:700;color:#111827;'
                f'margin:12px 0 6px">{text}</h2>'
            )
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                result.append(
                    '<ul style="margin:4px 0;padding-left:18px;font-size:10px;'
                    'line-height:1.6;color:#374151">'
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
                f'<p style="font-size:10px;line-height:1.6;color:#374151;'
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
# Public API
# ---------------------------------------------------------------------------


def render_content_report(
    content_md: str,
    *,
    title: str,
    subtitle: str = "",
    language: Language = "en",
) -> str:
    """Render markdown content as a branded Netz HTML report.

    Parameters
    ----------
    content_md:
        Markdown text (``## heading``, ``**bold**``, ``- items``, paragraphs).
    title:
        Cover title (e.g. "Investment Outlook", "Market Flash Report").
    subtitle:
        Optional subtitle (e.g. fund name for Manager Spotlight).
    language:
        ``"pt"`` or ``"en"`` for bilingual labels and dates.

    Returns
    -------
    str
        Complete HTML ready for Playwright PDF rendering.
    """
    labels = LABELS[language]
    today = date.today()

    # Header
    subtitle_html = ""
    if subtitle:
        subtitle_html = (
            f'<div style="font-size:14px;color:#D1D5DB;margin-top:4px">'
            f"{_e(subtitle)}</div>"
        )

    header = (
        f'<div style="background:#111827;padding:28px 36px">'
        f'<div style="font-size:9px;letter-spacing:.14em;color:#6B7FA8;'
        f'text-transform:uppercase;margin-bottom:6px">{_e(labels["confidential"])}</div>'
        f'<div style="font-size:20px;font-weight:500;color:#F9FAFB;'
        f'letter-spacing:.02em">{_e(title)}</div>'
        f"{subtitle_html}"
        f'<div style="font-size:11px;color:#6B7FA8;margin-top:6px">'
        f"{format_date(today, language)}</div>"
        f"</div>"
    )

    # Content
    content_html = _md_to_html(content_md)

    # Footer
    footer = (
        f'<div style="position:absolute;bottom:0;left:0;right:0;padding:10px 24px;'
        f"font-size:8px;color:#9ca3af;border-top:1px solid #e5e7eb;"
        f'display:flex;justify-content:space-between">'
        f"<span>{_e(labels['confidential'])}</span>"
        f"<span>{format_date(today, language)}</span>"
        f"</div>"
    )

    body = (
        f'<div class="page">'
        f"{header}"
        f'<div style="padding:20px 36px 64px">'
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
