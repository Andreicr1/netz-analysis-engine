"""Executive fact-sheet renderer (Playwright HTML→PDF).

Delegates to ``vertical_engines.wealth.pdf.templates.fact_sheet_executive``
for the actual HTML rendering. This module exists as a stable import target
for the fact_sheet package — callers may import from here or from the
pdf.templates module directly.

The FactSheetEngine orchestrates data loading and calls the renderer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vertical_engines.wealth.pdf.templates.fact_sheet_executive import (
    render_fact_sheet_executive,
)

if TYPE_CHECKING:
    from vertical_engines.wealth.fact_sheet.i18n import Language
    from vertical_engines.wealth.fact_sheet.models import FactSheetData

__all__ = ["render_executive"]


def render_executive(
    data: FactSheetData,
    *,
    language: Language = "pt",
) -> str:
    """Render 1-2 page Executive Fact Sheet as self-contained HTML.

    Parameters
    ----------
    data:
        Frozen ``FactSheetData`` bundle built by ``FactSheetEngine``.
    language:
        ``"pt"`` or ``"en"`` for bilingual labels.

    Returns
    -------
    str
        Complete HTML ready for Playwright ``page.pdf()``.
    """
    return render_fact_sheet_executive(data, language=language)
