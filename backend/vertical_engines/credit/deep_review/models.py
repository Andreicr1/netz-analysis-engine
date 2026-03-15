"""Deep Review V4 — shared constants and type definitions.

This module is the LEAF node of the deep_review package DAG.
It MUST NOT import any sibling modules.

Import hierarchy:
    models.py → helpers → (corpus | prompts | policy | decision | confidence)
              → persist → portfolio → service.py
"""
from __future__ import annotations

import os

# ── LLM concurrency limit ─────────────────────────────────────────────
# Plain integer — NOT an asyncio.Semaphore.  Safe at module scope.
# The asyncio.Semaphore is created lazily inside async functions.
_LLM_CONCURRENCY: int = max(1, int(os.getenv("NETZ_LLM_CONCURRENCY", "5")))

__all__: list[str] = [
    "_LLM_CONCURRENCY",
]
