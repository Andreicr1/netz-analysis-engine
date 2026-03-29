"""Core Playwright HTML→PDF renderer.

Single responsibility: receive a self-contained HTML string, render to PDF bytes.
All templates are rendered by the caller before invoking this module.

Both async and sync entry points available:
- ``html_to_pdf()`` — for use in async routes / workers
- ``html_to_pdf_sync()`` — for use inside ``asyncio.to_thread()`` or pure sync code
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()


async def html_to_pdf(
    html: str,
    *,
    format: str = "A4",
    print_background: bool = True,
    margin_mm: int = 0,
) -> bytes:
    """Render self-contained HTML to PDF bytes via Playwright Chromium.

    Parameters
    ----------
    html:
        Complete, self-contained HTML (inline CSS, inline SVG, no external refs).
    format:
        Page format string accepted by Playwright (default "A4").
    print_background:
        Whether to print CSS backgrounds (required for dark headers).
    margin_mm:
        Uniform page margin in mm (0 = full bleed, recommended for cover pages).

    Returns
    -------
    bytes
        Raw PDF bytes.

    Raises
    ------
    RuntimeError
        If Playwright or Chromium is unavailable.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed. Add it to requirements and run "
            "'playwright install chromium --with-deps'."
        ) from exc

    margin = f"{margin_mm}mm"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            pdf_bytes = await page.pdf(
                format=format,
                print_background=print_background,
                margin={
                    "top": margin,
                    "right": margin,
                    "bottom": margin,
                    "left": margin,
                },
            )
        finally:
            await browser.close()

    logger.info("pdf_rendered", size_bytes=len(pdf_bytes), format=format)
    return pdf_bytes


def html_to_pdf_sync(
    html: str,
    *,
    format: str = "A4",
    print_background: bool = True,
    margin_mm: int = 0,
) -> bytes:
    """Sync version of ``html_to_pdf``. Uses Playwright sync API.

    Safe to call from ``asyncio.to_thread()`` or pure sync code.
    Do NOT call from an async context — use ``html_to_pdf()`` instead.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed. Add it to requirements and run "
            "'playwright install chromium --with-deps'."
        ) from exc

    margin = f"{margin_mm}mm"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="domcontentloaded")
            pdf_bytes = page.pdf(
                format=format,
                print_background=print_background,
                margin={
                    "top": margin,
                    "right": margin,
                    "bottom": margin,
                    "left": margin,
                },
            )
        finally:
            browser.close()

    logger.info("pdf_rendered_sync", size_bytes=len(pdf_bytes), format=format)
    return pdf_bytes
