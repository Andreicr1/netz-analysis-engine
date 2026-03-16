"""Pipeline intelligence generation — institutional two-call flow.

Implements generate_pipeline_intelligence() (Call A: structured + Call B: memo)
and generate_all_pending() (batch entrypoint).

Error contract: never-raises. Returns empty dict on failure, sets status to FAILED.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ai_engine.model_config import get_model
from ai_engine.openai_client import create_completion
from ai_engine.prompts import prompt_registry
from app.domains.credit.modules.ai.evidence_selector import (
    build_curated_context_text,
    curate_all_chapter_surfaces,
    curate_for_analysis_call,
)
from vertical_engines.credit.pipeline.models import (
    MAX_RETRIEVAL_CHUNKS,
    MIN_CITATIONS_REQUIRED,
    MIN_KEY_RISKS,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_READY,
)
from vertical_engines.credit.pipeline.persistence import (
    _set_intelligence_status,
    _write_derived_fields,
    _write_research_output,
)
from vertical_engines.credit.pipeline.screening import (
    _compute_missing_documents,
    _retrieve_deal_context,
    compute_completeness_score,
)
from vertical_engines.credit.pipeline.validation import (
    _validate_memo,
    _validate_output,
)

logger = structlog.get_logger()


def _call_gpt_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str,
    max_tokens: int = 12_000,
    call_label: str = "structured",
) -> dict[str, Any]:
    """Call GPT via centralised openai_client, parse JSON, add _meta."""
    result = create_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = (result.text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    obj = json.loads(raw)
    if isinstance(obj, dict):
        meta = obj.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("engine", "pipeline_engine")
        meta.setdefault("call", call_label)
        meta.setdefault("modelVersion", result.model)
        meta.setdefault("generatedAt", datetime.now(UTC).isoformat())
        obj["_meta"] = meta
    return obj


def generate_pipeline_intelligence(
    db: Session,
    *,
    deal_id: uuid.UUID,
    deal_name: str,
    sponsor_name: str | None = None,
    fund_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate full pipeline intelligence via institutional two-call flow.

    Call A: Structured Intelligence — deal_overview, terms, risks, citations,
            missing_documents (NO memo in this call).
    Call B: Memo Writer — independent 1500-3000 word IC memorandum grounded
            in structured output + evidence excerpts.

    Evidence surface: 80 chunks x 4000 chars = up to 320k chars.
    Citation minimum: 5 (hard fail).
    Missing-documents checklist: LLM + heuristic detection.
    """
    from app.domains.credit.modules.deals.models import PipelineDeal

    t0 = time.perf_counter()

    # ── Idempotency guard ─────────────────────────────────────────
    deal = db.execute(
        select(PipelineDeal).where(PipelineDeal.id == deal_id),
    ).scalar_one_or_none()
    if deal is None:
        logger.error("pipeline_deal_not_found", deal_id=str(deal_id))
        return {}

    if (
        not force
        and deal.research_output
        and deal.intelligence_status == STATUS_READY
    ):
        logger.info(
            "pipeline_deal_already_ready",
            deal_id=str(deal_id),
            generated_at=str(deal.intelligence_generated_at),
        )
        return deal.research_output  # type: ignore[return-value]

    # ── Mark PROCESSING ───────────────────────────────────────────
    _set_intelligence_status(db, deal_id, STATUS_PROCESSING)
    logger.info(
        "pipeline_intel_start",
        deal_id=str(deal_id),
        deal_name=deal_name,
    )

    # ── Retrieve context (institutional-scale, 80 chunks) ─────────
    context, chunk_count, raw_chunks, issuer_summary = _retrieve_deal_context(
        deal_id, deal_name, organization_id=organization_id or deal_id, max_chunks=MAX_RETRIEVAL_CHUNKS,
    )
    if not context:
        logger.warning(
            "pipeline_no_chunks",
            deal_id=str(deal_id),
        )
        _set_intelligence_status(db, deal_id, STATUS_FAILED)
        return {}

    # ── DUAL-SURFACE ARCHITECTURE ─────────────────────────────────
    raw_audit_chunks = list(raw_chunks)  # frozen copy for traceability

    curated_surfaces, curation_metadata = curate_all_chapter_surfaces(
        raw_chunks,
    )

    analysis_chunks = curate_for_analysis_call(raw_chunks, max_chunks=40)

    logger.info(
        "pipeline_context_retrieved",
        deal_id=str(deal_id),
        chunks=chunk_count,
        context_chars=len(context),
        audit_surface=len(raw_audit_chunks),
        analysis_surface=len(analysis_chunks),
        curated_chapters={k: len(v) for k, v in curated_surfaces.items()},
    )

    # ══════════════════════════════════════════════════════════════
    #  CALL A — Structured Intelligence (NO memo)
    # ══════════════════════════════════════════════════════════════
    structured_model = get_model("structured")
    system_a = prompt_registry.render(
        "pipeline_structured.j2",
        deal_name=deal_name,
        sponsor_name=sponsor_name or "Unknown",
        min_citations=MIN_CITATIONS_REQUIRED,
        min_risks=MIN_KEY_RISKS,
    )

    analysis_context_parts: list[str] = []
    for i, chunk in enumerate(analysis_chunks):
        doc_title = chunk.get("title", chunk.get("doc_type", "unknown"))
        issuer_tag = ""
        if chunk.get("issuer_name"):
            issuer_tag = (
                f" | issuer={chunk['issuer_name']}"
                f" ({chunk['issuer_category']})"
                f" | authority={chunk['issuer_tier']}"
            )
        header = (
            f"[Excerpt {i + 1} | {doc_title} "
            f"| type={chunk.get('doc_type', 'unknown')} "
            f"| pages {chunk.get('page_start', '?')}-"
            f"{chunk.get('page_end', '?')}"
            f"{issuer_tag}]"
        )
        analysis_context_parts.append(f"{header}\n{chunk.get('content', '')}")
    analysis_context = "\n\n---\n\n".join(analysis_context_parts)

    user_a = f"Document excerpts ({len(analysis_chunks)} curated, diversified):\n\n{analysis_context}"

    try:
        logger.info("pipeline_call_a_start", model=structured_model)
        structured_output = _call_gpt_json(
            system_a, user_a,
            model=structured_model,
            max_tokens=12_000,
            call_label="structured_intelligence",
        )
        logger.info("pipeline_call_a_complete")
    except Exception as exc:
        logger.error(
            "pipeline_call_a_failed",
            deal_id=str(deal_id),
            error=str(exc),
            exc_info=True,
        )
        _set_intelligence_status(db, deal_id, STATUS_FAILED)
        return {}

    # ── Validate structured output ────────────────────────────────
    is_valid_a, issues_a = _validate_output(structured_output)
    if not is_valid_a:
        logger.warning(
            "pipeline_validation_issues",
            deal_id=str(deal_id),
            issues="; ".join(issues_a),
        )
        structured_output["_validation_issues"] = issues_a

    # ── Enrich missing-documents checklist ────────────────────────
    llm_missing = structured_output.get("missing_documents", [])
    enriched_missing = _compute_missing_documents(raw_chunks, llm_missing)
    structured_output["missing_documents"] = enriched_missing

    # ── Compute data-room completeness score ──────────────────────
    completeness = compute_completeness_score(enriched_missing)
    structured_output["data_room_completeness"] = completeness

    # ── Persist issuer summary ────────────────────────────────────
    if issuer_summary:
        structured_output["issuer_summary"] = issuer_summary

    # ══════════════════════════════════════════════════════════════
    #  CALL B — Memo Writer (independent institutional prose)
    # ══════════════════════════════════════════════════════════════
    memo_model = get_model("pipeline_memo")
    system_b = prompt_registry.render(
        "pipeline_memo.j2",
        deal_name=deal_name,
        sponsor_name=sponsor_name or "Unknown",
    )

    structured_json = json.dumps(structured_output, separators=(",", ":"), default=str)

    issuer_section = ""
    if issuer_summary:
        issuer_lines = []
        for cat, names in sorted(issuer_summary.items()):
            issuer_lines.append(f"  {cat}: {', '.join(names)}")
        issuer_section = (
            "\n\n=== INSTITUTIONAL ISSUER SUMMARY ===\n"
            "The following authoritative institutional issuers were detected "
            "in the data room. Reference them by name in your analysis where "
            "relevant:\n" + "\n".join(issuer_lines)
        )

    completeness_section = (
        f"\n\n=== DATA ROOM COMPLETENESS ===\n"
        f"Score: {completeness['completeness_score']}/100 "
        f"({completeness['completeness_grade']})\n"
        f"Documents present: {completeness['documents_present']}/{completeness['total_tracked']}\n"
        f"Documents missing: {completeness['documents_missing']}/{completeness['total_tracked']}"
    )

    curated_context_text = build_curated_context_text(curated_surfaces)

    curation_summary_lines = []
    for ch_type, meta in curation_metadata.items():
        curation_summary_lines.append(
            f"  {ch_type}: {meta['original_count']} -> {meta['final_count']} "
            f"(hard_dedup={meta['hard_dedup_removed']}, "
            f"semantic_dedup={meta['semantic_dedup_removed']})",
        )
    curation_summary = "\n".join(curation_summary_lines)

    user_b = (
        f"=== STRUCTURED INTELLIGENCE DOSSIER ===\n\n"
        f"{structured_json}"
        f"{issuer_section}"
        f"{completeness_section}\n\n"
        f"=== EVIDENCE CURATION SUMMARY ===\n{curation_summary}\n\n"
        f"=== CURATED CHAPTER EVIDENCE ===\n\n"
        f"{curated_context_text}"
    )

    try:
        logger.info("pipeline_call_b_start", model=memo_model)
        memo_output = _call_gpt_json(
            system_b, user_b,
            model=memo_model,
            max_tokens=16_000,
            call_label="memo_writer",
        )
        logger.info("pipeline_call_b_complete")
    except Exception as exc:
        logger.error(
            "pipeline_call_b_failed",
            deal_id=str(deal_id),
            error=str(exc),
            exc_info=True,
        )
        structured_output["investment_memo"] = (
            "[Memo generation failed — structured intelligence available. "
            f"Error: {exc}]"
        )
        structured_output["confidence_score"] = 0.0
        memo_output = None

    # ── Merge memo into structured output ─────────────────────────
    if memo_output:
        is_valid_b, issues_b = _validate_memo(memo_output)
        if not is_valid_b:
            logger.warning(
                "pipeline_memo_issues",
                deal_id=str(deal_id),
                issues="; ".join(issues_b),
            )
        structured_output["investment_memo"] = memo_output.get(
            "investment_memo", "",
        )
        structured_output["memo_word_count"] = memo_output.get(
            "memo_word_count", 0,
        )
        structured_output["confidence_score"] = memo_output.get(
            "confidence_score", 0.5,
        )
        structured_output["confidence_rationale"] = memo_output.get(
            "confidence_rationale", "",
        )
        if memo_output.get("_meta"):
            structured_output["_meta_memo"] = memo_output["_meta"]

    # ── Attach curation metadata for evidence pack ────────────────
    structured_output["_curation_metadata"] = curation_metadata
    structured_output["_audit_surface_count"] = len(raw_audit_chunks)

    # ── Adjust confidence for missing critical documents ──────────
    critical_missing = sum(
        1 for d in enriched_missing if d.get("priority") == "critical"
    )
    if critical_missing > 0:
        base_conf = structured_output.get("confidence_score", 0.5)
        penalty = min(critical_missing * 0.1, 0.4)
        adjusted = max(round(base_conf - penalty, 2), 0.05)
        structured_output["confidence_score"] = adjusted
        structured_output["confidence_adjustment"] = (
            f"Reduced by {penalty:.0%} due to "
            f"{critical_missing} missing critical documents"
        )
        logger.info(
            "pipeline_confidence_adjusted",
            deal_id=str(deal_id),
            base=base_conf,
            adjusted=adjusted,
            missing_critical=critical_missing,
        )

    # ── Persist atomically ────────────────────────────────────────
    try:
        with db.begin_nested():
            _write_research_output(
                db, deal_id, structured_output, auto_commit=False,
            )
            now = datetime.now(UTC)
            _set_intelligence_status(
                db, deal_id, STATUS_READY,
                generated_at=now, auto_commit=False,
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "pipeline_persist_failed",
            deal_id=str(deal_id),
            exc_info=True,
        )
        _set_intelligence_status(db, deal_id, STATUS_FAILED)
        return {}

    # ── Derived field writeback (best-effort) ─────────────────────
    if fund_id is not None:
        try:
            _write_derived_fields(
                db, deal_id=deal_id, fund_id=fund_id,
                output=structured_output,
            )
        except Exception:
            logger.warning(
                "derived_field_writeback_failed",
                deal_id=str(deal_id),
                exc_info=True,
            )

    elapsed = time.perf_counter() - t0
    citations_used = len(structured_output.get("citations", []))
    memo_chars = len(structured_output.get("investment_memo", ""))
    confidence = structured_output.get("confidence_score", 0)
    risk_count = len(
        structured_output.get("risk_map", {}).get("key_risks", [])
        if isinstance(structured_output.get("risk_map"), dict)
        else structured_output.get("risk_map", []),
    )

    logger.info(
        "pipeline_intel_complete",
        deal_id=str(deal_id),
        elapsed=f"{elapsed:.1f}s",
        chunks=chunk_count,
        citations=citations_used,
        risks=risk_count,
        missing_docs=len(enriched_missing),
        memo_chars=memo_chars,
        confidence=confidence,
        valid_structured=is_valid_a,
    )
    return structured_output


# Backward-compatible alias
generate_structured_intelligence = generate_pipeline_intelligence


def generate_all_pending(
    db: Session,
    *,
    force: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Generate pipeline intelligence for all PENDING pipeline deals."""
    from app.domains.credit.modules.deals.models import PipelineDeal

    stmt = select(PipelineDeal).where(
        text(
            "intelligence_status::text IN ('PENDING', 'FAILED')",
        ),
    )
    if not force:
        stmt = stmt.where(
            PipelineDeal.research_output.is_(None)
            | text("intelligence_status::text != 'READY'"),
        )
    stmt = stmt.limit(limit)

    deals = list(db.execute(stmt).scalars().all())
    logger.info("pipeline_batch_start", pending_deals=len(deals))

    results: dict[str, Any] = {
        "total": len(deals),
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }

    deal_snapshots = [
        {
            "id": deal.id,
            "deal_name": deal.deal_name or deal.title,
            "sponsor_name": deal.sponsor_name or deal.borrower_name,
            "fund_id": deal.fund_id,
            "title": deal.title,
        }
        for deal in deals
    ]

    def _process_deal(snap: dict) -> dict:
        """Process a single deal with its own DB session (thread-safe)."""
        thread_db = async_session_factory()
        try:
            output = generate_pipeline_intelligence(
                thread_db,
                deal_id=snap["id"],
                deal_name=snap["deal_name"],
                sponsor_name=snap["sponsor_name"],
                fund_id=snap["fund_id"],
                force=force,
            )
            if output:
                return {"deal_id": str(snap["id"]), "name": snap["title"], "status": "OK"}
            return {"deal_id": str(snap["id"]), "name": snap["title"], "status": "SKIPPED"}
        except Exception as exc:
            logger.error(
                "pipeline_intelligence_failed",
                deal_id=str(snap["id"]),
                error=str(exc),
                exc_info=True,
            )
            return {"deal_id": str(snap["id"]), "name": snap["title"], "status": f"ERROR: {exc}"}
        finally:
            thread_db.close()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_process_deal, snap): snap
            for snap in deal_snapshots
        }
        for future in as_completed(futures):
            detail = future.result()
            results["details"].append(detail)
            if detail["status"] == "OK":
                results["succeeded"] += 1
            elif detail["status"] == "SKIPPED":
                results["skipped"] += 1
            else:
                results["failed"] += 1

    logger.info(
        "pipeline_batch_complete",
        total=results["total"],
        succeeded=results["succeeded"],
        failed=results["failed"],
        skipped=results["skipped"],
    )
    return results
