"""Local VLM OCR — PDF to markdown via LM Studio SDK.

Uses a local LM Studio server with a VLM (qwen2.5-vl-7b) to extract
text from PDF pages rendered as JPEG images.

Drop-in replacement for mistral_ocr.async_extract_pdf_with_mistral().
Returns the same list[PageBlock] format.
"""
from __future__ import annotations

import asyncio
import io
import logging

logger = logging.getLogger(__name__)

from ai_engine.extraction.mistral_ocr import PageBlock

# ── Defaults ────────────────────────────────────────────────────────
DEFAULT_HOST = "127.0.0.1:1234"
_DPI = 100
_JPEG_QUALITY = 55
_MAX_IMAGE_PIXELS = 1200 * 1600


def _render_page_jpeg(pdf_bytes: bytes, page_idx: int) -> bytes:
    """Render a single PDF page as JPEG bytes."""
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_idx]
        pix = page.get_pixmap(matrix=fitz.Matrix(_DPI / 72, _DPI / 72))

    from PIL import Image as PILImage

    img = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
    total_px = img.width * img.height
    if total_px > _MAX_IMAGE_PIXELS:
        scale = (_MAX_IMAGE_PIXELS / total_px) ** 0.5
        img = img.resize(
            (int(img.width * scale), int(img.height * scale)), PILImage.LANCZOS,
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY)
    return buf.getvalue()


def _get_page_count(pdf_bytes: bytes) -> int:
    import fitz

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return len(doc)


_OCR_PROMPT = (
    "You are a document OCR engine. Extract ALL text from this page image "
    "as markdown. Preserve headings, bullet points, numbered lists, and "
    "tables (use markdown table syntax). Output ONLY the extracted text, "
    "no commentary or explanations."
)


def _ocr_page_sync(
    pdf_bytes: bytes,
    page_idx: int,
    host: str,
) -> PageBlock:
    """OCR a single page (sync, runs in thread)."""
    import lmstudio

    page_num = page_idx + 1
    try:
        jpeg_bytes = _render_page_jpeg(pdf_bytes, page_idx)
        logger.info(
            "VLM OCR page %d: JPEG %d bytes", page_num, len(jpeg_bytes),
        )

        client = lmstudio.Client(host)
        models = client.list_loaded_models()
        if not models:
            logger.error("No VLM model loaded in LM Studio")
            client.close()
            return PageBlock(page_start=page_num, page_end=page_num, text="")

        model = models[0]
        img_handle = client.prepare_image(jpeg_bytes, name=f"page{page_num}.jpg")

        chat = lmstudio.Chat()
        chat.add_user_message([img_handle, _OCR_PROMPT])

        result = model.respond(
            chat, config={"maxTokens": 4096, "temperature": 0},
        )
        text = str(result)
        client.close()

        logger.info("VLM OCR page %d: %d chars extracted", page_num, len(text))
        return PageBlock(page_start=page_num, page_end=page_num, text=text)
    except Exception as e:
        logger.warning("VLM OCR failed for page %d: %s", page_num, e)
        return PageBlock(page_start=page_num, page_end=page_num, text="")


async def async_extract_pdf_with_local_vlm(
    pdf_bytes: bytes,
    *,
    host: str = DEFAULT_HOST,
) -> list[PageBlock]:
    """Extract text from a PDF via local VLM (async).

    Drop-in replacement for async_extract_pdf_with_mistral().
    Processes pages sequentially (local GPU can only handle one at a time).
    """
    total = await asyncio.to_thread(_get_page_count, pdf_bytes)
    if total == 0:
        return []

    logger.info("Local VLM OCR: %d pages to process", total)

    blocks: list[PageBlock] = []
    for i in range(total):
        block = await asyncio.to_thread(_ocr_page_sync, pdf_bytes, i, host)
        blocks.append(block)

    result = [b for b in blocks if b.text.strip()]
    logger.info(
        "Local VLM OCR complete: %d/%d pages with text", len(result), total,
    )
    return result
