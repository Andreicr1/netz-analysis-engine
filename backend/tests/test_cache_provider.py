"""Tests for ai_engine.cache.provider_cache — OCR and embedding caching."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from ai_engine.cache.provider_cache import (
    EmbeddingCache,
    OcrCache,
    _sha256,
)


@pytest.fixture
def _enable_cache():
    """Enable cache and provide in-memory SQLite for tests."""
    conn = sqlite3.connect(":memory:")
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

    with (
        patch("ai_engine.cache.provider_cache._is_enabled", return_value=True),
        patch("ai_engine.cache.provider_cache._get_conn", return_value=conn),
    ):
        yield conn
    conn.close()


# ── _sha256 ──────────────────────────────────────────────────────


class TestSha256:
    def test_bytes_input(self):
        result = _sha256(b"hello")
        assert len(result) == 64
        assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_string_input(self):
        result = _sha256("hello")
        assert result == _sha256(b"hello")

    def test_different_inputs_different_hashes(self):
        assert _sha256(b"a") != _sha256(b"b")

    def test_deterministic(self):
        assert _sha256(b"test") == _sha256(b"test")


# ── OcrCache ──────────────────────────────────────────────────────


class TestOcrCache:
    def test_miss_returns_none(self, _enable_cache):
        cache = OcrCache()
        assert cache.get(b"nonexistent") is None

    def test_put_and_get(self, _enable_cache):
        cache = OcrCache()
        pdf = b"fake pdf content"
        cache.put(pdf, "Extracted OCR text", filename="test.pdf", page_count=5)
        result = cache.get(pdf, filename="test.pdf")
        assert result == "Extracted OCR text"

    def test_different_content_different_keys(self, _enable_cache):
        cache = OcrCache()
        cache.put(b"pdf1", "text1")
        cache.put(b"pdf2", "text2")
        assert cache.get(b"pdf1") == "text1"
        assert cache.get(b"pdf2") == "text2"

    def test_overwrite_existing(self, _enable_cache):
        cache = OcrCache()
        pdf = b"same pdf"
        cache.put(pdf, "old text")
        cache.put(pdf, "new text")
        assert cache.get(pdf) == "new text"

    def test_stats(self, _enable_cache):
        cache = OcrCache()
        cache.put(b"pdf1", "text one")
        cache.put(b"pdf2", "text two")
        stats = cache.stats()
        assert stats["enabled"] is True
        assert stats["entries"] == 2
        assert stats["total_chars"] > 0

    def test_disabled_returns_none(self):
        with patch("ai_engine.cache.provider_cache._is_enabled", return_value=False):
            cache = OcrCache()
            assert cache.get(b"test") is None

    def test_disabled_put_noop(self):
        with patch("ai_engine.cache.provider_cache._is_enabled", return_value=False):
            cache = OcrCache()
            cache.put(b"test", "text")  # Should not raise

    def test_disabled_stats(self):
        with patch("ai_engine.cache.provider_cache._is_enabled", return_value=False):
            cache = OcrCache()
            stats = cache.stats()
            assert stats["enabled"] is False


# ── EmbeddingCache ───────────────────────────────────────────────


class TestEmbeddingCache:
    def test_miss_returns_none(self, _enable_cache):
        cache = EmbeddingCache()
        assert cache.get("nonexistent text") is None

    def test_put_and_get(self, _enable_cache):
        cache = EmbeddingCache()
        vector = [0.1, 0.2, 0.3]
        cache.put("hello world", vector, model="test-model")
        result = cache.get("hello world")
        assert result == vector

    def test_get_batch_mixed(self, _enable_cache):
        cache = EmbeddingCache()
        cache.put("cached text", [1.0, 2.0])
        results = cache.get_batch(["cached text", "not cached"])
        assert results[0] == [1.0, 2.0]
        assert results[1] is None

    def test_put_batch(self, _enable_cache):
        cache = EmbeddingCache()
        texts = ["text1", "text2", "text3"]
        vectors = [[0.1], [0.2], [0.3]]
        cache.put_batch(texts, vectors, model="test")
        assert cache.get("text1") == [0.1]
        assert cache.get("text2") == [0.2]
        assert cache.get("text3") == [0.3]

    def test_stats(self, _enable_cache):
        cache = EmbeddingCache()
        cache.put("t1", [0.1, 0.2])
        stats = cache.stats()
        assert stats["enabled"] is True
        assert stats["entries"] == 1

    def test_disabled_get_batch_all_none(self):
        with patch("ai_engine.cache.provider_cache._is_enabled", return_value=False):
            cache = EmbeddingCache()
            results = cache.get_batch(["a", "b", "c"])
            assert results == [None, None, None]

    def test_disabled_stats(self):
        with patch("ai_engine.cache.provider_cache._is_enabled", return_value=False):
            cache = EmbeddingCache()
            assert cache.stats()["enabled"] is False
