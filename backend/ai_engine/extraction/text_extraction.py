"""Text extraction layer — Blob → structured pages.

Supports:
- PDF via Mistral OCR (primary, when MISTRAL_API_KEY configured)
- PDF via pypdf (fallback)
- Azure Document Intelligence fallback for scanned PDFs (optional)
- DOCX (via python-docx)
- TXT, MD, CSV (UTF-8)

All functions return a list of page dicts:
  [{"page_start": int, "page_end": int, "text": str}]
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
from typing import TypedDict

logger = logging.getLogger(__name__)


class PageBlock(TypedDict):
    page_start: int
    page_end: int
    text: str


# ── PDF extraction (pypdf) ───────────────────────────────────────────


def _extract_pdf(data: bytes) -> list[PageBlock]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[PageBlock] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append({"page_start": idx, "page_end": idx, "text": text})
    return pages


# ── Mistral OCR extraction ───────────────────────────────────────────


def _mistral_available() -> bool:
    """Check if Mistral OCR is configured."""
    try:
        from app.core.config.settings import settings
        return bool(settings.MISTRAL_API_KEY)
    except Exception:
        return False


async def _async_extract_pdf_mistral(data: bytes) -> list[PageBlock]:
    """Extract PDF via Mistral OCR, converting to PageBlock dicts."""
    from ai_engine.extraction.mistral_ocr import async_extract_pdf_with_mistral

    blocks = await async_extract_pdf_with_mistral(data)
    return [
        {"page_start": b.page_start, "page_end": b.page_end, "text": b.text}
        for b in blocks
    ]


# ── DOCX extraction (python-docx) ───────────────────────────────────


def _extract_docx(data: bytes) -> list[PageBlock]:
    import docx

    doc = docx.Document(io.BytesIO(data))
    full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not full_text.strip():
        return []
    # DOCX has no native page concept → treat as single page
    return [{"page_start": 1, "page_end": 1, "text": full_text}]


# ── Azure Document Intelligence fallback ─────────────────────────────


def _extract_with_document_intelligence(data: bytes) -> list[PageBlock]:
    """Fallback for scanned PDFs — uses Azure DI if available."""
    try:
        from azure.ai.documentintelligence import (
            DocumentIntelligenceClient,  # type: ignore[import-untyped]
        )
        from azure.ai.documentintelligence.models import (
            AnalyzeDocumentRequest,  # type: ignore[import-untyped]
        )
        from azure.identity import DefaultAzureCredential

        endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
        if not endpoint:
            logger.debug("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not set — DI fallback skipped")
            return []

        cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        client = DocumentIntelligenceClient(endpoint=endpoint, credential=cred)

        poller = client.begin_analyze_document(
            "prebuilt-read",
            analyze_request=AnalyzeDocumentRequest(bytes_source=data),
        )
        result = poller.result()

        pages: list[PageBlock] = []
        if result.pages:
            for page in result.pages:
                page_num = page.page_number or 1
                lines = []
                if page.lines:
                    lines = [line.content for line in page.lines if line.content]
                text = "\n".join(lines).strip()
                if text:
                    pages.append({"page_start": page_num, "page_end": page_num, "text": text})
        return pages

    except ImportError:
        logger.debug("azure-ai-documentintelligence not installed — DI fallback unavailable")
        return []
    except Exception:
        logger.warning("Document Intelligence extraction failed", exc_info=True)
        return []


# ── Public API ────────────────────────────────────────────────────────


async def async_extract_text_from_bytes(data: bytes, *, filename: str) -> list[PageBlock]:
    """Async text extraction — routes PDFs through Mistral OCR when available.

    Fallback chain for PDFs:
    1. Mistral OCR (if MISTRAL_API_KEY configured) → markdown with HTML tables
    2. pypdf (if Mistral unavailable or fails) → plain text
    3. Azure Document Intelligence (if pypdf yields nothing) → scanned PDF OCR
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        # Try Mistral OCR first
        if _mistral_available():
            try:
                pages = await _async_extract_pdf_mistral(data)
                if pages:
                    logger.info(
                        "Mistral OCR extracted %d pages from %s",
                        len(pages), filename,
                    )
                    return pages
                logger.warning("Mistral OCR returned empty — falling back to pypdf: %s", filename)
            except Exception:
                logger.warning(
                    "Mistral OCR failed — falling back to pypdf: %s",
                    filename, exc_info=True,
                )

        # Fallback to pypdf
        pages = _extract_pdf(data)
        if not pages:
            logger.info("PDF yielded no text — attempting Document Intelligence: %s", filename)
            pages = _extract_with_document_intelligence(data)
        return pages

    if ext in ("docx", "doc"):
        return _extract_docx(data)

    if ext in ("txt", "md", "csv"):
        text = data.decode("utf-8", errors="replace").strip()
        return [{"page_start": 1, "page_end": 1, "text": text}] if text else []

    logger.warning("Unsupported file extension '%s' for text extraction: %s", ext, filename)
    return []


# Supported file extensions for text extraction
_SUPPORTED_EXTENSIONS = {"pdf", "docx", "doc", "txt", "md", "csv"}


async def async_extract_text_from_blob(blob_container: str, blob_path: str) -> list[PageBlock]:
    """Async version of extract_text_from_blob.

    Downloads blob synchronously (Azure SDK limitation) then routes
    through async text extraction (Mistral OCR for PDFs).
    """
    filename = blob_path.rsplit("/", 1)[-1] if "/" in blob_path else blob_path
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in _SUPPORTED_EXTENSIONS:
        logger.info("Skipping unsupported file type '%s' (no download): %s", ext, blob_path)
        return []

    from app.services.azure.blob_client import get_blob_service_client

    svc = get_blob_service_client()
    container = svc.get_container_client(blob_container)
    blob = container.get_blob_client(blob_path)
    data = await asyncio.to_thread(lambda: blob.download_blob().readall())
    return await async_extract_text_from_bytes(data, filename=filename)
