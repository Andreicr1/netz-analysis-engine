"""Pipeline provider cache — OCR text and embedding vectors.

Stores results in a local SQLite database to avoid redundant paid API calls.
Cache key = SHA-256 hash of the input (PDF bytes for OCR, text for embeddings).

Usage::

    from ai_engine.cache.provider_cache import ocr_cache, embedding_cache

    # OCR
    text = ocr_cache.get(pdf_bytes)
    if text is None:
        text = await mistral_ocr(pdf_bytes)
        ocr_cache.put(pdf_bytes, text)

    # Embeddings
    vectors = embedding_cache.get_batch(texts)
    # vectors[i] is None for cache misses

Enable via ``ENABLE_PIPELINE_CACHE=true`` in ``.env``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_FILENAME = "pipeline_cache.db"

# Thread-local connections (SQLite is not thread-safe by default)
_local = threading.local()


def _get_cache_dir() -> Path:
    """Resolve cache directory from settings."""
    from app.core.config import settings
    return Path(settings.pipeline_cache_dir)


def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating tables if needed."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    cache_dir = _get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = cache_dir / _DB_FILENAME

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ocr_cache (
            hash TEXT PRIMARY KEY,
            filename TEXT,
            page_count INTEGER,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_cache (
            hash TEXT PRIMARY KEY,
            model TEXT,
            dim INTEGER,
            vector TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    _local.conn = conn
    return conn


def _sha256(data: bytes | str) -> str:
    """Compute SHA-256 hex digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ── OCR Cache ──────────────────────────────────────────────────────────


class OcrCache:
    """Cache for OCR text output keyed by PDF content hash."""

    def get(self, pdf_bytes: bytes, *, filename: str = "") -> str | None:
        """Return cached OCR text or None on miss."""
        if not _is_enabled():
            return None
        h = _sha256(pdf_bytes)
        conn = _get_conn()
        row = conn.execute(
            "SELECT text FROM ocr_cache WHERE hash = ?", (h,),
        ).fetchone()
        if row:
            logger.info("OCR_CACHE HIT hash=%s…%s filename=%s", h[:12], h[-4:], filename)
            return row[0]
        logger.debug("OCR_CACHE MISS hash=%s…%s filename=%s", h[:12], h[-4:], filename)
        return None

    def put(
        self,
        pdf_bytes: bytes,
        text: str,
        *,
        filename: str = "",
        page_count: int = 0,
    ) -> None:
        """Store OCR text in cache."""
        if not _is_enabled():
            return
        h = _sha256(pdf_bytes)
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO ocr_cache (hash, filename, page_count, text) VALUES (?, ?, ?, ?)",
            (h, filename, page_count, text),
        )
        conn.commit()
        logger.info("OCR_CACHE STORE hash=%s…%s filename=%s pages=%d chars=%d",
                     h[:12], h[-4:], filename, page_count, len(text))

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        if not _is_enabled():
            return {"enabled": False}
        conn = _get_conn()
        row = conn.execute("SELECT COUNT(*), SUM(LENGTH(text)) FROM ocr_cache").fetchone()
        return {
            "enabled": True,
            "entries": row[0] or 0,
            "total_chars": row[1] or 0,
        }


# ── Embedding Cache ────────────────────────────────────────────────────


class EmbeddingCache:
    """Cache for embedding vectors keyed by text content hash."""

    def get(self, text: str) -> list[float] | None:
        """Return cached vector or None on miss."""
        if not _is_enabled():
            return None
        h = _sha256(text)
        conn = _get_conn()
        row = conn.execute(
            "SELECT vector FROM embedding_cache WHERE hash = ?", (h,),
        ).fetchone()
        if row:
            return json.loads(row[0])
        return None

    def get_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Return cached vectors for a batch; None for misses."""
        if not _is_enabled():
            return [None] * len(texts)
        conn = _get_conn()
        results: list[list[float] | None] = []
        for text in texts:
            h = _sha256(text)
            row = conn.execute(
                "SELECT vector FROM embedding_cache WHERE hash = ?", (h,),
            ).fetchone()
            results.append(json.loads(row[0]) if row else None)
        hits = sum(1 for r in results if r is not None)
        if hits:
            logger.info("EMBEDDING_CACHE batch=%d hits=%d misses=%d",
                         len(texts), hits, len(texts) - hits)
        return results

    def put(self, text: str, vector: list[float], *, model: str = "", dim: int = 0) -> None:
        """Store a single embedding vector."""
        if not _is_enabled():
            return
        h = _sha256(text)
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO embedding_cache (hash, model, dim, vector) VALUES (?, ?, ?, ?)",
            (h, model, dim or len(vector), json.dumps(vector)),
        )
        conn.commit()

    def put_batch(
        self,
        texts: list[str],
        vectors: list[list[float]],
        *,
        model: str = "",
    ) -> None:
        """Store a batch of embedding vectors."""
        if not _is_enabled():
            return
        conn = _get_conn()
        for text, vector in zip(texts, vectors, strict=True):
            h = _sha256(text)
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache (hash, model, dim, vector) VALUES (?, ?, ?, ?)",
                (h, model, len(vector), json.dumps(vector)),
            )
        conn.commit()
        logger.info("EMBEDDING_CACHE STORE batch=%d model=%s", len(texts), model)

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        if not _is_enabled():
            return {"enabled": False}
        conn = _get_conn()
        row = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()
        return {"enabled": True, "entries": row[0] or 0}


# ── Module-level singletons ────────────────────────────────────────────

ocr_cache = OcrCache()
embedding_cache = EmbeddingCache()


def _is_enabled() -> bool:
    """Check if pipeline cache is enabled via settings."""
    from app.core.config import settings
    return settings.enable_pipeline_cache
