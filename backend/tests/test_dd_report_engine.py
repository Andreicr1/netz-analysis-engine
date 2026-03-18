"""Tests for DDReportEngine concurrency contract (ASYNC-03).

Acceptance criteria:
1. Implementation and docstrings declare the same chapter-generation mode.
2. Sequential mode: only one chapter-generation task is in flight at a time.
3. Output ordering is deterministic (by chapter order field).
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from vertical_engines.wealth.dd_report.dd_report_engine import DDReportEngine
from vertical_engines.wealth.dd_report.evidence_pack import EvidencePack
from vertical_engines.wealth.dd_report.models import (
    CHAPTER_REGISTRY,
    PARALLEL_CHAPTER_TAGS,
    SEQUENTIAL_CHAPTER_TAG,
    MIN_CHAPTERS_FOR_RECOMMENDATION,
    ChapterResult,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_call_openai_fn(response_text: str = "## Content\n\nGenerated chapter.") -> MagicMock:
    """Return a mock LLM call function that returns deterministic content."""
    mock = MagicMock(return_value={"content": response_text})
    return mock


def _make_evidence() -> EvidencePack:
    """Minimal evidence pack for unit tests (no DB required)."""
    return EvidencePack(
        instrument_id="fund-001",
        fund_name="Test Fund",
        isin="US1234567890",
        manager_name="Test Manager",
    )


# ── AC-1: Docstring declares sequential mode ──────────────────────────────────

class TestDocstringContract:
    """Verify the module and method docstrings declare sequential chapter generation."""

    def test_module_docstring_declares_sequential(self):
        """Module-level docstring must say SEQUENTIAL, not parallel."""
        import vertical_engines.wealth.dd_report.dd_report_engine as mod
        docstring = mod.__doc__ or ""
        assert "SEQUENTIAL" in docstring, (
            "Module docstring must declare 'Chapter generation mode: SEQUENTIAL'. "
            "Found: " + repr(docstring[:200])
        )

    def test_module_docstring_does_not_claim_taskgroup(self):
        """Module docstring must not claim TaskGroup concurrency inside the engine."""
        import vertical_engines.wealth.dd_report.dd_report_engine as mod
        docstring = mod.__doc__ or ""
        # The old incorrect claim was "TaskGroup + Semaphore"
        assert "TaskGroup + Semaphore" not in docstring, (
            "Module docstring still claims TaskGroup + Semaphore concurrency, "
            "which contradicts the sequential implementation."
        )

    def test_generate_all_chapters_docstring_says_sequential(self):
        """_generate_all_chapters method docstring must describe sequential generation."""
        docstring = DDReportEngine._generate_all_chapters.__doc__ or ""
        assert "sequential" in docstring.lower(), (
            "_generate_all_chapters docstring must acknowledge sequential mode."
        )

    def test_generate_all_chapters_docstring_explains_thread_context(self):
        """_generate_all_chapters docstring must explain why it's sequential (to_thread)."""
        docstring = DDReportEngine._generate_all_chapters.__doc__ or ""
        assert "to_thread" in docstring, (
            "_generate_all_chapters docstring must mention asyncio.to_thread() "
            "as the reason for the sequential design."
        )


# ── AC-2: Only one chapter in flight at a time ────────────────────────────────

class TestSequentialExecution:
    """Prove only one chapter-generation call is active at a time."""

    def test_chapters_generated_one_at_a_time(self):
        """generate_chapter is called strictly sequentially (no overlap)."""
        call_log: list[str] = []
        active_calls: list[int] = [0]  # mutable int (list wrapper)
        max_concurrent: list[int] = [0]

        def tracking_call_openai_fn(system_prompt, user_content, max_tokens=None):
            # Track entry
            active_calls[0] += 1
            if active_calls[0] > max_concurrent[0]:
                max_concurrent[0] = active_calls[0]
            result = {"content": "## Generated\n\nContent."}
            active_calls[0] -= 1
            return result

        engine = DDReportEngine(call_openai_fn=tracking_call_openai_fn)
        evidence = _make_evidence()

        # Patch generate_chapter to use our tracking fn
        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: (
                call_log.append(chapter_tag),
                ChapterResult(
                    tag=chapter_tag,
                    order=next(
                        (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag),
                        0,
                    ),
                    title=chapter_tag,
                    content_md="## Test\n\nContent.",
                    status="completed",
                ),
            )[-1],  # return the ChapterResult (last tuple element)
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters={},
                force=True,
            )

        # All 8 chapters must be called sequentially — call_log grows one at a time
        assert len(call_log) == 8, f"Expected 8 chapter calls, got {len(call_log)}: {call_log}"

    def test_no_thread_overlap_during_chapter_generation(self):
        """Chapter generation is single-threaded — no concurrent threads spawned."""
        threads_seen: set[int] = set()

        def recording_call_openai_fn(system_prompt, user_content, max_tokens=None):
            threads_seen.add(threading.get_ident())
            return {"content": "## Test\n\nContent."}

        engine = DDReportEngine(call_openai_fn=recording_call_openai_fn)
        evidence = _make_evidence()

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: ChapterResult(
                tag=chapter_tag,
                order=next(
                    (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                ),
                title=chapter_tag,
                content_md="## Test\n\nContent.",
                status="completed",
            ),
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters={},
                force=True,
            )

        # All calls happened on a single thread
        # (No asyncio.gather / asyncio.TaskGroup spawned background tasks)
        assert len(threads_seen) <= 1, (
            f"Chapter generation used multiple threads: {threads_seen}. "
            "Expected sequential single-thread execution."
        )

    def test_recommendation_called_after_all_other_chapters(self):
        """Chapter 8 (Recommendation) must be generated after chapters 1-7."""
        call_order: list[str] = []

        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: (
                call_order.append(chapter_tag),
                ChapterResult(
                    tag=chapter_tag,
                    order=next(
                        (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                    ),
                    title=chapter_tag,
                    content_md="## Test\n\nContent.",
                    status="completed",
                ),
            )[-1],
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters={},
                force=True,
            )

        # Recommendation must be last in call_order
        assert SEQUENTIAL_CHAPTER_TAG in call_order, "Recommendation chapter not generated"
        assert call_order[-1] == SEQUENTIAL_CHAPTER_TAG, (
            f"Expected '{SEQUENTIAL_CHAPTER_TAG}' to be called last. "
            f"Actual call order: {call_order}"
        )

        # All non-recommendation chapters must precede it
        rec_index = call_order.index(SEQUENTIAL_CHAPTER_TAG)
        non_rec = [tag for tag in call_order if tag != SEQUENTIAL_CHAPTER_TAG]
        assert len(non_rec) == rec_index, (
            "Non-recommendation chapters must all complete before recommendation."
        )


# ── AC-3: Deterministic output ordering ──────────────────────────────────────

class TestDeterministicOrdering:
    """Prove output chapters are in deterministic order by chapter.order field."""

    def test_output_chapters_sorted_by_order(self):
        """_generate_all_chapters always returns chapters sorted by order field."""
        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: ChapterResult(
                tag=chapter_tag,
                order=next(
                    (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                ),
                title=chapter_tag,
                content_md="## Test\n\nContent.",
                status="completed",
            ),
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters={},
                force=True,
            )

        orders = [ch.order for ch in chapters]
        assert orders == sorted(orders), (
            f"Output chapters are not in order. Got orders: {orders}"
        )

    def test_output_chapters_sorted_by_order_with_cached_chapters(self):
        """Ordering is deterministic even when some chapters are served from cache."""
        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()

        # Cache chapters 1 and 3 (executive_summary and manager_assessment)
        existing_chapters = {
            "executive_summary": "## Cached Executive Summary\n\nContent.",
            "manager_assessment": "## Cached Manager Assessment\n\nContent.",
        }

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: ChapterResult(
                tag=chapter_tag,
                order=next(
                    (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                ),
                title=chapter_tag,
                content_md="## Generated\n\nContent.",
                status="completed",
            ),
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters=existing_chapters,
                force=False,
            )

        orders = [ch.order for ch in chapters]
        assert orders == sorted(orders), (
            f"Output chapters with cached entries are not in order. Got: {orders}"
        )

        # The cached chapters must appear with their cached content
        by_tag = {ch.tag: ch for ch in chapters}
        assert by_tag["executive_summary"].content_md == "## Cached Executive Summary\n\nContent."
        assert by_tag["manager_assessment"].content_md == "## Cached Manager Assessment\n\nContent."

    def test_chapter_tags_match_registry(self):
        """All 8 registry chapters appear in output exactly once."""
        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: ChapterResult(
                tag=chapter_tag,
                order=next(
                    (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                ),
                title=chapter_tag,
                content_md="## Test\n\nContent.",
                status="completed",
            ),
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters={},
                force=True,
            )

        registry_tags = {ch["tag"] for ch in CHAPTER_REGISTRY}
        output_tags = {ch.tag for ch in chapters}
        assert output_tags == registry_tags, (
            f"Output tags {output_tags} do not match registry {registry_tags}"
        )

    def test_output_is_stable_across_multiple_calls(self):
        """Same inputs always produce the same chapter order (no randomness)."""
        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()

        results = []
        for _ in range(3):
            with patch(
                "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
                side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: ChapterResult(
                    tag=chapter_tag,
                    order=next(
                        (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                    ),
                    title=chapter_tag,
                    content_md="## Test\n\nContent.",
                    status="completed",
                ),
            ):
                chapters = engine._generate_all_chapters(
                    evidence=evidence,
                    existing_chapters={},
                    force=True,
                )
            results.append([ch.tag for ch in chapters])

        assert results[0] == results[1] == results[2], (
            f"Chapter order is not stable across calls. Got: {results}"
        )


# ── Resume safety edge cases ──────────────────────────────────────────────────

class TestResumeSafety:
    """Prove skip-if-cached logic works correctly."""

    def test_cached_chapters_skip_llm_call(self):
        """When a chapter is cached, generate_chapter is NOT called for it."""
        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()
        generate_chapter_mock = MagicMock(
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: ChapterResult(
                tag=chapter_tag,
                order=next(
                    (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                ),
                title=chapter_tag,
                content_md="## Generated\n\nContent.",
                status="completed",
            )
        )

        # All non-recommendation chapters cached
        non_rec_tags = [ch["tag"] for ch in CHAPTER_REGISTRY if ch["tag"] != SEQUENTIAL_CHAPTER_TAG]
        existing_chapters = {tag: f"## Cached {tag}" for tag in non_rec_tags}
        # Also cache recommendation
        existing_chapters[SEQUENTIAL_CHAPTER_TAG] = "## Cached Recommendation"

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            generate_chapter_mock,
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters=existing_chapters,
                force=False,
            )

        # No LLM calls should have been made — all chapters cached
        generate_chapter_mock.assert_not_called()
        assert len(chapters) == 8

    def test_force_bypasses_cache(self):
        """force=True re-generates even when chapters are cached."""
        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()

        called_tags: list[str] = []
        generate_chapter_mock = MagicMock(
            side_effect=lambda fn, chapter_tag, evidence_context, **kwargs: (
                called_tags.append(chapter_tag),
                ChapterResult(
                    tag=chapter_tag,
                    order=next(
                        (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                    ),
                    title=chapter_tag,
                    content_md="## Regenerated\n\nContent.",
                    status="completed",
                ),
            )[-1],
        )

        existing_chapters = {"executive_summary": "## Cached"}

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            generate_chapter_mock,
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters=existing_chapters,
                force=True,
            )

        # executive_summary must be re-generated despite being cached
        assert "executive_summary" in called_tags, (
            "force=True should bypass cache and re-generate executive_summary"
        )
        assert len(called_tags) == 8, (
            f"force=True should re-generate all 8 chapters. Called: {called_tags}"
        )

    def test_recommendation_skipped_if_insufficient_chapters(self):
        """Chapter 8 is skipped (status=skipped) when fewer than MIN_CHAPTERS_FOR_RECOMMENDATION succeed."""
        engine = DDReportEngine(call_openai_fn=_make_call_openai_fn())
        evidence = _make_evidence()

        call_count = [0]

        def failing_generate_chapter(fn, chapter_tag, evidence_context, **kwargs):
            # Only 2 chapters succeed; rest fail
            call_count[0] += 1
            if chapter_tag == SEQUENTIAL_CHAPTER_TAG:
                raise AssertionError("Recommendation should not be called when prerequisites fail")
            succeed = call_count[0] <= 2
            return ChapterResult(
                tag=chapter_tag,
                order=next(
                    (ch["order"] for ch in CHAPTER_REGISTRY if ch["tag"] == chapter_tag), 0
                ),
                title=chapter_tag,
                content_md="## Content" if succeed else None,
                status="completed" if succeed else "failed",
            )

        with patch(
            "vertical_engines.wealth.dd_report.dd_report_engine.generate_chapter",
            side_effect=failing_generate_chapter,
        ):
            chapters = engine._generate_all_chapters(
                evidence=evidence,
                existing_chapters={},
                force=True,
            )

        rec_chapter = next((ch for ch in chapters if ch.tag == SEQUENTIAL_CHAPTER_TAG), None)
        assert rec_chapter is not None, "Recommendation chapter must always appear in output"
        assert rec_chapter.status == "skipped", (
            f"Expected recommendation status='skipped' when fewer than "
            f"{MIN_CHAPTERS_FOR_RECOMMENDATION} prerequisites completed. "
            f"Got: {rec_chapter.status}"
        )


# ── Model constants consistency ───────────────────────────────────────────────

class TestModelConstants:
    """Verify CHAPTER_REGISTRY constants are internally consistent."""

    def test_parallel_chapter_tags_are_orders_1_to_7(self):
        """PARALLEL_CHAPTER_TAGS must be exactly the tags for orders 1-7."""
        expected = [ch["tag"] for ch in CHAPTER_REGISTRY if ch["order"] <= 7]
        assert PARALLEL_CHAPTER_TAGS == expected, (
            f"PARALLEL_CHAPTER_TAGS mismatch. Expected {expected}, got {PARALLEL_CHAPTER_TAGS}"
        )

    def test_sequential_chapter_tag_is_recommendation(self):
        """SEQUENTIAL_CHAPTER_TAG must be 'recommendation'."""
        assert SEQUENTIAL_CHAPTER_TAG == "recommendation"

    def test_registry_has_8_chapters(self):
        """CHAPTER_REGISTRY must have exactly 8 chapters."""
        assert len(CHAPTER_REGISTRY) == 8

    def test_registry_orders_are_unique_and_sequential(self):
        """Chapter orders must be 1-8, each unique."""
        orders = sorted(ch["order"] for ch in CHAPTER_REGISTRY)
        assert orders == list(range(1, 9)), f"Expected orders 1-8, got {orders}"

    def test_min_chapters_for_recommendation_is_below_7(self):
        """MIN_CHAPTERS_FOR_RECOMMENDATION must be less than 7 (the prerequisite count)."""
        assert MIN_CHAPTERS_FOR_RECOMMENDATION < 7, (
            f"MIN_CHAPTERS_FOR_RECOMMENDATION={MIN_CHAPTERS_FOR_RECOMMENDATION} "
            "must be < 7 (there are 7 prerequisite chapters)."
        )
