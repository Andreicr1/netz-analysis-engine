"""
Stage 7 — Chunk Embedding
=========================
Reads cu_chunks.json from Stage 6 (prepare_pdfs_full.py)
Embeds each chunk's content via the centralised provider layer
Writes cu_chunks_embedded.json with vector field added

Usage:
    python embed_chunks.py --folder "C:/Deals/Garrington"
    python embed_chunks.py --folder "C:/Deals/Garrington" --dry-run
    python embed_chunks.py --folder "C:/Deals" --recursive
"""

import json
import logging
import time
from pathlib import Path

from ai_engine.openai_client import create_embedding

logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

BATCH_SIZE = 500  # max items per embedding request

# text-embedding-3-large has a hard limit of 8 192 tokens.
# ~4 chars/token → 30 000 chars ≈ 7 500 tokens (safe margin).
EMBED_MAX_CHARS = 30_000

# Text sent to embedding model
# Prepend breadcrumb to content so the vector captures section context
# "Fee Structure > Management Fee\n\n[chunk content]"
def build_embed_text(chunk: dict) -> str:
    breadcrumb = chunk.get("breadcrumb", "")
    content    = chunk.get("content", "")
    if breadcrumb and not content.startswith(f"[{breadcrumb}]"):
        text = f"{breadcrumb}\n\n{content}"
    else:
        text = content
    if len(text) > EMBED_MAX_CHARS:
        text = text[:EMBED_MAX_CHARS]
    return text


# ============================================================
# EMBEDDING — via centralised provider layer
# ============================================================

def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via the centralised provider layer.

    Provider selection, retry logic, and fallback are handled by
    ``create_embedding()`` in ``ai_engine.openai_client``.
    Returns list of vectors in same order as input texts.
    """
    result = create_embedding(inputs=texts)
    return result.vectors


# ============================================================
# EMBED FOLDER
# ============================================================

def embed_folder(
    folder_path: str,
    dry_run: bool = False,
) -> int:
    folder     = Path(folder_path)
    input_path = folder / "cu_chunks.json"

    if not input_path.exists():
        logger.info("cu_chunks.json not found in %s", folder.name)
        return 0

    chunks = json.loads(input_path.read_text(encoding="utf-8"))
    if not chunks:
        logger.info("cu_chunks.json is empty in %s", folder.name)
        return 0

    logger.info("Embed: %s — %s chunks", folder.name, f"{len(chunks):,}")

    if dry_run:
        logger.info("DRY RUN — skipping embedding")
        return len(chunks)

    # Build texts
    texts = [build_embed_text(c) for c in chunks]

    # Embed in batches
    all_vectors: list[list[float]] = []
    t0 = time.time()

    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[batch_start: batch_start + BATCH_SIZE]
        batch_end   = min(batch_start + BATCH_SIZE, len(texts))

        t_b = time.time()
        vectors = embed_batch(batch_texts)
        all_vectors.extend(vectors)
        logger.info("Embedding %d–%d / %d… %.1fs", batch_start + 1, batch_end, len(texts), time.time() - t_b)

    elapsed = round(time.time() - t0, 1)

    # Attach vectors to chunks
    for chunk, vector in zip(chunks, all_vectors, strict=False):
        chunk["embedding"] = vector

    # Write output
    output_path = folder / "cu_chunks_embedded.json"
    output_path.write_text(
        json.dumps(chunks, ensure_ascii=False),  # no indent — file can be large
        encoding="utf-8"
    )

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Done: %s chunks | %.1fs | %.1f MB → %s", f"{len(chunks):,}", elapsed, size_mb, output_path.name)
    return len(chunks)


# (CLI entry point removed — use embed_folder() directly)
