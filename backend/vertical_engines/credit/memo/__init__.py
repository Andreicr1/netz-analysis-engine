"""Memo package — chapter-wise institutional memorandum generation.

Public API:
    generate_memo_book()           — sync full memo generation
    async_generate_memo_book()     — async parallel memo generation
    generate_chapter()             — single chapter generation
    select_chapter_chunks()        — evidence chunk selection
    build_evidence_summary()       — deterministic evidence summary
    filter_evidence_pack()         — chapter-relevant pack subset
    regenerate_chapter_with_critic() — critic-driven chapter revision
    CHAPTER_REGISTRY               — authoritative 14-chapter table
    build_evidence_pack()          — frozen evidence surface builder
    validate_evidence_pack()       — structural validation
    persist_evidence_pack()        — DB persistence
    run_tone_normalizer()          — two-pass post-processing
    ToneReviewResult               — tone normalizer output schema

Error contract: never-raises (orchestration engine). Functions return result
dicts with status/warnings on failure. exc_info=True in structlog.

Uses PEP 562 lazy imports — openai (in batch.py) is heavy.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Eager imports — lightweight, always needed
from vertical_engines.credit.memo.models import (
    CHAPTER_REGISTRY,
    ToneReviewResult,
)

if TYPE_CHECKING:
    from vertical_engines.credit.memo.chapters import (
        build_evidence_summary as build_evidence_summary,
    )
    from vertical_engines.credit.memo.chapters import (
        filter_evidence_pack as filter_evidence_pack,
    )
    from vertical_engines.credit.memo.chapters import (
        generate_chapter as generate_chapter,
    )
    from vertical_engines.credit.memo.chapters import (
        regenerate_chapter_with_critic as regenerate_chapter_with_critic,
    )
    from vertical_engines.credit.memo.chapters import (
        select_chapter_chunks as select_chapter_chunks,
    )
    from vertical_engines.credit.memo.evidence import (
        build_evidence_pack as build_evidence_pack,
    )
    from vertical_engines.credit.memo.evidence import (
        persist_evidence_pack as persist_evidence_pack,
    )
    from vertical_engines.credit.memo.evidence import (
        validate_evidence_pack as validate_evidence_pack,
    )
    from vertical_engines.credit.memo.service import (
        async_generate_memo_book as async_generate_memo_book,
    )
    from vertical_engines.credit.memo.service import (
        generate_memo_book as generate_memo_book,
    )
    from vertical_engines.credit.memo.tone import (
        run_tone_normalizer as run_tone_normalizer,
    )

__all__ = [
    # models (eager)
    "CHAPTER_REGISTRY",
    "ToneReviewResult",
    # service
    "generate_memo_book",
    "async_generate_memo_book",
    # chapters
    "generate_chapter",
    "select_chapter_chunks",
    "build_evidence_summary",
    "filter_evidence_pack",
    "regenerate_chapter_with_critic",
    # evidence
    "build_evidence_pack",
    "validate_evidence_pack",
    "persist_evidence_pack",
    # tone
    "run_tone_normalizer",
]


def __getattr__(name: str) -> Any:
    if name in ("generate_memo_book", "async_generate_memo_book"):
        from vertical_engines.credit.memo.service import (
            async_generate_memo_book,
            generate_memo_book,
        )
        _map = {
            "generate_memo_book": generate_memo_book,
            "async_generate_memo_book": async_generate_memo_book,
        }
        return _map[name]

    if name in (
        "generate_chapter", "select_chapter_chunks", "build_evidence_summary",
        "filter_evidence_pack", "regenerate_chapter_with_critic",
    ):
        from vertical_engines.credit.memo import chapters as _chapters
        return getattr(_chapters, name)

    if name in (
        "build_evidence_pack", "validate_evidence_pack",
        "persist_evidence_pack",
    ):
        from vertical_engines.credit.memo import evidence as _evidence
        return getattr(_evidence, name)

    if name == "run_tone_normalizer":
        from vertical_engines.credit.memo.tone import run_tone_normalizer
        return run_tone_normalizer

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
