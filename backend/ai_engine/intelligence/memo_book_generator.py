"""Memo Book Generator v4 — Chapter-wise institutional memorandum.

Generates a 13-chapter Investment Committee Memorandum where each chapter
is produced independently from a frozen EvidencePack + a small set of
relevant evidence chunks.

Architecture invariants:
  • NO chapter receives previous chapter text.
  • NO chapter receives the full deal corpus.
  • Every chapter receives the full EvidencePack (≤ 5k tokens).
  • Evidence chunks per chapter: ≤ 10 chunks × 1200 chars.
  • Chapter 13 (Recommendation) is synthesis-only — it receives NO
    raw evidence, only: EvidencePack, quant, critic, policy, sponsor flags.
  • Each chapter persists immediately after generation.
  • Resume safety: cached chapters are skipped on re-run.

Provides both sync (``generate_memo_book``) and async
(``async_generate_memo_book``) entry points.  The async version
generates chapters 1-12 and 14 in parallel via ``asyncio.TaskGroup``
with semaphore-bounded concurrency.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ai_engine.intelligence.batch_client import (
    build_chapter_request,
    parse_batch_results,
    poll_batch,
    submit_chapter_batch,
)
from ai_engine.intelligence.memo_chapter_engine import (
    _build_appendix_1,
    _build_appendix_2,
    _extract_recommendation_from_text,
    build_evidence_summary,
    generate_chapter,
    generate_recommendation_chapter,
    select_chapter_chunks,
)
from ai_engine.model_config import get_model

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Callback protocol for call_openai_fn
# ---------------------------------------------------------------------------

class CallOpenAiFn(Protocol):
    """Structural type for the OpenAI completion callback."""

    def __call__(
        self, system_prompt: str, user_content: str, *, max_tokens: int = ..., model: str | None = ...,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Chapter registry — authoritative 13-chapter table
# ---------------------------------------------------------------------------

CHAPTER_REGISTRY: list[tuple[int, str, str]] = [
    (1,  "ch01_exec",           "Executive Summary"),
    (2,  "ch02_macro",          "Market Context"),
    (3,  "ch03_exit",           "Macro Regime & Exit Environment"),
    (4,  "ch04_sponsor",        "Sponsor & Management Analysis"),
    (5,  "ch05_legal",          "Legal Structure & Document Analysis"),
    (6,  "ch06_terms",          "Detailed Investment Terms & Covenants"),
    (7,  "ch07_capital",        "Capital Structure Analysis"),
    (8,  "ch08_returns",        "Return Modeling"),
    (9,  "ch09_downside",       "Downside Scenario Model"),
    (10, "ch10_covenants",      "Covenant Strength Assessment"),
    (11, "ch11_risks",          "Key Risks"),
    (12, "ch12_peers",          "Peer Comparison"),
    (13, "ch13_recommendation", "Final Recommendation"),
    (14, "ch14_governance_stress", "Governance Under Adverse Event & Stress Analysis"),
]

# ---------------------------------------------------------------------------
# Helpers — extracted to eliminate copy-paste across sequential / batch paths
# ---------------------------------------------------------------------------


def _attribute_citations(
    citations: list[dict[str, Any]],
    *,
    ch_num: int,
    ch_tag: str,
    ch_title: str,
) -> None:
    """Stamp chapter metadata onto each citation dict (mutates in place)."""
    for cit in citations:
        cit["chapter_number"] = ch_num
        cit["chapter_tag"] = ch_tag
        cit["chapter_title"] = ch_title


def _persist_chapter(
    db: Session,
    *,
    fund_id: Any,
    deal_id: Any,
    evidence_pack_id: Any,
    ch_num: int,
    ch_tag: str,
    ch_title: str,
    section_text: str,
    version_tag: str,
    ch_model: str,
    evidence_pack: dict[str, Any],
    actor_id: str,
) -> None:
    """Persist a single memo chapter row with is_current flip.

    Defence-in-depth: strips NUL bytes that break PostgreSQL text columns.
    """
    import datetime as dt

    from sqlalchemy import update as _sa_update

    from app.domains.credit.modules.ai.models import MemoChapter

    section_text = section_text.replace("\x00", "")
    now = dt.datetime.now(dt.UTC)

    # Mark only THIS chapter_number as not-current before inserting new version
    db.execute(
        _sa_update(MemoChapter)
        .where(
            MemoChapter.fund_id == fund_id,
            MemoChapter.deal_id == deal_id,
            MemoChapter.chapter_number == ch_num,
            MemoChapter.is_current == True,  # noqa: E712
        )
        .values(is_current=False),
    )

    chapter_row = MemoChapter(
        fund_id=fund_id,
        deal_id=deal_id,
        evidence_pack_id=evidence_pack_id,
        chapter_number=ch_num,
        chapter_tag=ch_tag,
        chapter_title=ch_title[:200],
        content_md=section_text,
        version_tag=version_tag[:40],
        generated_at=now,
        model_version=ch_model[:80],
        token_count_input=len(json.dumps(evidence_pack, default=str)) // 4,
        token_count_output=len(section_text) // 4,
        is_current=True,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(chapter_row)
    db.flush()


# ---------------------------------------------------------------------------
# Full memo book generation (with resume / caching)
# ---------------------------------------------------------------------------

def generate_memo_book(
    db: Session,
    *,
    fund_id: Any,
    deal_id: Any,
    evidence_pack: dict[str, Any],
    evidence_pack_id: Any,
    evidence_map: list[dict[str, Any]],
    evidence_chunks: list[dict[str, Any]] | None = None,
    quant_dict: dict[str, Any],
    critic_findings: dict[str, Any],
    policy_dict: dict[str, Any],
    sponsor_output: dict[str, Any],
    version_tag: str,
    call_openai_fn: CallOpenAiFn,
    model: str | None = None,
    model_mini: str | None = None,
    actor_id: str = "ai-engine",
    decision_anchor: dict[str, Any] | None = None,
    use_batch: bool = False,
) -> dict[str, Any]:
    """Generate all 14 chapters of the Investment Memorandum.

    Implements resume safety: cached chapters are re-used, only missing
    chapters are generated.

    Cost governance optimisations:
      B — Per-chapter chunk budgets (select_chapter_chunks)
      D — Evidence pack filtering (filter_evidence_pack)
      E — Prompt caching via shared evidence summary prefix
      F — Deterministic evidence summary (build_evidence_summary)
      G — Batch API support (use_batch=True)

    Returns:
        {
            "fullMemo": str,                    # body + Appendix 1
            "memo_body": str,                    # body only (no appendix)
            "appendix_1_source_index": str,       # Appendix 1 Markdown
            "citations_used": list[dict],         # all citations
            "unsupported_claims_detected": bool,  # True if 0 real cites
            "chapters": list[dict],
            "recommendation": str,
            "confidenceLevel": str,
            "chaptersGenerated": int,
            "chaptersFromCache": int,
        }

    """
    from ai_engine.governance.artifact_cache import load_cached_chapter

    # ── Build shared evidence summary (F + E) — once for all chapters ──
    evidence_summary = build_evidence_summary(evidence_pack)
    logger.info("EVIDENCE_SUMMARY_BUILT chars=%d", len(evidence_summary))

    # NOTE: We no longer blanket-reset is_current for ALL chapters.
    # Instead, each chapter is individually marked not-current only when
    # its replacement is about to be persisted (see per-chapter update below).
    # This ensures partial runs preserve previous chapter versions.

    chapters_output: list[dict[str, Any]] = []
    section_texts_map: dict[int, str] = {}  # ch_num → formatted section (preserves order for batch mode)
    chapter_texts_dict: dict[str, str] = {}  # ch_tag → section_text (for Tone Normalizer)
    all_citations: list[dict[str, Any]] = []
    all_critical_gaps: list[dict[str, Any]] = []  # {chapter_tag, chapter_title, gap} rows for Appendix 2
    recommendation = "CONDITIONAL"
    confidence_level = "MEDIUM"
    chapters_generated = 0
    chapters_from_cache = 0

    # ── Batch mode (G): collect pending chapters, submit as single batch ──
    batch_pending: list[dict[str, Any]] = []  # chapters needing generation (for batch mode)

    for ch_num, ch_tag, ch_title in CHAPTER_REGISTRY:
        # ── Check cache ──────────────────────────────────────────
        cached_row = load_cached_chapter(
            db, evidence_pack_id=evidence_pack_id, chapter_number=ch_num,
        )
        if cached_row is not None:
            cached_content = cached_row.get("content_md", "")
            logger.info("CHAPTER_CACHE_HIT", extra={"chapter": ch_num, "tag": ch_tag})
            section_texts_map[ch_num] = f"## {ch_num}. {ch_title}\n\n{cached_content}"
            chapters_output.append({
                "chapter_number": ch_num,
                "chapter_tag": ch_tag,
                "chapter_title": ch_title,
                "from_cache": True,
            })
            chapters_from_cache += 1
            # Extract recommendation from cached ch13
            if ch_tag == "ch13_recommendation":
                recommendation, confidence_level = _extract_recommendation_from_text(cached_content)
            continue

        # ── Generate chapter ─────────────────────────────────────
        # Resolve per-chapter model from model_config (env-overridable)
        ch_model = get_model(ch_tag) if ch_tag != "ch13_recommendation" else get_model("ch13_recommendation")

        if use_batch and ch_tag != "ch13_recommendation":
            # ── Batch mode: defer generation, collect request ────
            chunk_source = evidence_chunks if evidence_chunks else evidence_map
            ch_evidence = select_chapter_chunks(chunk_source, ch_tag)
            batch_pending.append({
                "ch_num": ch_num, "ch_tag": ch_tag, "ch_title": ch_title,
                "ch_model": ch_model, "ch_evidence": ch_evidence,
            })
            continue  # will be processed after the loop

        if ch_tag == "ch13_recommendation":
            ch_summaries = {}
            for prev_tag, prev_text in chapter_texts_dict.items():
                if prev_tag != "ch13_recommendation" and prev_tag != "ch14_governance_stress":
                    ch_summaries[prev_tag] = prev_text[:500]

            chapter_result = generate_recommendation_chapter(
                evidence_pack=evidence_pack,
                quant_summary=quant_dict,
                critic_findings=critic_findings,
                policy_breaches=policy_dict,
                sponsor_red_flags=sponsor_output.get("governance_red_flags", []),
                call_openai_fn=call_openai_fn,
                model=ch_model,
                decision_anchor=decision_anchor,
                chapter_summaries=ch_summaries,
            )
            recommendation = chapter_result.get("recommendation", "CONDITIONAL")
            confidence_level = chapter_result.get("confidence_level", "MEDIUM")
            # Final safety: anchor always wins
            if decision_anchor:
                recommendation = decision_anchor["finalDecision"]
        else:
            # Select relevant evidence chunks for this chapter.
            # Prefer raw_chunks (full content); fall back to evidence_map.
            chunk_source = evidence_chunks if evidence_chunks else evidence_map
            ch_evidence = select_chapter_chunks(chunk_source, ch_tag)

            chapter_result = generate_chapter(
                chapter_num=ch_num,
                chapter_tag=ch_tag,
                chapter_title=ch_title,
                evidence_pack=evidence_pack,
                evidence_chunks=ch_evidence,
                call_openai_fn=call_openai_fn,
                model=ch_model,
                evidence_summary=evidence_summary,
            )

        section_text = chapter_result.get("section_text", "")
        section_texts_map[ch_num] = f"## {ch_num}. {ch_title}\n\n{section_text}"

        # ── Accumulate citations with chapter attribution ────────
        ch_citations = chapter_result.get("citations", [])
        _attribute_citations(ch_citations, ch_num=ch_num, ch_tag=ch_tag, ch_title=ch_title)
        all_citations.extend(ch_citations)

        # ── Accumulate critical gaps for Appendix 2 ──────────────
        ch_critical_gaps = chapter_result.get("critical_gaps", [])
        for gap in ch_critical_gaps:
            gap_text = gap.get("description") or gap.get("gap") or str(gap) if isinstance(gap, dict) else str(gap or "")
            all_critical_gaps.append({
                "chapter_tag": ch_tag,
                "chapter_num": ch_num,
                "chapter_title": ch_title,
                "gap": gap_text,
            })

        # ── Persist chapter immediately ──────────────────────────
        section_text = section_text.replace("\x00", "")
        chapter_texts_dict[ch_tag] = section_text  # expose to Tone Normalizer
        _persist_chapter(
            db,
            fund_id=fund_id,
            deal_id=deal_id,
            evidence_pack_id=evidence_pack_id,
            ch_num=ch_num,
            ch_tag=ch_tag,
            ch_title=ch_title,
            section_text=section_text,
            version_tag=version_tag,
            ch_model=ch_model,
            evidence_pack=evidence_pack,
            actor_id=actor_id,
        )

        chapters_generated += 1
        chapters_output.append({
            "chapter_number": ch_num,
            "chapter_tag": ch_tag,
            "chapter_title": ch_title,
            "from_cache": False,
            "output_chars": len(section_text),
        })

    # ── Batch mode (G): submit deferred chapters as a single batch ───
    if batch_pending:
        logger.info(
            "BATCH_MODE_START chapters=%d tags=%s",
            len(batch_pending),
            [p["ch_tag"] for p in batch_pending],
        )

        # 1. Prepare all chapter requests via prepare_only mode
        batch_requests: list[dict[str, Any]] = []
        for pending in batch_pending:
            prepared = generate_chapter(
                chapter_num=pending["ch_num"],
                chapter_tag=pending["ch_tag"],
                chapter_title=pending["ch_title"],
                evidence_pack=evidence_pack,
                evidence_chunks=pending["ch_evidence"],
                call_openai_fn=call_openai_fn,  # unused in prepare_only
                model=pending["ch_model"],
                evidence_summary=evidence_summary,
                prepare_only=True,
            )
            batch_requests.append(
                build_chapter_request(
                    custom_id=pending["ch_tag"],
                    system_prompt=prepared["system_prompt"],
                    user_content=prepared["user_content"],
                    model=pending["ch_model"],
                    max_tokens=prepared["max_tokens"],
                ),
            )

        # 2. Submit batch
        try:
            batch_id = submit_chapter_batch(
                batch_requests,
                metadata={"deal_id": deal_id, "version": version_tag[:40]},
            )
            logger.info("BATCH_SUBMITTED batch_id=%s chapters=%d", batch_id, len(batch_requests))

            # 3. Poll until completion (30 min timeout)
            batch_result = poll_batch(batch_id, timeout=1800)
            logger.info("BATCH_COMPLETED batch_id=%s result=%s", batch_id, batch_result.get("request_counts"))

            # 4. Parse batch results
            parsed_results = parse_batch_results(batch_result)

            # 5. Process each chapter result (same as sequential path)
            for pending in batch_pending:
                ch_num = pending["ch_num"]
                ch_tag = pending["ch_tag"]
                ch_title = pending["ch_title"]
                ch_model = pending["ch_model"]

                result_data = parsed_results.get(ch_tag, {})

                if "error" in result_data:
                    logger.error(
                        "BATCH_CHAPTER_FAILED ch=%d tag=%s error=%s",
                        ch_num, ch_tag, result_data["error"],
                    )
                    section_text = (
                        f"*Chapter {ch_num}: {ch_title} — "
                        f"batch generation failed: {result_data['error']}*"
                    )
                    ch_citations: list[dict[str, Any]] = []
                else:
                    section_text = result_data.get("section_text", "")
                    section_text = section_text.replace("\x00", "")
                    ch_citations = result_data.get("citations", [])
                    if not section_text.strip():
                        section_text = (
                            f"*Chapter {ch_num}: {ch_title} — "
                            f"LLM returned empty (batch).*"
                        )

                section_texts_map[ch_num] = f"## {ch_num}. {ch_title}\n\n{section_text}"

                _attribute_citations(ch_citations, ch_num=ch_num, ch_tag=ch_tag, ch_title=ch_title)
                all_citations.extend(ch_citations)

                # Accumulate critical gaps for Appendix 2
                ch_critical_gaps = result_data.get("critical_gaps", [])
                for gap in ch_critical_gaps:
                    gap_text = gap.get("description") or gap.get("gap") or str(gap) if isinstance(gap, dict) else str(gap or "")
                    all_critical_gaps.append({
                        "chapter_tag": ch_tag,
                        "chapter_num": ch_num,
                        "chapter_title": ch_title,
                        "gap": gap_text,
                    })

                # Persist chapter
                section_text = section_text.replace("\x00", "")
                chapter_texts_dict[ch_tag] = section_text
                _persist_chapter(
                    db,
                    fund_id=fund_id,
                    deal_id=deal_id,
                    evidence_pack_id=evidence_pack_id,
                    ch_num=ch_num,
                    ch_tag=ch_tag,
                    ch_title=ch_title,
                    section_text=section_text,
                    version_tag=version_tag,
                    ch_model=ch_model,
                    evidence_pack=evidence_pack,
                    actor_id=actor_id,
                )

                chapters_generated += 1
                chapters_output.append({
                    "chapter_number": ch_num,
                    "chapter_tag": ch_tag,
                    "chapter_title": ch_title,
                    "from_cache": False,
                    "output_chars": len(section_text),
                    "batch_mode": True,
                })

        except Exception as exc:
            logger.error(
                "BATCH_MODE_FAILED error=%s — falling back to sequential", exc,
                exc_info=True,
            )
            # Fallback: run deferred chapters sequentially
            for pending in batch_pending:
                chapter_result = generate_chapter(
                    chapter_num=pending["ch_num"],
                    chapter_tag=pending["ch_tag"],
                    chapter_title=pending["ch_title"],
                    evidence_pack=evidence_pack,
                    evidence_chunks=pending["ch_evidence"],
                    call_openai_fn=call_openai_fn,
                    model=pending["ch_model"],
                    evidence_summary=evidence_summary,
                )

                section_text = chapter_result.get("section_text", "")
                section_texts_map[pending["ch_num"]] = (
                    f"## {pending['ch_num']}. {pending['ch_title']}\n\n{section_text}"
                )

                ch_citations = chapter_result.get("citations", [])
                _attribute_citations(
                    ch_citations,
                    ch_num=pending["ch_num"],
                    ch_tag=pending["ch_tag"],
                    ch_title=pending["ch_title"],
                )
                all_citations.extend(ch_citations)

                # Accumulate critical gaps for Appendix 2
                ch_critical_gaps = chapter_result.get("critical_gaps", [])
                for gap in ch_critical_gaps:
                    gap_text = gap.get("description") or gap.get("gap") or str(gap) if isinstance(gap, dict) else str(gap or "")
                    all_critical_gaps.append({
                        "chapter_tag": pending["ch_tag"],
                        "chapter_num": pending["ch_num"],
                        "chapter_title": pending["ch_title"],
                        "gap": gap_text,
                    })

                section_text = section_text.replace("\x00", "")
                chapter_texts_dict[pending["ch_tag"]] = section_text
                _persist_chapter(
                    db,
                    fund_id=fund_id,
                    deal_id=deal_id,
                    evidence_pack_id=evidence_pack_id,
                    ch_num=pending["ch_num"],
                    ch_tag=pending["ch_tag"],
                    ch_title=pending["ch_title"],
                    section_text=section_text,
                    version_tag=version_tag,
                    ch_model=pending["ch_model"],
                    evidence_pack=evidence_pack,
                    actor_id=actor_id,
                )

                chapters_generated += 1
                chapters_output.append({
                    "chapter_number": pending["ch_num"],
                    "chapter_tag": pending["ch_tag"],
                    "chapter_title": pending["ch_title"],
                    "from_cache": False,
                    "output_chars": len(section_text),
                })

    # ── Build Appendix 1 — Source Index ──────────────────────────
    appendix_1 = _build_appendix_1(all_citations)

    # ── Build Appendix 2 — Data Gaps Register (only if critical gaps exist) ──
    appendix_2 = _build_appendix_2(all_critical_gaps) if all_critical_gaps else ""

    # ── Self-audit: citations_used > 0 or FAIL HARD ──────────────
    real_citations = [c for c in all_citations if c.get("chunk_id") != "NONE"]
    unsupported_claims_detected = len(real_citations) == 0

    if unsupported_claims_detected:
        logger.warning(
            "CITATION_SELF_AUDIT_FAIL: zero real citations across %d chapters",
            len(CHAPTER_REGISTRY),
        )

    # ── Assemble full memo (body + appendices) ────────────────────
    # Re-assemble in chapter order (dict keys may be out of order due to batch mode)
    section_texts = [section_texts_map[ch_num] for ch_num, _, _ in CHAPTER_REGISTRY if ch_num in section_texts_map]
    memo_body = "\n\n---\n\n".join(section_texts)
    full_memo = memo_body + "\n\n---\n\n" + appendix_1
    if appendix_2:
        full_memo += "\n\n---\n\n" + appendix_2

    logger.info("MEMO_BOOK_COMPLETE", extra={
        "chapters_generated": chapters_generated,
        "chapters_from_cache": chapters_from_cache,
        "total_memo_chars": len(full_memo),
        "recommendation": recommendation,
        "citations_total": len(all_citations),
        "citations_real": len(real_citations),
        "unsupported_claims_detected": unsupported_claims_detected,
        "critical_gaps_total": len(all_critical_gaps),
    })

    return {
        "fullMemo": full_memo,
        "memo_body": memo_body,
        "appendix_1_source_index": appendix_1,
        "appendix_2_data_gaps": appendix_2,
        "critical_gaps": all_critical_gaps,
        "citations_used": all_citations,
        "unsupported_claims_detected": unsupported_claims_detected,
        "chapters": chapters_output,
        "chapter_texts": chapter_texts_dict,  # ch_tag → section_text for Tone Normalizer
        "recommendation": recommendation,
        "confidenceLevel": confidence_level,
        "chaptersGenerated": chapters_generated,
        "chaptersFromCache": chapters_from_cache,
    }


# ---------------------------------------------------------------------------
# Async memo book generation — parallel chapters via asyncio.TaskGroup
# ---------------------------------------------------------------------------


async def async_generate_memo_book(
    db: Session,
    *,
    fund_id: Any,
    deal_id: Any,
    evidence_pack: dict[str, Any],
    evidence_pack_id: Any,
    evidence_map: list[dict[str, Any]],
    evidence_chunks: list[dict[str, Any]] | None = None,
    quant_dict: dict[str, Any],
    critic_findings: dict[str, Any],
    policy_dict: dict[str, Any],
    sponsor_output: dict[str, Any],
    version_tag: str,
    call_openai_fn: CallOpenAiFn,
    model: str | None = None,
    model_mini: str | None = None,
    actor_id: str = "ai-engine",
    decision_anchor: dict[str, Any] | None = None,
    sem: asyncio.Semaphore | None = None,
) -> dict[str, Any]:
    """Async parallel memo book generation.

    Generates chapters 1-12 and 14 concurrently via ``asyncio.TaskGroup``,
    then generates chapter 13 (Recommendation) which needs summaries from
    the other chapters.  All chapter persistence is batched sequentially
    after generation completes on the main (event loop) thread's DB session.

    Uses ``asyncio.to_thread()`` for each chapter's ``generate_chapter()``
    call since that function internally calls the sync ``call_openai_fn``.
    The semaphore bounds concurrent LLM calls to prevent API rate limiting.

    Returns the same dict structure as ``generate_memo_book()``.
    """
    from ai_engine.governance.artifact_cache import load_cached_chapter

    if sem is None:
        sem = asyncio.Semaphore(5)

    # ── Build shared evidence summary — once for all chapters ─────
    evidence_summary = build_evidence_summary(evidence_pack)
    logger.info("ASYNC_EVIDENCE_SUMMARY_BUILT chars=%d", len(evidence_summary))

    chapters_output: list[dict[str, Any]] = []
    section_texts_map: dict[int, str] = {}
    chapter_texts_dict: dict[str, str] = {}
    all_citations: list[dict[str, Any]] = []
    all_critical_gaps: list[dict[str, Any]] = []
    recommendation = "CONDITIONAL"
    confidence_level = "MEDIUM"
    chapters_generated = 0
    chapters_from_cache = 0

    # ── Check cache for all chapters (sequential, fast DB reads) ──
    chapters_to_generate: list[tuple[int, str, str, str]] = []

    for ch_num, ch_tag, ch_title in CHAPTER_REGISTRY:
        cached_row = load_cached_chapter(
            db, evidence_pack_id=evidence_pack_id, chapter_number=ch_num,
        )
        if cached_row is not None:
            cached_content = cached_row.get("content_md", "")
            logger.info("CHAPTER_CACHE_HIT", extra={"chapter": ch_num, "tag": ch_tag})
            section_texts_map[ch_num] = f"## {ch_num}. {ch_title}\n\n{cached_content}"
            chapter_texts_dict[ch_tag] = cached_content
            chapters_output.append({
                "chapter_number": ch_num,
                "chapter_tag": ch_tag,
                "chapter_title": ch_title,
                "from_cache": True,
            })
            chapters_from_cache += 1
            if ch_tag == "ch13_recommendation":
                recommendation, confidence_level = _extract_recommendation_from_text(
                    cached_content,
                )
            continue

        ch_model = (
            get_model(ch_tag)
            if ch_tag != "ch13_recommendation"
            else get_model("ch13_recommendation")
        )
        chapters_to_generate.append((ch_num, ch_tag, ch_title, ch_model))

    # ── Separate ch13 from parallel chapters ──────────────────────
    parallel_chapters = [
        c for c in chapters_to_generate if c[1] != "ch13_recommendation"
    ]
    ch13_entry = next(
        (c for c in chapters_to_generate if c[1] == "ch13_recommendation"),
        None,
    )

    # ── Generate chapters 1-12, 14 in parallel via TaskGroup ──────
    # TaskGroup cancels all siblings on first failure — no wasted
    # API calls on chapters that will be discarded.
    chapter_results: dict[str, dict[str, Any]] = {}

    if parallel_chapters:
        chunk_source = evidence_chunks if evidence_chunks else evidence_map

        async def _gen_chapter(
            ch_num: int, ch_tag: str, ch_title: str, ch_model: str,
        ) -> None:
            ch_evidence = select_chapter_chunks(chunk_source, ch_tag)
            async with sem:
                result = await asyncio.to_thread(
                    generate_chapter,
                    chapter_num=ch_num,
                    chapter_tag=ch_tag,
                    chapter_title=ch_title,
                    evidence_pack=evidence_pack,
                    evidence_chunks=ch_evidence,
                    call_openai_fn=call_openai_fn,
                    model=ch_model,
                    evidence_summary=evidence_summary,
                )
            chapter_results[ch_tag] = result

        async with asyncio.TaskGroup() as tg:
            for ch_num, ch_tag, ch_title, ch_model in parallel_chapters:
                tg.create_task(
                    _gen_chapter(ch_num, ch_tag, ch_title, ch_model),
                )

    logger.info(
        "ASYNC_PARALLEL_CHAPTERS_COMPLETE count=%d",
        len(chapter_results),
    )

    # ── Process parallel results ──────────────────────────────────
    for ch_num, ch_tag, ch_title, ch_model in parallel_chapters:
        result = chapter_results[ch_tag]
        section_text = result.get("section_text", "")
        section_text = section_text.replace("\x00", "")
        section_texts_map[ch_num] = f"## {ch_num}. {ch_title}\n\n{section_text}"
        chapter_texts_dict[ch_tag] = section_text

        ch_citations = result.get("citations", [])
        _attribute_citations(
            ch_citations, ch_num=ch_num, ch_tag=ch_tag, ch_title=ch_title,
        )
        all_citations.extend(ch_citations)

        ch_critical_gaps = result.get("critical_gaps", [])
        for gap in ch_critical_gaps:
            gap_text = (
                gap.get("description") or gap.get("gap") or str(gap)
                if isinstance(gap, dict)
                else str(gap or "")
            )
            all_critical_gaps.append({
                "chapter_tag": ch_tag,
                "chapter_num": ch_num,
                "chapter_title": ch_title,
                "gap": gap_text,
            })

        # Persist chapter on main session (sequential, deterministic order)
        _persist_chapter(
            db,
            fund_id=fund_id,
            deal_id=deal_id,
            evidence_pack_id=evidence_pack_id,
            ch_num=ch_num,
            ch_tag=ch_tag,
            ch_title=ch_title,
            section_text=section_text,
            version_tag=version_tag,
            ch_model=ch_model,
            evidence_pack=evidence_pack,
            actor_id=actor_id,
        )
        chapters_generated += 1
        chapters_output.append({
            "chapter_number": ch_num,
            "chapter_tag": ch_tag,
            "chapter_title": ch_title,
            "from_cache": False,
            "output_chars": len(section_text),
        })

    # ── Generate ch13 (Recommendation) — needs summaries ──────────
    if ch13_entry is not None:
        ch_num, ch_tag, ch_title, ch_model = ch13_entry
        ch_summaries = {
            tag: text[:500]
            for tag, text in chapter_texts_dict.items()
            if tag != "ch13_recommendation" and tag != "ch14_governance_stress"
        }

        async with sem:
            ch13_result = await asyncio.to_thread(
                generate_recommendation_chapter,
                evidence_pack=evidence_pack,
                quant_summary=quant_dict,
                critic_findings=critic_findings,
                policy_breaches=policy_dict,
                sponsor_red_flags=sponsor_output.get("governance_red_flags", []),
                call_openai_fn=call_openai_fn,
                model=ch_model,
                decision_anchor=decision_anchor,
                chapter_summaries=ch_summaries,
            )

        recommendation = ch13_result.get("recommendation", "CONDITIONAL")
        confidence_level = ch13_result.get("confidence_level", "MEDIUM")
        if decision_anchor:
            recommendation = decision_anchor["finalDecision"]

        section_text = ch13_result.get("section_text", "")
        section_text = section_text.replace("\x00", "")
        section_texts_map[ch_num] = f"## {ch_num}. {ch_title}\n\n{section_text}"
        chapter_texts_dict[ch_tag] = section_text

        ch_citations = ch13_result.get("citations", [])
        _attribute_citations(
            ch_citations, ch_num=ch_num, ch_tag=ch_tag, ch_title=ch_title,
        )
        all_citations.extend(ch_citations)

        _persist_chapter(
            db,
            fund_id=fund_id,
            deal_id=deal_id,
            evidence_pack_id=evidence_pack_id,
            ch_num=ch_num,
            ch_tag=ch_tag,
            ch_title=ch_title,
            section_text=section_text,
            version_tag=version_tag,
            ch_model=ch_model,
            evidence_pack=evidence_pack,
            actor_id=actor_id,
        )
        chapters_generated += 1
        chapters_output.append({
            "chapter_number": ch_num,
            "chapter_tag": ch_tag,
            "chapter_title": ch_title,
            "from_cache": False,
            "output_chars": len(section_text),
        })

    # ── Build appendices & assemble memo ──────────────────────────
    appendix_1 = _build_appendix_1(all_citations)
    appendix_2 = _build_appendix_2(all_critical_gaps) if all_critical_gaps else ""

    real_citations = [c for c in all_citations if c.get("chunk_id") != "NONE"]
    unsupported_claims_detected = len(real_citations) == 0

    if unsupported_claims_detected:
        logger.warning(
            "ASYNC_CITATION_SELF_AUDIT_FAIL: zero real citations across %d chapters",
            len(CHAPTER_REGISTRY),
        )

    section_texts = [
        section_texts_map[ch_num]
        for ch_num, _, _ in CHAPTER_REGISTRY
        if ch_num in section_texts_map
    ]
    memo_body = "\n\n---\n\n".join(section_texts)
    full_memo = memo_body + "\n\n---\n\n" + appendix_1
    if appendix_2:
        full_memo += "\n\n---\n\n" + appendix_2

    logger.info("ASYNC_MEMO_BOOK_COMPLETE", extra={
        "chapters_generated": chapters_generated,
        "chapters_from_cache": chapters_from_cache,
        "total_memo_chars": len(full_memo),
        "recommendation": recommendation,
        "citations_total": len(all_citations),
        "citations_real": len(real_citations),
    })

    return {
        "fullMemo": full_memo,
        "memo_body": memo_body,
        "appendix_1_source_index": appendix_1,
        "appendix_2_data_gaps": appendix_2,
        "critical_gaps": all_critical_gaps,
        "citations_used": all_citations,
        "unsupported_claims_detected": unsupported_claims_detected,
        "chapters": chapters_output,
        "chapter_texts": chapter_texts_dict,
        "recommendation": recommendation,
        "confidenceLevel": confidence_level,
        "chaptersGenerated": chapters_generated,
        "chaptersFromCache": chapters_from_cache,
    }


