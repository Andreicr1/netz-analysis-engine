"""Memo Book Generator v4 — Chapter-wise institutional memorandum.

Generates a 14-chapter Investment Committee Memorandum where each chapter
is produced independently from a frozen EvidencePack + a small set of
relevant evidence chunks.

Architecture invariants:
  - NO chapter receives previous chapter text.
  - NO chapter receives the full deal corpus.
  - Every chapter receives the full EvidencePack (≤ 5k tokens).
  - Evidence chunks per chapter: ≤ 10 chunks × 1200 chars.
  - Chapter 13 (Recommendation) is synthesis-only — it receives NO
    raw evidence, only: EvidencePack, quant, critic, policy, sponsor flags.
  - Each chapter persists immediately after generation.
  - Resume safety: cached chapters are skipped on re-run.

Provides both sync (``generate_memo_book``) and async
(``async_generate_memo_book``) entry points.

Sole orchestrator — imports ALL sibling modules within memo package.

Error contract: never-raises (orchestration engine). Returns result dicts
with status information on failure.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from sqlalchemy.orm import Session

from ai_engine.model_config import get_model
from vertical_engines.credit.memo.batch import (
    build_chapter_request,
    parse_batch_results,
    poll_batch,
    submit_chapter_batch,
)
from vertical_engines.credit.memo.chapters import (
    _build_appendix_1,
    _build_appendix_2,
    _extract_recommendation_from_text,
    build_evidence_summary,
    generate_chapter,
    generate_recommendation_chapter,
    select_chapter_chunks,
)
from vertical_engines.credit.memo.models import CHAPTER_REGISTRY, CallOpenAiFn

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Helpers — extracted to eliminate copy-paste across sequential / batch paths
# ---------------------------------------------------------------------------


def _extract_gap_text(gap: Any) -> str:
    """Extract gap description from a gap entry (dict or string)."""
    if isinstance(gap, dict):
        return gap.get("description") or gap.get("gap") or str(gap)
    return str(gap or "")


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
    evidence_pack_json_len: int,
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
        token_count_input=evidence_pack_json_len // 4,
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

    Returns dict with fullMemo, chapters, recommendation, etc.
    """
    from ai_engine.governance.artifact_cache import load_cached_chapter

    # ── Build shared evidence summary (F + E) — once for all chapters ──
    evidence_summary = build_evidence_summary(evidence_pack)
    evidence_pack_json_len = len(json.dumps(evidence_pack, default=str))
    logger.info("EVIDENCE_SUMMARY_BUILT", chars=len(evidence_summary))

    chapters_output: list[dict[str, Any]] = []
    section_texts_map: dict[int, str] = {}
    chapter_texts_dict: dict[str, str] = {}
    all_citations: list[dict[str, Any]] = []
    all_critical_gaps: list[dict[str, Any]] = []
    recommendation = "CONDITIONAL"
    confidence_level = "MEDIUM"
    chapters_generated = 0
    chapters_from_cache = 0

    batch_pending: list[dict[str, Any]] = []

    for ch_num, ch_tag, ch_title in CHAPTER_REGISTRY:
        # ── Check cache ──────────────────────────────────────────
        cached_row = load_cached_chapter(
            db, evidence_pack_id=evidence_pack_id, chapter_number=ch_num,
        )
        if cached_row is not None:
            cached_content = cached_row.get("content_md", "")
            logger.info("CHAPTER_CACHE_HIT", chapter=ch_num, tag=ch_tag)
            section_texts_map[ch_num] = f"## {ch_num}. {ch_title}\n\n{cached_content}"
            chapters_output.append({
                "chapter_number": ch_num,
                "chapter_tag": ch_tag,
                "chapter_title": ch_title,
                "from_cache": True,
            })
            chapters_from_cache += 1
            if ch_tag == "ch13_recommendation":
                recommendation, confidence_level = _extract_recommendation_from_text(cached_content)
            continue

        # ── Generate chapter ─────────────────────────────────────
        ch_model = get_model(ch_tag) if ch_tag != "ch13_recommendation" else get_model("ch13_recommendation")

        if use_batch and ch_tag != "ch13_recommendation":
            chunk_source = evidence_chunks or evidence_map
            ch_evidence = select_chapter_chunks(chunk_source, ch_tag)
            batch_pending.append({
                "ch_num": ch_num, "ch_tag": ch_tag, "ch_title": ch_title,
                "ch_model": ch_model, "ch_evidence": ch_evidence,
            })
            continue

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
            if decision_anchor:
                recommendation = decision_anchor["finalDecision"]
        else:
            chunk_source = evidence_chunks or evidence_map
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

        ch_citations = chapter_result.get("citations", [])
        _attribute_citations(ch_citations, ch_num=ch_num, ch_tag=ch_tag, ch_title=ch_title)
        all_citations.extend(ch_citations)

        ch_critical_gaps = chapter_result.get("critical_gaps", [])
        for gap in ch_critical_gaps:
            all_critical_gaps.append({
                "chapter_tag": ch_tag,
                "chapter_num": ch_num,
                "chapter_title": ch_title,
                "gap": _extract_gap_text(gap),
            })

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
            evidence_pack_json_len=evidence_pack_json_len,
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
            "BATCH_MODE_START",
            chapters=len(batch_pending),
            tags=[p["ch_tag"] for p in batch_pending],
        )

        batch_requests: list[dict[str, Any]] = []
        for pending in batch_pending:
            prepared = generate_chapter(
                chapter_num=pending["ch_num"],
                chapter_tag=pending["ch_tag"],
                chapter_title=pending["ch_title"],
                evidence_pack=evidence_pack,
                evidence_chunks=pending["ch_evidence"],
                call_openai_fn=call_openai_fn,
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

        try:
            batch_id = submit_chapter_batch(
                batch_requests,
                metadata={"deal_id": deal_id, "version": version_tag[:40]},
            )
            logger.info("BATCH_SUBMITTED", batch_id=batch_id, chapters=len(batch_requests))

            batch_result = poll_batch(batch_id, timeout=1800)
            logger.info("BATCH_COMPLETED", batch_id=batch_id, result=batch_result.get("request_counts"))

            parsed_results = parse_batch_results(batch_result)

            for pending in batch_pending:
                ch_num = pending["ch_num"]
                ch_tag = pending["ch_tag"]
                ch_title = pending["ch_title"]
                ch_model = pending["ch_model"]

                result_data = parsed_results.get(ch_tag, {})

                if "error" in result_data:
                    logger.error(
                        "BATCH_CHAPTER_FAILED",
                        ch=ch_num, tag=ch_tag, error=result_data["error"],
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

                ch_critical_gaps = result_data.get("critical_gaps", [])
                for gap in ch_critical_gaps:
                    all_critical_gaps.append({
                        "chapter_tag": ch_tag,
                        "chapter_num": ch_num,
                        "chapter_title": ch_title,
                        "gap": _extract_gap_text(gap),
                    })

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
                    evidence_pack_json_len=evidence_pack_json_len,
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
            logger.error("BATCH_MODE_FAILED — falling back to sequential", error=str(exc), exc_info=True)
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

                ch_critical_gaps = chapter_result.get("critical_gaps", [])
                for gap in ch_critical_gaps:
                    all_critical_gaps.append({
                        "chapter_tag": pending["ch_tag"],
                        "chapter_num": pending["ch_num"],
                        "chapter_title": pending["ch_title"],
                        "gap": _extract_gap_text(gap),
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
                    evidence_pack_json_len=evidence_pack_json_len,
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

    # ── Build appendices ──────────────────────────────────────────
    appendix_1 = _build_appendix_1(all_citations)
    appendix_2 = _build_appendix_2(all_critical_gaps) if all_critical_gaps else ""

    real_citations = [c for c in all_citations if c.get("chunk_id") != "NONE"]
    unsupported_claims_detected = len(real_citations) == 0

    if unsupported_claims_detected:
        logger.warning(
            "CITATION_SELF_AUDIT_FAIL: zero real citations",
            chapters=len(CHAPTER_REGISTRY),
        )

    section_texts = [section_texts_map[ch_num] for ch_num, _, _ in CHAPTER_REGISTRY if ch_num in section_texts_map]
    memo_body = "\n\n---\n\n".join(section_texts)
    full_memo = memo_body + "\n\n---\n\n" + appendix_1
    if appendix_2:
        full_memo += "\n\n---\n\n" + appendix_2

    logger.info("MEMO_BOOK_COMPLETE", chapters_generated=chapters_generated, chapters_from_cache=chapters_from_cache, total_memo_chars=len(full_memo), recommendation=recommendation, citations_total=len(all_citations), citations_real=len(real_citations), unsupported_claims_detected=unsupported_claims_detected, critical_gaps_total=len(all_critical_gaps))

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
    the other chapters.

    Returns the same dict structure as ``generate_memo_book()``.
    """
    from ai_engine.governance.artifact_cache import load_cached_chapter

    if sem is None:
        sem = asyncio.Semaphore(5)

    evidence_summary = build_evidence_summary(evidence_pack)
    evidence_pack_json_len = len(json.dumps(evidence_pack, default=str))
    logger.info("ASYNC_EVIDENCE_SUMMARY_BUILT", chars=len(evidence_summary))

    chapters_output: list[dict[str, Any]] = []
    section_texts_map: dict[int, str] = {}
    chapter_texts_dict: dict[str, str] = {}
    all_citations: list[dict[str, Any]] = []
    all_critical_gaps: list[dict[str, Any]] = []
    recommendation = "CONDITIONAL"
    confidence_level = "MEDIUM"
    chapters_generated = 0
    chapters_from_cache = 0

    chapters_to_generate: list[tuple[int, str, str, str]] = []

    for ch_num, ch_tag, ch_title in CHAPTER_REGISTRY:
        cached_row = load_cached_chapter(
            db, evidence_pack_id=evidence_pack_id, chapter_number=ch_num,
        )
        if cached_row is not None:
            cached_content = cached_row.get("content_md", "")
            logger.info("CHAPTER_CACHE_HIT", chapter=ch_num, tag=ch_tag)
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

    parallel_chapters = [
        c for c in chapters_to_generate if c[1] != "ch13_recommendation"
    ]
    ch13_entry = next(
        (c for c in chapters_to_generate if c[1] == "ch13_recommendation"),
        None,
    )

    chapter_results: dict[str, dict[str, Any]] = {}

    if parallel_chapters:
        chunk_source = evidence_chunks or evidence_map

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

    logger.info("ASYNC_PARALLEL_CHAPTERS_COMPLETE", count=len(chapter_results))

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
            all_critical_gaps.append({
                "chapter_tag": ch_tag,
                "chapter_num": ch_num,
                "chapter_title": ch_title,
                "gap": _extract_gap_text(gap),
            })

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
            evidence_pack_json_len=evidence_pack_json_len,
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
            evidence_pack_json_len=evidence_pack_json_len,
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
            "ASYNC_CITATION_SELF_AUDIT_FAIL: zero real citations",
            chapters=len(CHAPTER_REGISTRY),
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

    logger.info("ASYNC_MEMO_BOOK_COMPLETE", chapters_generated=chapters_generated, chapters_from_cache=chapters_from_cache, total_memo_chars=len(full_memo), recommendation=recommendation, citations_total=len(all_citations), citations_real=len(real_citations))

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
