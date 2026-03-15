"""Deep Review V4 — shared constants and type definitions.

This module is the LEAF node of the deep_review package DAG.
It MUST NOT import any sibling modules.

Import hierarchy:
    models.py → (helpers | corpus | prompts | policy | decision | confidence)
              → persist → portfolio → service.py
"""
from __future__ import annotations

import os
from typing import Any

# ── LLM concurrency limit ─────────────────────────────────────────────
# Plain integer — NOT an asyncio.Semaphore.  Safe at module scope.
# The asyncio.Semaphore is created lazily inside async functions.
_LLM_CONCURRENCY: int = max(1, int(os.getenv("NETZ_LLM_CONCURRENCY", "5")))

# ── Stage criticality classification ──────────────────────────────────
# Documents which pipeline stages are fatal vs degraded (non-fatal).
# Used for logging enrichment and alerting — NOT for orchestrator flow
# control (which is preserved as-is from the monolithic deep_review.py).
STAGE_CRITICALITY: dict[str, str] = {
    "deal_lookup": "fatal",
    "rag_context": "fatal",
    "structured_analysis": "fatal",
    "macro_context": "degraded",
    "edgar": "degraded",
    "kyc": "degraded",
    "quant": "fatal",
    "concentration": "fatal",
    "policy_hard": "fatal",
    "policy_llm": "fatal",
    "sponsor": "fatal",
    "evidence_pack": "fatal",
    "critic": "degraded",
    "memo_book": "fatal",
    "persist": "fatal",
}

__all__: list[str] = [
    "_LLM_CONCURRENCY",
    "STAGE_CRITICALITY",
]
