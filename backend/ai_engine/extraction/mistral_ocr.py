"""Mistral OCR — PDF to markdown with HTML tables.

Extracted from legacy ``prepare_pdfs_full.py`` into a standalone async-first
module for the backend-native ingestion pipeline.

Uses ``mistral-ocr-latest`` via the public Mistral API.
Capabilities: table_format="html", handles scanned PDFs, base64 upload.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# ── API constants ────────────────────────────────────────────────────
MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"
MISTRAL_MODEL = "mistral-ocr-latest"
MISTRAL_MAX_PAGES = 1000
MISTRAL_MAX_FILE_MB = 250
MISTRAL_MAX_FILE_BYTES = MISTRAL_MAX_FILE_MB * 1024 * 1024
_TIMEOUT = 180  # seconds — large PDFs can take a while


@dataclass(frozen=True)
class PageBlock:
    """A page-tagged block of markdown text from OCR."""
    page_start: int
    page_end: int
    text: str


# ── Token-bucket rate limiter ────────────────────────────────────────


class _TokenBucket:
    """Simple async token-bucket rate limiter."""

    def __init__(self, rate: float):
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


# Module-level rate limiter — initialized lazily
_rate_limiter: _TokenBucket | None = None


def _get_rate_limiter() -> _TokenBucket:
    global _rate_limiter  # noqa: PLW0603
    if _rate_limiter is None:
        from app.core.config.settings import settings
        _rate_limiter = _TokenBucket(settings.MISTRAL_OCR_RATE_LIMIT)
    return _rate_limiter


# ── PDF page extraction via pymupdf ─────────────────────────────────


def _pdf_to_base64(pdf_bytes: bytes, start_page: int = 0, end_page: int | None = None) -> str:
    """Extract pages [start_page, end_page) from PDF bytes and return base64."""
    import fitz  # pymupdf

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        total = len(doc)
        if end_page is None or end_page > total:
            end_page = total

        with fitz.open() as out:
            for p in range(start_page, end_page):
                out.insert_pdf(doc, from_page=p, to_page=p)
            data = out.tobytes()

    if len(data) > MISTRAL_MAX_FILE_BYTES:
        raise ValueError(
            f"PDF batch pages {start_page + 1}–{end_page} exceeds "
            f"{MISTRAL_MAX_FILE_MB} MB limit."
        )
    return base64.b64encode(data).decode()


def _get_page_count(pdf_bytes: bytes) -> int:
    import fitz
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return len(doc)


# ── Core OCR call ────────────────────────────────────────────────────


def _build_payload(pdf_b64: str) -> dict:
    return {
        "model": MISTRAL_MODEL,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_b64}",
        },
        "table_format": "html",
        "include_image_base64": False,
    }


def _parse_ocr_response(data: dict) -> list[PageBlock]:
    """Parse Mistral OCR JSON response into PageBlocks."""
    pages = data.get("pages", [])
    if not pages:
        text = data.get("text", "") or data.get("content", "")
        if text:
            return [PageBlock(page_start=1, page_end=1, text=text)]
        return []

    blocks: list[PageBlock] = []
    for i, p in enumerate(pages, start=1):
        md = p.get("markdown", "") or p.get("text", "")
        # Replace [tbl-X.html](tbl-X.html) placeholders with actual HTML
        for tbl in p.get("tables", []):
            tbl_id = tbl.get("id", "")
            content = tbl.get("content", "")
            if tbl_id and content:
                md = md.replace(f"[{tbl_id}]({tbl_id})", content)
        if md.strip():
            page_num = p.get("page_number", i)
            blocks.append(PageBlock(page_start=page_num, page_end=page_num, text=md))
    return blocks


# ── Async API ────────────────────────────────────────────────────────

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0


async def async_extract_pdf_with_mistral(
    pdf_bytes: bytes,
    *,
    api_key: str | None = None,
) -> list[PageBlock]:
    """Extract text from a PDF via Mistral OCR (async).

    Automatically batches large PDFs (>1000 pages).
    Returns list of PageBlocks with page provenance.

    Raises:
        RuntimeError: On API errors after retries exhausted.
        ValueError: If api_key is not provided and not configured.
    """
    if api_key is None:
        from app.core.config.settings import settings
        api_key = settings.MISTRAL_API_KEY
    if not api_key:
        raise ValueError("MISTRAL_API_KEY not configured")

    total_pages = _get_page_count(pdf_bytes)
    if total_pages == 0:
        return []

    # Build batch ranges
    ranges = [
        (s, min(s + MISTRAL_MAX_PAGES, total_pages))
        for s in range(0, total_pages, MISTRAL_MAX_PAGES)
    ]

    all_blocks: list[PageBlock] = []
    limiter = _get_rate_limiter()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for batch_idx, (start, end) in enumerate(ranges):
            if len(ranges) > 1:
                logger.info(
                    "Mistral OCR batch %d/%d (pages %d–%d)",
                    batch_idx + 1, len(ranges), start + 1, end,
                )

            b64 = _pdf_to_base64(pdf_bytes, start, end)
            payload = _build_payload(b64)

            # Retry with exponential backoff on 429 / 5xx
            for attempt in range(_MAX_RETRIES):
                await limiter.acquire()
                try:
                    resp = await client.post(
                        MISTRAL_OCR_URL,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {api_key}",
                        },
                        json=payload,
                    )

                    if resp.status_code == 200:
                        blocks = _parse_ocr_response(resp.json())
                        # Adjust page numbers for batched PDFs
                        if start > 0:
                            blocks = [
                                PageBlock(
                                    page_start=b.page_start + start,
                                    page_end=b.page_end + start,
                                    text=b.text,
                                )
                                for b in blocks
                            ]
                        all_blocks.extend(blocks)
                        break

                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < _MAX_RETRIES - 1:
                        wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                        logger.warning(
                            "Mistral OCR HTTP %d — retrying in %.1fs (attempt %d/%d)",
                            resp.status_code, wait, attempt + 1, _MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue

                    logger.debug("Mistral OCR error response: %s", resp.text[:500])
                    raise RuntimeError(
                        f"Mistral OCR failed with HTTP {resp.status_code}"
                    )

                except httpx.TimeoutException:
                    if attempt < _MAX_RETRIES - 1:
                        wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                        logger.warning(
                            "Mistral OCR timeout — retrying in %.1fs (attempt %d/%d)",
                            wait, attempt + 1, _MAX_RETRIES,
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise RuntimeError("Mistral OCR timed out after all retries")

    logger.info(
        "Mistral OCR complete: %d pages → %d blocks, %d chars",
        total_pages,
        len(all_blocks),
        sum(len(b.text) for b in all_blocks),
    )
    return all_blocks


# ── Sync wrapper ─────────────────────────────────────────────────────


def extract_pdf_with_mistral(
    pdf_bytes: bytes,
    *,
    api_key: str | None = None,
) -> list[PageBlock]:
    """Sync wrapper around ``async_extract_pdf_with_mistral``."""
    return asyncio.run(async_extract_pdf_with_mistral(pdf_bytes, api_key=api_key))
