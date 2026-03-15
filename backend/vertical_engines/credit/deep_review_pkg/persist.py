"""Deep Review V4 — persistence helpers.

Self-contained helpers used by the Stage 13 persist logic in service.py.
The main persist blocks (Stage 13b/c/d) remain in service.py because they
reference 30+ local variables from the orchestrator context — extracting
them as a function would require a worse interface than inline code.

The profile/brief/risk flag persist logic is duplicated between the sync
and async pipelines.  Dedup is deferred to the sync/async dedup effort
(see Phase 3 in the Wave 2 plan).
"""
from __future__ import annotations

import structlog
from typing import Any

logger = structlog.get_logger()


def _index_chapter_citations(
    chapters: list[dict[str, Any]],
    citations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group flat memo citations by chapter tag for eval consumers."""
    by_number: dict[int, str] = {}
    for ch in chapters:
        chapter_number = ch.get("chapter_number")
        chapter_tag = ch.get("chapter_tag")
        if chapter_number is None or not chapter_tag:
            continue
        try:
            by_number[int(chapter_number)] = str(chapter_tag)
        except (TypeError, ValueError):
            continue
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in citations or []:
        citation = dict(raw or {})
        chapter_tag = str(citation.get("chapter_tag") or "").strip()
        if not chapter_tag:
            chapter_number = citation.get("chapter_number")
            if isinstance(chapter_number, int):
                chapter_tag = by_number.get(chapter_number, "")
        if not chapter_tag:
            continue
        citation["chapter_tag"] = chapter_tag
        grouped.setdefault(chapter_tag, []).append(citation)
    return grouped


def _build_tone_artifacts(
    *,
    pre_tone_chapters: dict[str, str],
    post_tone_chapters: dict[str, str],
    tone_review_log: list[Any],
    tone_pass1_changes: dict[str, Any],
    tone_pass2_changes: list[Any],
    signal_original: str,
    signal_final: str,
) -> dict[str, Any]:
    """Persist only changed chapter snapshots to keep the audit payload compact."""
    changed_chapters = sorted(
        chapter_tag
        for chapter_tag in set(pre_tone_chapters) | set(post_tone_chapters)
        if (pre_tone_chapters.get(chapter_tag) or "") != (post_tone_chapters.get(chapter_tag) or "")
    )
    return {
        "signal_original": signal_original,
        "signal_final": signal_final,
        "changed_chapters": changed_chapters,
        "pre_tone_snapshots": {
            chapter_tag: pre_tone_chapters.get(chapter_tag, "")
            for chapter_tag in changed_chapters
        },
        "post_tone_snapshots": {
            chapter_tag: post_tone_chapters.get(chapter_tag, "")
            for chapter_tag in changed_chapters
        },
        "pass1_changes": tone_pass1_changes,
        "pass2_changes": tone_pass2_changes,
        "review_log": tone_review_log,
    }


__all__ = [
    "_index_chapter_citations",
    "_build_tone_artifacts",
]
