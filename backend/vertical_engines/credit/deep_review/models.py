"""Deep Review V4 — shared constants and type definitions.

This module is the LEAF node of the deep_review package DAG.
It MUST NOT import any sibling modules.

Import hierarchy:
    models.py → helpers → (corpus | prompts | policy | decision | confidence)
              → persist → portfolio → service.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── LLM concurrency limit ─────────────────────────────────────────────
# Resolved lazily at call-time via Settings so that env-var changes
# between process startup and first use are honoured (e.g. test fixtures).
# The asyncio.Semaphore is created lazily inside async functions.


def get_llm_concurrency() -> int:
    """Return the configured LLM concurrency limit, resolved through Settings.

    Always read through the Settings singleton rather than a module-level
    capture so that test fixtures that override NETZ_LLM_CONCURRENCY are
    respected without requiring a process restart.
    """
    from app.core.config.settings import settings
    return max(1, settings.netz_llm_concurrency)


# _LLM_CONCURRENCY is kept for import compatibility with any code that
# imports it directly.  It captures the Settings value at import time
# (no bare os.getenv at module level).  Callers that need a fresh value
# at call-time — e.g. when creating asyncio.Semaphore — MUST call
# get_llm_concurrency() instead, as service.py now does.
_LLM_CONCURRENCY: int = get_llm_concurrency()


# ── StageOutcome — named results for asyncio.gather ───────────────────


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """Result container for async gather stages.

    Named fields prevent silent breakage on reorder.
    Used only by the async pipeline's Phase 3 gather (EDGAR, Policy, Sponsor, KYC, Quant).
    """

    edgar: Any | None = None
    policy: Any | None = None
    sponsor: Any | None = None
    kyc: Any | None = None
    quant: Any | None = None
    errors: dict[str, BaseException] = field(default_factory=dict)

    @classmethod
    def from_gather(
        cls,
        stage_names: list[str],
        results: list[Any],
    ) -> StageOutcome:
        """Build from asyncio.gather(return_exceptions=True) output.

        ``strict=True`` on ``zip()`` catches gather configuration bugs
        (mismatched stage_names and results lengths).
        """
        fields: dict[str, Any] = {}
        errors: dict[str, BaseException] = {}
        for name, result in zip(stage_names, results, strict=True):
            if isinstance(result, BaseException):
                errors[name] = result
            else:
                fields[name] = result
        return cls(**fields, errors=errors)


__all__: list[str] = [
    "_LLM_CONCURRENCY",
    "get_llm_concurrency",
    "StageOutcome",
]
