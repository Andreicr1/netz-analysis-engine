"""Deep Review V4 — shared constants and type definitions.

This module is the LEAF node of the deep_review package DAG.
It MUST NOT import any sibling modules.

Import hierarchy:
    models.py → helpers → (corpus | prompts | policy | decision | confidence)
              → persist → portfolio → service.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# ── LLM concurrency limit ─────────────────────────────────────────────
# Plain integer — NOT an asyncio.Semaphore.  Safe at module scope.
# The asyncio.Semaphore is created lazily inside async functions.
_LLM_CONCURRENCY: int = max(1, int(os.getenv("NETZ_LLM_CONCURRENCY", "5")))


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
    "StageOutcome",
]
