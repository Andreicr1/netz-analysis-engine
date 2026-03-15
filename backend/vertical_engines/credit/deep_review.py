"""AI Deep Review Service — Tier-1 Institutional Memorandum OS.

V4 Pipeline (13-Chapter Memo Book):
  1. RAG context extraction (sectional budgeting + evidence map)
  2. Structured deal analysis (extraction prompt)
  2.5. Macro context injection (FRED Market Data Engine — deterministic)
  3. Quant engine injection (ic_quant_engine — deterministic)
  4. Concentration engine injection (concentration_engine — deterministic)
  5. Policy compliance search (fund-level policy RAG)
  6. Decision Anchor computation (deterministic gate)
  7. 13-chapter IM generation (chapter-by-chapter with curated evidence surfaces)
  8. Critic loop (critic/ — adversarial, rewrite if fatal flaws)
  9. Atomic versioned persist (no delete of old drafts, chart-ready metadata)

Also provides:
  • Portfolio periodic reviews (``run_portfolio_review``)
  • Current IM draft retrieval (``get_current_im_draft``)

Safety invariants:
  • Validate-before-persist (no delete-first pattern)
  • Sectional token budgeting (40/30/30 split)
  • Evidence map tracking per context chunk
  • Atomic transaction control (no manual commit/rollback inside functions)
  • Fail-safe JSON validation with structured logging
  • Batch runner session isolation

Note: V3 (9-stage pipeline) was deprecated and removed.  All entry points
now use the V4 13-chapter architecture exclusively.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import uuid
from collections.abc import Awaitable
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from ai_engine.governance.token_budget import TokenBudgetTracker

# Cost Governance — multi-model routing + token budget
from ai_engine.model_config import get_model  # single source of truth for model routing
from ai_engine.prompts import prompt_registry
from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    DealICBrief,
    DealIntelligenceProfile,
    DealRiskFlag,
    InvestmentMemorandumDraft,
    PeriodicReviewReport,
)
from app.domains.credit.modules.deals.models import PipelineDeal as Deal  # pipeline domain
from vertical_engines.credit.deep_review_corpus import (
    _gather_deal_texts,
    _gather_investment_texts,
    _load_deal_context_from_blob,
)

# ---------------------------------------------------------------------------
# Import from split modules
# ---------------------------------------------------------------------------
from vertical_engines.credit.deep_review_helpers import (
    _MODEL,
    _async_call_openai,
    _call_openai,
    _now_utc,
    _title_case_strategy,
    _trunc,
)
from vertical_engines.credit.deep_review_policy import (
    _compute_confidence_score,
    _compute_decision_anchor,
    _gather_policy_context,
    _run_hard_policy_checks,
    _run_policy_compliance,
)
from vertical_engines.credit.deep_review_prompts import (
    _build_deal_review_prompt_v2,
    _pre_classify_from_corpus,
)

logger = logging.getLogger(__name__)

_LLM_CONCURRENCY = max(1, int(os.getenv("NETZ_LLM_CONCURRENCY", "5")))


# ---------------------------------------------------------------------------
# Eval artifact helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Public API: Current IM Draft query
# ---------------------------------------------------------------------------
def get_current_im_draft(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> InvestmentMemorandumDraft | None:
    """Return the current (is_current=True) IM draft for a deal.

    Fallback: if no draft has is_current=True (legacy data), return the
    latest by generated_at.  Returns None if no drafts exist.
    """
    # Primary: explicit current pointer
    current = db.execute(
        select(InvestmentMemorandumDraft).where(
            InvestmentMemorandumDraft.fund_id == fund_id,
            InvestmentMemorandumDraft.deal_id == deal_id,
            InvestmentMemorandumDraft.is_current == True,  # noqa: E712
        ),
    ).scalar_one_or_none()

    if current is not None:
        return current

    # Fallback: latest generated_at (for pre-migration rows)
    return db.execute(
        select(InvestmentMemorandumDraft)
        .where(
            InvestmentMemorandumDraft.fund_id == fund_id,
            InvestmentMemorandumDraft.deal_id == deal_id,
        )
        .order_by(InvestmentMemorandumDraft.generated_at.desc())
        .limit(1),
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public API: Portfolio periodic review
# ---------------------------------------------------------------------------
def run_portfolio_review(
    db: Session,
    *,
    fund_id: uuid.UUID,
    investment_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> dict[str, Any]:
    """Run a periodic AI review of an active investment."""
    now = _now_utc()
    investment = db.execute(
        select(ActiveInvestment).where(
            ActiveInvestment.id == investment_id,
            ActiveInvestment.fund_id == fund_id,
        ),
    ).scalar_one_or_none()
    if investment is None:
        return {"error": "Investment not found"}

    corpus = _gather_investment_texts(db, fund_id=fund_id, investment=investment)
    if not corpus.strip():
        return {"error": "No readable documents found for this investment"}

    system_prompt = prompt_registry.render("intelligence/portfolio_review.j2")
    review = _call_openai(system_prompt, corpus)

    report = PeriodicReviewReport(
        fund_id=fund_id,
        investment_id=investment_id,
        review_type="PERIODIC",
        overall_rating=review.get("overallRating", "AMBER"),
        executive_summary=review.get("executiveSummary", "Review pending."),
        performance_assessment=review.get("performanceAssessment", ""),
        covenant_compliance=review.get("covenantCompliance", ""),
        material_changes=review.get("materialChanges", []),
        risk_evolution=review.get("riskEvolution", ""),
        liquidity_assessment=review.get("liquidityAssessment", ""),
        valuation_view=review.get("valuationView", ""),
        recommended_actions=review.get("recommendedActions", []),
        reviewed_at=now,
        model_version=_MODEL,
        created_by=actor_id,
        updated_by=actor_id,
    )
    with db.begin_nested():
        db.add(report)

    # No db.commit() — caller manages transaction boundary.

    return {
        "investmentId": str(investment_id),
        "investmentName": investment.investment_name,
        "overallRating": report.overall_rating,
        "asOf": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Public API: Batch periodic review for all active investments
# ---------------------------------------------------------------------------
def run_all_portfolio_reviews(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> dict[str, Any]:
    """Run periodic review for every active investment.

    Pre-V3 Hardening (Task 9): Each investment gets its own DB session.
    """

    investments = list(
        db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id))
        .scalars()
        .all(),
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    SessionLocal = async_session_factory
    results = []

    def _review_investment(inv):
        try:
            with SessionLocal() as session:
                result = run_portfolio_review(
                    session,
                    fund_id=fund_id,
                    investment_id=inv.id,
                    actor_id=actor_id,
                )
                if "error" not in result:
                    session.commit()
                return result
        except Exception as exc:
            logger.warning("Portfolio review failed for %s: %s", inv.id, exc)
            return {"investmentId": str(inv.id), "error": str(exc)}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_review_investment, inv): inv for inv in investments}
        for future in as_completed(futures):
            results.append(future.result())

    return {
        "asOf": _now_utc().isoformat(),
        "totalInvestments": len(investments),
        "reviewed": len([r for r in results if "error" not in r]),
        "errors": len([r for r in results if "error" in r]),
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════════════════
# DEEP REVIEW V4 — Tier-1 Institutional Memorandum OS
# ═══════════════════════════════════════════════════════════════════════════
#
# 13-stage pipeline:
#   1.  Deal lookup & validation
#   2.  RAG context extraction (reuses V3 _gather_deal_texts)
#   3.  Structured deal analysis (reuses V3 Stage 2)
#   4.  Macro context injection (FRED Market Data Engine — deterministic)
#   5.  Quant engine injection (deterministic)
#   6.  Concentration engine injection (deterministic)
#   7.  Hard policy checks (deterministic)
#   8.  Policy compliance assessment (LLM)
#   9.  Sponsor & Key Person engine (LLM)
#   10. Evidence Pack generation (freeze the truth surface)
#   11. IC Critic loop (adversarial review on the evidence pack)
#   12. 13-Chapter Memo Book generation (per-chapter bounded context)
#   13. Atomic versioned persist (evidence pack + chapters + metadata)
#
# V3 is completely untouched.  V4 is additive.
# ═══════════════════════════════════════════════════════════════════════════


def run_deal_deep_review_v4(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    actor_id: str = "ai-engine",
    force: bool = False,
    full_mode: bool = False,
) -> dict[str, Any]:
    """Deep AI review V4 — 13-chapter institutional memorandum pipeline.

    Parameters
    ----------
    full_mode : bool
        When ``True``, unlocks higher token ceilings for all LLM stages.
        Standard mode keeps conservative limits for cost control.

    Returns a summary dict.  Raises on LLM/validation failure.
    No manual commit — caller manages transaction boundary.

    """
    from ai_engine.governance.artifact_cache import (
        artifact_exists_v4,
        load_cached_artifact_v4,
    )
    from ai_engine.portfolio.concentration_engine import compute_concentration
    from vertical_engines.credit.critic import critique_intelligence
    from vertical_engines.credit.edgar import (
        build_edgar_multi_entity_context,
        extract_searchable_entities,
        fetch_edgar_multi_entity,
    )
    from vertical_engines.credit.memo_book_generator import generate_memo_book
    from vertical_engines.credit.memo_evidence_pack import (
        build_evidence_pack,
        persist_evidence_pack,
        validate_evidence_pack,
    )
    from vertical_engines.credit.quant import compute_quant_profile
    from vertical_engines.credit.sponsor import analyze_sponsor

    now = _now_utc()
    budget = TokenBudgetTracker(context="deep_review_v4")

    # ── Token ceilings — full_mode unlocks higher limits ─────────
    max_tokens_structured = 6000 if full_mode else 4000
    max_tokens_sponsor = 8000 if full_mode else 6000
    max_tokens_memo = 10000 if full_mode else 6000
    max_tokens_critic = 10000 if full_mode else 8000
    max_tokens_escalation = 16000 if full_mode else 12000

    if full_mode:
        logger.info("V4_FULL_MODE_ENABLED deal_id=%s", deal_id)

    # ── Stage 1: Cache check ─────────────────────────────────────
    if not force and artifact_exists_v4(db, deal_id=deal_id):
        cached = load_cached_artifact_v4(db, deal_id=deal_id, fund_id=fund_id)
        if cached and cached.get("chaptersCompleted", 0) >= 13:
            logger.info("V4_CACHE_HIT deal_id=%s — returning cached result", deal_id)
            return cached

    # ── Stage 1b: Deal lookup ────────────────────────────────────
    deal = db.execute(
        select(Deal).where(Deal.id == deal_id, Deal.fund_id == fund_id),
    ).scalar_one_or_none()
    if deal is None:
        return {"error": "Deal not found", "dealId": str(deal_id)}

    deal_fields = {
        "deal_name": deal.deal_name or getattr(deal, "title", ""),
        "sponsor_name": getattr(deal, "sponsor_name", None) or "",
        "borrower_name": getattr(deal, "borrower_name", None) or "",
        "currency": getattr(deal, "currency", "USD") or "USD",
        "requested_amount": getattr(deal, "requested_amount", None),
        "stage": getattr(deal, "stage", None),
    }

    # ── Enrich deal_fields with blob-stored deal/fund context ──────
    deal_context_blob = _load_deal_context_from_blob(deal, deal_fields)

    version_tag = f"v4-{now.strftime('%Y%m%dT%H%M%S')}"
    logger.info("V4_START deal_id=%s version=%s", deal_id, version_tag)

    # ── Stage 2: IC-Grade retrieval (per-chapter specialized) ──────
    context = _gather_deal_texts(db, fund_id=fund_id, deal=deal)
    corpus = context["corpus_text"]
    evidence_map = context["evidence_map"]
    evidence_chunks = context.get("raw_chunks", [])
    retrieval_audit = context.get("retrieval_audit", {})
    saturation_report = context.get("saturation_report", {})
    chapter_evidence = context.get("chapter_evidence", {})

    if not corpus or len(corpus.strip()) < 200:
        return {
            "error": "Insufficient document corpus for V4 review",
            "dealId": str(deal_id),
            "corpusLength": len(corpus) if corpus else 0,
        }

    # ── Stage 3: Structured deal analysis ────────────────────────
    model_structured = get_model("structured")
    pre_instrument_type = _pre_classify_from_corpus(corpus, deal_fields)
    deal_review_prompt = _build_deal_review_prompt_v2(
        pre_instrument_type,
        deal_role_map=deal_fields.get("deal_role_map"),
        third_party_counterparties=deal_fields.get("third_party_counterparties"),
    )
    logger.info("V4_PRE_CLASSIFIED deal_id=%s type=%s", deal_id, pre_instrument_type)
    analysis = _call_openai(
        deal_review_prompt,
        corpus,
        max_tokens=max_tokens_structured,
        model=model_structured,
        budget=budget,
        label="v4_stage3_analysis",
    )

    # ── Stage 4: Macro context injection (deterministic) ─────────
    from vertical_engines.credit.market_data import (
        compute_macro_stress_severity,
        get_macro_snapshot,
    )

    deal_geography = (
        deal_fields.get("property_location")
        or deal_fields.get("geography")
        or deal_fields.get("collateral_location")
    )
    macro_snapshot = get_macro_snapshot(db, deal_geography=deal_geography)
    macro_stress = compute_macro_stress_severity(macro_snapshot)
    macro_stress_flag = macro_stress["level"] in ("MODERATE", "SEVERE")

    # ── Stage 4.3: Market Benchmark Retrieval (market-data-index) ──
    from ai_engine.governance.policy_loader import (
        SEARCH_API_KEY as _SEARCH_API_KEY,
    )
    from ai_engine.governance.policy_loader import (
        SEARCH_ENDPOINT as _SEARCH_ENDPOINT,
    )
    from vertical_engines.credit.retrieval import retrieve_market_benchmarks

    _market_benchmarks: list[dict] = []
    _mb_chapters = ("ch03_exit", "ch08_returns", "ch09_downside", "ch12_peers")

    def _fetch_benchmarks(chapter: str) -> list[dict]:
        try:
            return retrieve_market_benchmarks(
                chapter,
                search_endpoint=_SEARCH_ENDPOINT,
                search_api_key=_SEARCH_API_KEY,
                top_k=12,
            )
        except Exception as _mb_exc:
            logger.warning(
                "V4_MARKET_BENCHMARKS_WARN chapter=%s error=%s",
                chapter,
                _mb_exc,
            )
            return []

    from concurrent.futures import ThreadPoolExecutor as _TPE
    with _TPE(max_workers=4) as _mb_pool:
        for _chunks in _mb_pool.map(_fetch_benchmarks, _mb_chapters):
            _market_benchmarks.extend(_chunks)
    logger.info(
        "V4_MARKET_BENCHMARKS_RETRIEVED deal_id=%s total_chunks=%d",
        deal_id,
        len(_market_benchmarks),
    )

    # ── Stage 4.5: Instrument classification (deterministic) ────
    from vertical_engines.credit.critic import classify_instrument_type

    instrument_type = classify_instrument_type(analysis)
    logger.info(
        "V4_INSTRUMENT_CLASSIFIED deal_id=%s type=%s",
        deal_id,
        instrument_type,
    )

    # ── Stage 4.7: EDGAR public filing data (multi-entity) ──────
    logger.info("V4_STAGE_4_7_EDGAR_START", extra={"deal_id": str(deal_id)})
    edgar_context: str = ""
    # Extract targetVehicle from analysis for smart attribution
    _target_vehicle = ""
    if isinstance(analysis, dict):
        _tv = analysis.get("targetVehicle")
        if (
            _tv
            and isinstance(_tv, str)
            and _tv.strip().lower()
            not in (
                "",
                "pending diligence",
                "n/a",
                "not specified",
                "unknown",
            )
        ):
            _target_vehicle = _tv.strip()
    try:
        edgar_entities = extract_searchable_entities(
            deal_fields,
            analysis,
            ticker=getattr(deal, "ticker", None) or None,
            instrument_type=instrument_type,
        )
        edgar_multi = fetch_edgar_multi_entity(
            edgar_entities,
            instrument_type=instrument_type,
        )
        edgar_context = build_edgar_multi_entity_context(
            edgar_multi,
            deal_name=deal_fields.get("deal_name", ""),
            target_vehicle=_target_vehicle,
        )
        logger.info(
            "V4_STAGE_4_7_EDGAR_COMPLETE",
            extra={
                "deal_id": str(deal_id),
                "entities_tried": edgar_multi["entities_tried"],
                "entities_found": edgar_multi["entities_found"],
                "unique_ciks": edgar_multi["unique_ciks"],
                "context_chars": len(edgar_context),
            },
        )
    except Exception as exc:
        logger.warning(
            "V4_STAGE_4_7_EDGAR_FAILED",
            extra={"deal_id": str(deal_id), "error": str(exc)},
            exc_info=True,
        )
        # Non-fatal: pipeline continues without EDGAR context

    # ── Stage 5→6: Concentration engine first (quant may use it) ──
    from ai_engine.governance.policy_loader import load_policy_thresholds as _load_policy

    policy = _load_policy()
    pending = {
        "deal_name": deal_fields["deal_name"],
        "currency": deal_fields["currency"],
        "requested_amount": deal_fields["requested_amount"],
    }
    concentration_profile = compute_concentration(
        db,
        fund_id=fund_id,
        include_pending_deal=pending,
        policy=policy,
    )
    concentration_dict = concentration_profile.to_dict()

    # ── Stage 5: Quant engine (deterministic) ────────────────────
    quant_profile = compute_quant_profile(
        analysis,
        deal_fields=deal_fields,
        macro_snapshot=macro_snapshot,  # from Stage 4 above
        concentration_profile=concentration_dict,
    )
    quant_dict = quant_profile.to_dict()

    # ── Stage 7: Hard policy checks (deterministic) ──────────────
    hard_check_results = _run_hard_policy_checks(
        concentration_dict=concentration_dict,
        analysis=analysis,
        deal_fields=deal_fields,
        policy=policy,
    )

    # ── Stage 8: Policy compliance (LLM) ─────────────────────────
    policy_text = _gather_policy_context(
        fund_id,
        deal_fields["deal_name"],
        deal_folder_path=deal.deal_folder_path,
    )
    policy_dict = _run_policy_compliance(
        corpus,
        policy_text,
        analysis,
        hard_check_results=hard_check_results,
    )

    # ── Stage 9: Sponsor & Key Person engine (LLM) ───────────────
    model_sponsor = get_model("sponsor")

    def _sponsor_call_openai(
        system: str, user: str, *, max_tokens: int = max_tokens_sponsor,
    ):
        return _call_openai(
            system,
            user,
            max_tokens=max_tokens,
            model=model_sponsor,
            budget=budget,
            label="v4_stage9_sponsor",
        )

    # ── Extract key persons from index + build sponsor-specific corpus
    # The per-chapter retrieval (ch04_sponsor) already gathered the most
    # relevant management bios, org charts, and governance chunks.
    # Build a dedicated sponsor corpus from ch04 evidence to avoid the
    # generic corpus truncation that loses management team pages.
    index_key_persons: list[str] = []
    sponsor_evidence_text: str | None = None
    ch04_data = chapter_evidence.get("ch04_sponsor")
    if ch04_data and ch04_data.get("chunks"):
        # Collect key_persons_mentioned from ALL evidence chunks
        _seen_kp: set[str] = set()
        for chunk in evidence_chunks:
            for kp in chunk.get("key_persons_mentioned", []):
                kp_clean = kp.strip()
                if kp_clean and kp_clean.lower() not in _seen_kp:
                    _seen_kp.add(kp_clean.lower())
                    index_key_persons.append(kp_clean)
        # Build sponsor-specific corpus from ch04 chunks (already ranked)
        ch04_chunks = ch04_data["chunks"]
        ch04_parts: list[str] = []
        for chunk in ch04_chunks:
            content = chunk.get("content", "")
            if content:
                blob = chunk.get("blob_name", chunk.get("title", ""))
                header = f"--- [{blob}] doc_type={chunk.get('doc_type', '?')} ---"
                ch04_parts.append(f"{header}\n{content}")
        sponsor_evidence_text = "\n\n".join(ch04_parts) if ch04_parts else None
        logger.info(
            "V4_SPONSOR_EVIDENCE_BUILT",
            extra={
                "ch04_chunks": len(ch04_chunks),
                "index_key_persons": len(index_key_persons),
                "sponsor_evidence_chars": len(sponsor_evidence_text)
                if sponsor_evidence_text
                else 0,
            },
        )

    sponsor_output = analyze_sponsor(
        corpus=corpus,
        deal_fields=deal_fields,
        analysis=analysis,
        call_openai_fn=_sponsor_call_openai,
        index_key_persons=index_key_persons if index_key_persons else None,
        sponsor_evidence_text=sponsor_evidence_text,
    )

    # ── Stage 9.5: KYC Spider Pipeline Screening ─────────────────
    # Automatically screen all key persons and organisations identified
    # in the deal documentation via KYC Spider API (PEP/Sanctions/AML).
    from vertical_engines.credit.kyc import (
        build_kyc_appendix,
        persist_kyc_screenings_to_db,
        run_kyc_screenings,
    )

    kyc_results: dict[str, Any] = {}
    kyc_appendix_text: str = ""
    try:
        kyc_results = run_kyc_screenings(
            analysis=analysis,
            deal_fields=deal_fields,
            index_key_persons=index_key_persons,
            sponsor_output=sponsor_output,
        )
        kyc_appendix_text = build_kyc_appendix(
            kyc_results,
            deal_name=deal_fields.get("deal_name", ""),
        )

        # Persist KYC screenings to DB (non-blocking)
        if kyc_results.get("summary", {}).get("skipped") is not True:
            try:
                persist_kyc_screenings_to_db(
                    db,
                    fund_id=fund_id,
                    deal_id=deal_id,
                    kyc_results=kyc_results,
                    actor_id=actor_id,
                )
            except Exception as _kyc_db_exc:
                logger.warning(
                    "KYC_PIPELINE_DB_PERSIST_FAILED deal_id=%s error=%s",
                    deal_id,
                    _kyc_db_exc,
                )

        logger.info(
            "V4_KYC_SCREENING_COMPLETE deal_id=%s persons=%d orgs=%d matches=%d",
            deal_id,
            kyc_results.get("summary", {}).get("total_persons_screened", 0),
            kyc_results.get("summary", {}).get("total_orgs_screened", 0),
            kyc_results.get("summary", {}).get("total_matches", 0),
        )
    except Exception as _kyc_exc:
        logger.warning(
            "V4_KYC_SCREENING_FAILED deal_id=%s error=%s — continuing without KYC appendix",
            deal_id,
            _kyc_exc,
        )

    # ── Stage 10: Build & freeze EvidencePack (≤ 5 000 tokens) ───
    evidence_pack = build_evidence_pack(
        analysis=analysis,
        quant_dict=quant_dict,
        concentration_dict=concentration_dict,
        policy_dict=policy_dict,
        macro_snapshot=macro_snapshot,
        sponsor_output=sponsor_output,
        deal_fields=deal_fields,
        evidence_map=evidence_map,
        market_benchmarks=_market_benchmarks,
    )
    try:
        validate_evidence_pack(evidence_pack)
    except ValueError as exc:
        logger.error("V4_EVIDENCE_PACK_INVALID errors=%s", exc)
        return {
            "error": "EvidencePack validation failed",
            "dealId": str(deal_id),
            "validationErrors": [str(exc)],
        }

    # Inject EDGAR context into evidence pack (flows to all chapters)
    if edgar_context.strip():
        evidence_pack["edgar_public_filings"] = edgar_context
        logger.info(
            "V4_EDGAR_INJECTED_INTO_PACK",
            extra={"deal_id": str(deal_id), "chars": len(edgar_context)},
        )

    # Inject deal_context (vehicles, investment terms, fund strategy, entity tree)
    if deal_context_blob:
        evidence_pack["deal_context"] = deal_context_blob
        logger.info(
            "V4_DEAL_CONTEXT_INJECTED_INTO_PACK",
            extra={"deal_id": str(deal_id), "keys": list(deal_context_blob.keys())},
        )

    model_evidence = get_model("evidence_pack")
    pack_row = persist_evidence_pack(
        db,
        fund_id=fund_id,
        deal_id=deal_id,
        pack=evidence_pack,
        version_tag=version_tag,
        model_version=model_evidence,
        actor_id=actor_id,
    )
    evidence_pack_id = pack_row.id
    logger.info(
        "V4_EVIDENCE_PACK_FROZEN deal_id=%s pack_id=%s tokens=%d",
        deal_id,
        evidence_pack_id,
        pack_row.token_count,
    )

    # ── Stage 11: IC Critic (adversarial review) ─────────────────
    model_critic = get_model("critic")

    critic_context = {
        "structured_analysis": analysis,
        "ic_brief": {},  # V4 does not generate IC Brief separately
        "full_memo": "",  # critic runs BEFORE memo in V4
        "quant_profile": quant_dict,
        "concentration_profile": concentration_dict,
        "policy_compliance": policy_dict,
        "deal_fields": deal_fields,
        "macro_snapshot": macro_snapshot,
        "macro_stress_flag": macro_stress_flag,
        "instrument_type": instrument_type,
    }

    def _critic_call_openai(
        system: str, user: str, *, max_tokens: int = max_tokens_critic,
    ):
        return _call_openai(
            system,
            user,
            max_tokens=max_tokens,
            model=model_critic,
            budget=budget,
            label="v4_stage11_critic",
        )

    critic_verdict = critique_intelligence(
        critic_context,
        call_openai_fn=_critic_call_openai,
    )
    critic_dict = critic_verdict.to_dict()
    critic_dict_default = critic_dict  # preserve for audit trail

    # ── Critic escalation — rerun with o3 on low confidence ──────
    critic_escalated = False
    critic_dict_escalation: dict[str, Any] | None = None
    _conf = critic_dict.get("confidence_score", 1.0)
    _fatal = critic_dict.get("fatal_flaws", [])
    _rewrite = critic_dict.get("rewrite_required", False)

    if _conf < 0.75 or _fatal or _rewrite:
        logger.warning(
            "V4_CRITIC_ESCALATION deal_id=%s confidence=%.2f fatal_flaws=%d rewrite=%s",
            deal_id,
            _conf,
            len(_fatal),
            _rewrite,
        )
        model_critic_esc = get_model("critic_escalation")

        def _critic_esc_call_openai(
            system: str, user: str, *, max_tokens: int = max_tokens_escalation,
        ):
            return _call_openai(
                system,
                user,
                max_tokens=max_tokens,
                model=model_critic_esc,
                budget=budget,
                label="v4_stage11_critic_escalation",
                stage="critic_escalation",
            )

        critic_verdict_esc = critique_intelligence(
            critic_context,
            call_openai_fn=_critic_esc_call_openai,
        )
        critic_dict_escalation = critic_verdict_esc.to_dict()
        critic_dict = critic_dict_escalation  # promote escalated as authoritative
        critic_escalated = True
        logger.info(
            "V4_CRITIC_ESCALATION_COMPLETE deal_id=%s "
            "default_confidence=%.2f escalated_confidence=%.2f",
            deal_id,
            critic_dict_default.get("confidence_score", 0),
            critic_dict.get("confidence_score", 0),
        )

    # Inject critic output into the evidence pack for Chapter 13
    # Structure: top-level = authoritative (final) verdict.
    #   default_verdict  — always present (gpt-4.1 first pass)
    #   escalation_verdict — only present when escalation fired (o3 second pass)
    #   escalated flag   — boolean for quick downstream branching
    evidence_pack["critic_output"] = {
        # ── Authoritative (final) verdict ──────────────────────────
        "confidence_score": critic_dict.get("confidence_score"),
        "fatal_flaws": critic_dict.get("fatal_flaws", []),
        "material_gaps": critic_dict.get("material_gaps", []),
        "rewrite_required": critic_dict.get("rewrite_required", False),
        # ── Audit trail ────────────────────────────────────────────
        "escalated": critic_escalated,
        "default_verdict": {
            "confidence_score": critic_dict_default.get("confidence_score"),
            "fatal_flaws": critic_dict_default.get("fatal_flaws", []),
            "material_gaps": critic_dict_default.get("material_gaps", []),
            "rewrite_required": critic_dict_default.get("rewrite_required", False),
        },
        "escalation_verdict": {
            "confidence_score": critic_dict_escalation.get("confidence_score"),
            "fatal_flaws": critic_dict_escalation.get("fatal_flaws", []),
            "material_gaps": critic_dict_escalation.get("material_gaps", []),
            "rewrite_required": critic_dict_escalation.get("rewrite_required", False),
        }
        if critic_dict_escalation is not None
        else None,
    }

    # ── Stage 11b: Decision Anchor (single authoritative verdict) ─
    decision_anchor = _compute_decision_anchor(
        hard_check_results=hard_check_results,
        policy_dict=policy_dict,
        critic_dict=critic_dict,
        concentration_dict=concentration_dict,
        quant_dict=quant_dict,
    )
    evidence_pack["decision_anchor"] = decision_anchor
    logger.info(
        "V4_DECISION_ANCHOR deal_id=%s decision=%s icGate=%s rationale=%s",
        deal_id,
        decision_anchor["finalDecision"],
        decision_anchor["icGate"],
        decision_anchor["decisionRationale"],
    )

    # ── Stage 12: 13-Chapter Memo Book generation ────────────────
    model_memo = get_model(
        "memo",
    )  # default chapter model (overridden per-chapter in memo_book_generator)

    def _memo_call_openai(
        system: str,
        user: str,
        *,
        max_tokens: int = max_tokens_memo,
        model: str | None = None,
    ):
        effective_model = model or model_memo
        return _call_openai(
            system,
            user,
            max_tokens=max_tokens,
            model=effective_model,
            budget=budget,
            label="v4_stage12_chapter",
            stage="memo",
        )

    memo_result = generate_memo_book(
        db=db,
        fund_id=fund_id,
        deal_id=deal_id,
        evidence_pack=evidence_pack,
        evidence_pack_id=evidence_pack_id,
        evidence_map=evidence_map,
        evidence_chunks=evidence_chunks,
        quant_dict=quant_dict,
        critic_findings=critic_dict,
        policy_dict=policy_dict,
        sponsor_output=sponsor_output,
        version_tag=version_tag,
        call_openai_fn=_memo_call_openai,
        model=model_memo,
        model_mini=get_model("memo_mini"),
        actor_id=actor_id,
        decision_anchor=decision_anchor,
        use_batch=os.getenv("NETZ_BATCH_MODE", "").lower() in ("1", "true", "yes"),
    )
    chapters = memo_result.get("chapters", [])
    full_memo_text = memo_result.get("fullMemo", "")
    chapter_texts = memo_result.get(
        "chapter_texts", {},
    )  # ch_tag → section_text for Tone Normalizer
    citations_used = memo_result.get("citations_used", [])
    chapter_citations = _index_chapter_citations(chapters, citations_used)
    unsupported_claims_detected = memo_result.get("unsupported_claims_detected", False)
    critical_gaps_all = memo_result.get("critical_gaps", [])

    # ── Append KYC checks appendix to full memo ─────────────────
    if kyc_appendix_text:
        full_memo_text = full_memo_text + "\n\n---\n\n" + kyc_appendix_text

    # ── Stage 12.5: Post-Memo Critic Review + Feedback Loop ───
    # Re-run critic with the full memo text so it can detect
    # narrative contradictions, unsupported claims, and gaps.
    # If rewrite_required, regenerate affected chapters (max 1 round).
    critic_context_post = {
        **critic_context,
        "full_memo": full_memo_text,
    }

    critic_post_verdict = critique_intelligence(
        critic_context_post,
        call_openai_fn=_critic_call_openai,
    )
    critic_post_dict = critic_post_verdict.to_dict()
    critic_rewrite_count = 0

    if critic_post_dict.get("rewrite_required") and chapter_texts:
        logger.warning(
            "V4_CRITIC_POST_MEMO_REWRITE deal_id=%s fatal_flaws=%d confidence=%.2f",
            deal_id,
            len(critic_post_dict.get("fatal_flaws", [])),
            critic_post_dict.get("confidence_score", 0),
        )
        affected_tags = set()
        for flaw in critic_post_dict.get("fatal_flaws", []):
            flaw_lower = str(flaw).lower()
            for ch_tag in chapter_texts:
                ch_short = ch_tag.replace("ch", "").split("_")[0]
                if ch_short in flaw_lower or ch_tag in flaw_lower:
                    affected_tags.add(ch_tag)
        for gap in critic_post_dict.get("material_gaps", []):
            gap_lower = str(gap).lower()
            for ch_tag in chapter_texts:
                ch_short = ch_tag.replace("ch", "").split("_")[0]
                if ch_short in gap_lower or ch_tag in gap_lower:
                    affected_tags.add(ch_tag)

        if not affected_tags:
            affected_tags = {"ch01_exec", "ch13_recommendation"}

        logger.info(
            "V4_CRITIC_REWRITE_CHAPTERS deal_id=%s chapters=%s",
            deal_id, sorted(affected_tags),
        )

        critic_addendum = (
            "CRITIC FINDINGS (address these issues):\n"
            + "\n".join(f"- FATAL: {f}" for f in critic_post_dict.get("fatal_flaws", []))
            + "\n".join(f"- GAP: {g}" for g in critic_post_dict.get("material_gaps", []))
        )

        for ch_tag in affected_tags:
            if ch_tag not in chapter_texts:
                continue
            try:
                from vertical_engines.credit.memo_chapter_engine import (
                    regenerate_chapter_with_critic,
                )

                new_text = regenerate_chapter_with_critic(
                    ch_tag=ch_tag,
                    original_text=chapter_texts[ch_tag],
                    critic_addendum=critic_addendum,
                    evidence_pack=evidence_pack,
                    call_openai_fn=_memo_call_openai,
                )
                if new_text:
                    chapter_texts[ch_tag] = new_text
                    for ch in chapters:
                        if ch.get("chapter_tag") == ch_tag:
                            ch["section_text"] = new_text
                    full_memo_text = "\n\n---\n\n".join(
                        chapter_texts[t] for t in sorted(chapter_texts)
                    )
                    critic_rewrite_count += 1
            except Exception:
                logger.exception("V4_CRITIC_REWRITE_FAILED ch=%s deal_id=%s", ch_tag, deal_id)

        critic_dict = critic_post_dict
        evidence_pack["critic_output"]["post_memo_review"] = critic_post_dict
        evidence_pack["critic_output"]["rewrite_count"] = critic_rewrite_count
        logger.info(
            "V4_CRITIC_REWRITE_COMPLETE deal_id=%s rewrote=%d chapters",
            deal_id, critic_rewrite_count,
        )
    elif critic_post_dict.get("fatal_flaws"):
        critic_dict = critic_post_dict
        evidence_pack["critic_output"]["post_memo_review"] = critic_post_dict

    # ── Stage 13: Underwriting Reliability Score (deterministic) ──
    # Computed BEFORE Tone Normalizer so narrative adjustments cannot
    # inflate the score.  Uses only structured artifacts.
    from vertical_engines.credit.deep_review_confidence import (
        apply_tone_normalizer_adjustment,
        compute_underwriting_confidence,
    )

    im_recommendation = memo_result.get("recommendation", "")

    # Build evidence_pack_meta for granular quality assessment
    _epm_chapter_counts: dict[str, dict] = {}
    for _ch_key, _ch_data in chapter_evidence.items():
        _ch_stats = _ch_data.get("stats", {}) if isinstance(_ch_data, dict) else {}
        _epm_chapter_counts[_ch_key] = {
            "unique_docs": _ch_stats.get("unique_docs", 0),
            "chunk_count": _ch_stats.get("chunk_count", 0),
        }

    _epm_terms = {}
    if isinstance(analysis, dict):
        _epm_terms = analysis.get("investmentTerms", {})
        if not isinstance(_epm_terms, dict):
            _epm_terms = {}

    evidence_pack_meta = {
        "chapter_counts": _epm_chapter_counts,
        "investment_terms": _epm_terms,
    }

    uw_confidence = compute_underwriting_confidence(
        retrieval_audit=retrieval_audit,
        saturation_report=saturation_report,
        hard_check_results=hard_check_results,
        concentration_profile=concentration_dict,
        critic_output=critic_dict,
        quant_profile=quant_dict,
        evidence_pack_meta=evidence_pack_meta,
    )
    confidence_score: int = uw_confidence["confidence_score"]
    confidence_level: str = uw_confidence["confidence_level"]
    confidence_breakdown: dict = uw_confidence["breakdown"]
    confidence_caps: list = uw_confidence["caps_applied"]
    pre_tone_confidence_score: int = confidence_score
    pre_tone_confidence_level: str = confidence_level
    pre_tone_confidence_breakdown: dict = dict(confidence_breakdown)
    pre_tone_confidence_caps: list = list(confidence_caps)

    # Legacy: keep ic_gate from decision_anchor for backward compat
    ic_gate: str = decision_anchor["icGate"]
    ic_gate_reasons: list = []
    if ic_gate == "BLOCKED" or ic_gate == "CONDITIONAL":
        ic_gate_reasons = [decision_anchor.get("decisionRationale", "")]

    # Backward-compat: compute legacy confidence (0.0–1.0 float)
    _legacy_conf = _compute_confidence_score(
        quant_dict=quant_dict,
        concentration_dict=concentration_dict,
        policy_dict=policy_dict,
        critic_dict=critic_dict,
        im_recommendation=im_recommendation,
    )
    final_confidence: float = _legacy_conf["final_confidence"]
    evidence_confidence: float = _legacy_conf["evidence_confidence"]

    logger.info(
        "V4_CONFIDENCE_COMPUTED deal_id=%s uw_score=%d uw_level=%s "
        "legacy_final=%.3f caps=%s",
        deal_id,
        confidence_score,
        confidence_level,
        final_confidence,
        confidence_caps,
    )

    token_summary = budget.summary()
    logger.info(
        "V4_COMPLETE deal_id=%s version=%s chapters=%d confidence=%.2f "
        "evidence_confidence=%.2f ic_gate=%s fatal_flaws=%d tokens=%s",
        deal_id,
        version_tag,
        len(chapters),
        final_confidence,
        evidence_confidence,
        ic_gate,
        len(critic_dict.get("fatal_flaws", [])),
        token_summary,
    )

    # ── Stage 4.5: Tone Normalizer ─────────────────────────────────
    # Runs after critic (Stage 11) and signal consolidation (Stage 13).
    # Normalises tone per-chapter (Pass 1) and cross-chapter (Pass 2).
    # May escalate im_recommendation — runs BEFORE artifact persist (Stage 13c)
    # so the escalated signal is committed to the authoritative artifact.
    tone_review_log: list = []
    tone_pass1_changes: dict = {}
    tone_pass2_changes: list = []
    _tone_signal_original: str = ""
    _tone_signal_final: str = ""
    pre_tone_chapter_texts = dict(chapter_texts)
    post_tone_chapter_texts = dict(chapter_texts)

    if chapter_texts:
        try:
            import asyncio as _asyncio
            from concurrent.futures import ThreadPoolExecutor as _ToneTPE

            from vertical_engines.credit.tone_normalizer import (
                run_tone_normalizer as _run_tone_normalizer,
            )

            logger.info(
                "TONE_NORMALIZER_START deal_id=%s chapters=%d signal=%s",
                deal_id,
                len(chapter_texts),
                im_recommendation,
            )

            _tone_coro = _run_tone_normalizer(
                chapter_texts=chapter_texts,
                critic_output=critic_dict,
                current_signal=im_recommendation,
            )

            try:
                _existing_loop = _asyncio.get_running_loop()
            except RuntimeError:
                _existing_loop = None

            if _existing_loop and _existing_loop.is_running():
                with _ToneTPE(max_workers=1) as _tone_pool:
                    tone_result = _tone_pool.submit(_asyncio.run, _tone_coro).result()
            else:
                tone_result = _asyncio.run(_tone_coro)

            # Update DB chapter records with normalised text
            if tone_result.get("chapters"):
                from sqlalchemy import update as _sa_update

                from app.domains.credit.modules.ai.models import MemoChapter as _MemoChapter

                for _ch_tag, _revised in tone_result["chapters"].items():
                    if _revised and _revised.strip():
                        db.execute(
                            _sa_update(_MemoChapter)
                            .where(
                                _MemoChapter.deal_id == deal_id,
                                _MemoChapter.version_tag == version_tag,
                                _MemoChapter.chapter_tag == _ch_tag,
                            )
                            .values(content_md=_revised),
                        )
                        post_tone_chapter_texts[_ch_tag] = _revised
                db.flush()
                logger.info(
                    "TONE_NORMALIZER_DB_UPDATED deal_id=%s chapters=%d",
                    deal_id,
                    len(tone_result["chapters"]),
                )

            # Signal escalation (may only go harder, never softer)
            if tone_result.get("signal_escalated"):
                _new_signal = tone_result.get("signal_final", im_recommendation)
                logger.warning(
                    "TONE_SIGNAL_ESCALATED deal_id=%s %s → %s | %s",
                    deal_id,
                    im_recommendation,
                    _new_signal,
                    tone_result.get("escalation_rationale", ""),
                )
                im_recommendation = _new_signal

            tone_review_log = tone_result.get("tone_review_log", [])
            tone_pass1_changes = tone_result.get("pass1_changes", {})
            tone_pass2_changes = tone_result.get("pass2_changes", [])
            _tone_signal_original = tone_result.get(
                "signal_original", im_recommendation,
            )
            _tone_signal_final = tone_result.get("signal_final", im_recommendation)

        except Exception as _tone_exc:
            logger.warning(
                "TONE_NORMALIZER_FAILED deal_id=%s error=%s — continuing without normalisation",
                deal_id,
                _tone_exc,
            )
    else:
        logger.debug(
            "TONE_NORMALIZER_SKIPPED deal_id=%s reason=no_chapter_texts", deal_id,
        )

    # ── Post-tone confidence adjustment (never increases score) ──
    uw_confidence = apply_tone_normalizer_adjustment(
        uw_confidence,
        tone_signal_escalated=bool(
            tone_pass2_changes
            and any("escalat" in str(c).lower() for c in tone_pass2_changes),
        )
        if chapter_texts
        else False,
        tone_pass2_changes=tone_pass2_changes,
    )
    confidence_score = uw_confidence["confidence_score"]
    confidence_level = uw_confidence["confidence_level"]
    confidence_breakdown = uw_confidence["breakdown"]
    confidence_caps = uw_confidence["caps_applied"]

    logger.info(
        "V4_CONFIDENCE_POST_TONE deal_id=%s uw_score=%d uw_level=%s caps=%s",
        deal_id,
        confidence_score,
        confidence_level,
        confidence_caps,
    )

    # ── Stage 13b: Persist final metadata into evidence pack row ──
    from app.domains.credit.modules.ai.models import MemoEvidencePack

    db.execute(
        update(MemoEvidencePack)
        .where(MemoEvidencePack.id == evidence_pack_id)
        .values(
            evidence_json={
                **pack_row.evidence_json,
                "citations": citations_used,
                "chapter_citations": chapter_citations,
                "critic_output": evidence_pack.get("critic_output", {}),
                "decision_anchor": decision_anchor,
                "final_confidence": final_confidence,
                "evidence_confidence": evidence_confidence,
                "confidence_score_pre_tone": pre_tone_confidence_score,
                "confidence_level_pre_tone": pre_tone_confidence_level,
                "confidence_breakdown_pre_tone": pre_tone_confidence_breakdown,
                "confidence_caps_applied_pre_tone": pre_tone_confidence_caps,
                "confidence_score": confidence_score,
                "confidence_level": confidence_level,
                "confidence_breakdown": confidence_breakdown,
                "confidence_caps_applied": confidence_caps,
                "ic_gate": ic_gate,
                "ic_gate_reasons": ic_gate_reasons,
                "instrument_type": instrument_type,
                "pipeline_version": "v4.4-ic-grade",
                "retrieval_policy": retrieval_audit.get(
                    "retrieval_policy", "IC_GRADE_V1",
                ),
                "stages_completed": 13,
                "chapter_count": len(chapters),
                "citation_governance": {
                    "citations_used": len(citations_used),
                    "unique_chunks": len(
                        {
                            c.get("chunk_id")
                            for c in citations_used
                            if c.get("chunk_id") != "NONE"
                        },
                    ),
                    "unsupported_claims_detected": unsupported_claims_detected,
                    "self_audit_pass": not unsupported_claims_detected,
                },
                "retrieval_audit": retrieval_audit,
                "saturation_report": saturation_report,
                "appendix_1_source_index": memo_result.get(
                    "appendix_1_source_index", "",
                ),
                "appendix_kyc_checks": kyc_appendix_text,
                "kyc_screening_summary": kyc_results.get("summary", {}),
                "tone_artifacts": _build_tone_artifacts(
                    pre_tone_chapters=pre_tone_chapter_texts,
                    post_tone_chapters=post_tone_chapter_texts,
                    tone_review_log=tone_review_log,
                    tone_pass1_changes=tone_pass1_changes,
                    tone_pass2_changes=tone_pass2_changes,
                    signal_original=_tone_signal_original,
                    signal_final=_tone_signal_final,
                ),
            },
        ),
    )

    # ── Stage 13c: Persist Unified Underwriting Artifact ─────────
    # This is the SINGLE authoritative IC truth object.  Pipeline Engine
    # must never write to this table.
    from vertical_engines.credit.underwriting_artifact import persist_underwriting_artifact

    persist_underwriting_artifact(
        db,
        fund_id=fund_id,
        deal_id=deal_id,
        evidence_pack=evidence_pack,
        evidence_pack_id=evidence_pack_id,
        im_recommendation=im_recommendation,
        final_confidence=final_confidence,
        analysis=analysis,
        critic_dict=critic_dict,
        policy_dict=policy_dict,
        chapters_completed=len(chapters),
        model_version=model_memo,
        generated_at=now,
        version_tag=version_tag,
        actor_id=actor_id,
        confidence_score=confidence_score,
        confidence_level=confidence_level,
        confidence_breakdown=confidence_breakdown,
        confidence_caps=confidence_caps,
        critical_gaps=critical_gaps_all,
    )
    logger.info(
        "V4_UNDERWRITING_ARTIFACT_PERSISTED deal_id=%s recommendation=%s",
        deal_id,
        im_recommendation,
    )

    # ── Stage 13d: Persist DealIntelligenceProfile + DealICBrief ──
    # V4 must populate these tables so the pipeline deal list endpoint
    # (GET /pipeline/deals) can show strategy_type, risk_band, and
    # recommendation_signal without requiring a separate V3 run.
    from vertical_engines.credit.underwriting_artifact import derive_risk_band as _derive_risk_band

    _v4_risk_band = _derive_risk_band(analysis)
    _v4_risk_band_label = {"HIGH": "HIGH", "MEDIUM": "MODERATE", "LOW": "LOW"}.get(
        _v4_risk_band, _v4_risk_band,
    )

    _v4_returns = analysis.get("expectedReturns", {})
    _v4_risks = analysis.get("riskFactors", [])
    if not isinstance(_v4_risks, list):
        _v4_risks = []

    _v4_profile_metadata = {
        "evidence_map": evidence_map,
        "quant_profile": quant_dict,
        "sensitivity_matrix": quant_dict.get("sensitivity_matrix", []),
        "concentration_profile": concentration_dict,
        "macro_snapshot": macro_snapshot,
        "macro_stress_flag": macro_stress_flag,
        "critic_output": critic_dict,
        "policy_compliance": policy_dict,
        "decision_anchor": decision_anchor,
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "confidence_breakdown": confidence_breakdown,
        "confidence_caps_applied": confidence_caps,
        "legacy_confidence_score": final_confidence,
        "evidence_confidence": evidence_confidence,
        "ic_gate": ic_gate,
        "ic_gate_reasons": ic_gate_reasons,
        "instrument_type": instrument_type,
        "pipeline_version": "v4",
        "token_budget": token_summary,
        "chapter_citations": chapter_citations,
        "tone_artifacts": _build_tone_artifacts(
            pre_tone_chapters=pre_tone_chapter_texts,
            post_tone_chapters=post_tone_chapter_texts,
            tone_review_log=tone_review_log,
            tone_pass1_changes=tone_pass1_changes,
            tone_pass2_changes=tone_pass2_changes,
            signal_original=_tone_signal_original,
            signal_final=_tone_signal_final,
        ),
        "tone_signal_original": _tone_signal_original,
        "tone_signal_final": _tone_signal_final,
    }

    _v4_profile = DealIntelligenceProfile(
        fund_id=fund_id,
        deal_id=deal_id,
        strategy_type=_title_case_strategy(
            _trunc(
                analysis.get("strategyType")
                or deal_fields.get("strategy_type")
                or "Private Credit",
                80,
            ),
        ),
        geography=_trunc(
            analysis.get("geography") or deal_fields.get("geography"), 120,
        ),
        sector_focus=_trunc(analysis.get("sectorFocus"), 160),
        target_return=_trunc(
            _v4_returns.get("targetIRR") or _v4_returns.get("couponRate"), 60,
        ),
        risk_band=_trunc(_v4_risk_band_label, 20),
        liquidity_profile=_trunc(analysis.get("liquidityProfile"), 80),
        capital_structure_type=_trunc(analysis.get("capitalStructurePosition"), 80),
        key_risks=[
            {
                "riskType": r.get("factor", ""),
                "severity": r.get("severity", "LOW"),
                "mitigation": r.get("mitigation", ""),
            }
            for r in _v4_risks
            if isinstance(r, dict)
        ],
        differentiators=analysis.get("keyDifferentiators", []),
        summary_ic_ready=analysis.get("executiveSummary", "AI review pending."),
        last_ai_refresh=now,
        metadata_json=_v4_profile_metadata,
        created_by=actor_id,
        updated_by=actor_id,
    )

    # Build IC brief from chapter texts or analysis
    _exec_summary = chapter_texts.get(
        "ch01_executive_summary", analysis.get("executiveSummary", ""),
    )
    _opp_overview = chapter_texts.get(
        "ch02_opportunity", analysis.get("opportunityOverview", ""),
    )
    _return_profile = chapter_texts.get(
        "ch08_returns", analysis.get("returnProfile", ""),
    )
    _downside_case = chapter_texts.get(
        "ch09_downside", analysis.get("downsideCase", ""),
    )
    _risk_summary = chapter_texts.get("ch10_risk", analysis.get("riskSummary", ""))
    _peer_compare = chapter_texts.get("ch12_peers", analysis.get("peerComparison", ""))
    _rec_signal = _trunc(
        (
            im_recommendation or decision_anchor.get("finalDecision", "CONDITIONAL")
        ).upper(),
        20,
    )

    _v4_brief = DealICBrief(
        fund_id=fund_id,
        deal_id=deal_id,
        executive_summary=_exec_summary or "See IC Memorandum.",
        opportunity_overview=_opp_overview or "See IC Memorandum.",
        return_profile=_return_profile or "See IC Memorandum.",
        downside_case=_downside_case or "See IC Memorandum.",
        risk_summary=_risk_summary or "See IC Memorandum.",
        comparison_peer_funds=_peer_compare or "See IC Memorandum.",
        recommendation_signal=_rec_signal,
        created_by=actor_id,
        updated_by=actor_id,
    )

    _v4_risk_flags = [
        DealRiskFlag(
            fund_id=fund_id,
            deal_id=deal_id,
            risk_type=_trunc(risk.get("factor", "UNKNOWN"), 40),
            severity=_trunc(risk.get("severity", "LOW"), 20),
            reasoning=f"{risk.get('factor', '')}: {risk.get('mitigation', 'No mitigation identified.')}",
            source_document=_trunc(deal.deal_folder_path, 800),
            created_by=actor_id,
            updated_by=actor_id,
        )
        for risk in _v4_risks
        if isinstance(risk, dict)
    ]

    with db.begin_nested():
        db.execute(
            delete(DealIntelligenceProfile).where(
                DealIntelligenceProfile.fund_id == fund_id,
                DealIntelligenceProfile.deal_id == deal_id,
            ),
        )
        db.execute(
            delete(DealRiskFlag).where(
                DealRiskFlag.fund_id == fund_id,
                DealRiskFlag.deal_id == deal_id,
            ),
        )
        db.execute(
            delete(DealICBrief).where(
                DealICBrief.fund_id == fund_id,
                DealICBrief.deal_id == deal_id,
            ),
        )
        db.flush()
        db.add(_v4_profile)
        for _flag in _v4_risk_flags:
            db.add(_flag)
        db.add(_v4_brief)

    logger.info(
        "V4_PROFILE_BRIEF_PERSISTED deal_id=%s strategy=%s risk_band=%s signal=%s flags=%d",
        deal_id,
        _v4_profile.strategy_type,
        _v4_risk_band_label,
        _rec_signal,
        len(_v4_risk_flags),
    )

    return {
        "dealId": str(deal_id),
        "dealName": deal_fields["deal_name"],
        "pipelineVersion": "v4",
        "versionTag": version_tag,
        "evidencePackId": str(evidence_pack_id),
        "evidencePackTokens": pack_row.token_count,
        "chaptersCompleted": len(chapters),
        "chaptersTotal": 13,
        "chapters": [
            {
                "chapter_number": ch["chapter_number"],
                "chapter_tag": ch["chapter_tag"],
                "chapter_title": ch["chapter_title"],
            }
            for ch in chapters
        ],
        "criticConfidence": critic_dict.get("confidence_score"),
        "criticDefaultConfidence": critic_dict_default.get("confidence_score"),
        "criticFatalFlaws": len(critic_dict.get("fatal_flaws", [])),
        "criticRewriteRequired": critic_dict.get("rewrite_required", False),
        "criticEscalated": critic_escalated,
        "fullMode": full_mode,
        "finalConfidence": final_confidence,  # backward compat (0.0–1.0)
        "evidenceConfidence": evidence_confidence,  # novo
        "confidenceScore": confidence_score,  # NEW deterministic 0-100
        "confidenceLevel": confidence_level,  # NEW HIGH/MEDIUM/LOW
        "confidenceBreakdown": confidence_breakdown,  # NEW per-block detail
        "confidenceCapsApplied": confidence_caps,  # NEW hard-cap list
        "icGate": ic_gate,  # novo
        "icGateReasons": ic_gate_reasons,  # novo
        "instrumentType": instrument_type,  # novo
        "quantStatus": quant_dict.get("metrics_status"),
        "concentrationBreached": concentration_dict.get("any_limit_breached", False),
        "policyStatus": policy_dict.get("overall_status"),
        "sponsorFlags": len(sponsor_output.get("governance_red_flags", [])),
        "macroStressFlag": macro_stress_flag,
        "kycScreeningSummary": kyc_results.get("summary", {}),
        "decisionAnchor": decision_anchor,
        "tokenUsage": token_summary,
        "citationGovernance": {
            "citationsUsed": len(citations_used),
            "uniqueChunks": len(
                {
                    c.get("chunk_id")
                    for c in citations_used
                    if c.get("chunk_id") != "NONE"
                },
            ),
            "unsupportedClaimsDetected": unsupported_claims_detected,
            "selfAuditPass": not unsupported_claims_detected,
        },
        "toneReviewLog": tone_review_log,
        "tonePass1Changes": tone_pass1_changes,
        "tonePass2Changes": tone_pass2_changes,
        "toneSignalOriginal": _tone_signal_original,
        "toneSignalFinal": _tone_signal_final,
        "fullMemo": full_memo_text,
        "asOf": now.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# ASYNC DAG ORCHESTRATOR — Parallel Deep Review V4
# ═══════════════════════════════════════════════════════════════════════════


async def async_run_deal_deep_review_v4(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    actor_id: str = "ai-engine",
    force: bool = False,
    full_mode: bool = False,
) -> dict[str, Any]:
    """Async deep review V4 — parallel DAG orchestrator.

    Executes independent pipeline stages concurrently via asyncio.gather().
    DB-touching and external API calls use asyncio.to_thread() with
    session-per-thread isolation.  LLM calls use native AsyncOpenAI
    where the calling layer supports it directly.

    7-phase DAG:
      Phase 1: Parallel retrieval (RAG, macro, benchmarks, concentration)
      Phase 2: Sequential structured analysis (needs corpus)
      Phase 3: Parallel stages (EDGAR, policy, sponsor, KYC, quant)
      Phase 4: Evidence pack build (convergence)
      Phase 5: IC Critic + Decision Anchor (must complete before chapters)
      Phase 6: Memo Book generation (13 chapters)
      Phase 7: Post-processing, tone normalizer, persist
    """
    from ai_engine.governance.artifact_cache import (
        artifact_exists_v4,
        load_cached_artifact_v4,
    )
    from ai_engine.portfolio.concentration_engine import compute_concentration
    from vertical_engines.credit.critic import (
        classify_instrument_type,
        critique_intelligence,
    )
    from vertical_engines.credit.edgar import (
        build_edgar_multi_entity_context,
        extract_searchable_entities,
        fetch_edgar_multi_entity,
    )
    from vertical_engines.credit.memo_book_generator import async_generate_memo_book
    from vertical_engines.credit.memo_evidence_pack import (
        build_evidence_pack,
        persist_evidence_pack,
        validate_evidence_pack,
    )
    from vertical_engines.credit.quant import compute_quant_profile
    from vertical_engines.credit.sponsor import analyze_sponsor

    now = _now_utc()
    budget = TokenBudgetTracker(context="deep_review_v4")
    sem = asyncio.Semaphore(_LLM_CONCURRENCY)

    async def guarded(coro: Awaitable[Any]) -> Any:
        async with sem:
            return await coro

    # ── Token ceilings ────────────────────────────────────────────
    max_tokens_structured = 6000 if full_mode else 4000
    max_tokens_sponsor = 8000 if full_mode else 6000
    max_tokens_memo = 10000 if full_mode else 6000
    max_tokens_critic = 10000 if full_mode else 8000
    max_tokens_escalation = 16000 if full_mode else 12000

    if full_mode:
        logger.info("V4_FULL_MODE_ENABLED deal_id=%s", deal_id)

    # ── Stage 1: Cache check (sync, fast) ─────────────────────────
    if not force and artifact_exists_v4(db, deal_id=deal_id):
        cached = load_cached_artifact_v4(db, deal_id=deal_id, fund_id=fund_id)
        if cached and cached.get("chaptersCompleted", 0) >= 13:
            logger.info("V4_CACHE_HIT deal_id=%s — returning cached result", deal_id)
            return cached

    # ── Stage 1b: Deal lookup (sync, fast) ────────────────────────
    deal = db.execute(
        select(Deal).where(Deal.id == deal_id, Deal.fund_id == fund_id),
    ).scalar_one_or_none()
    if deal is None:
        return {"error": "Deal not found", "dealId": str(deal_id)}

    deal_fields = {
        "deal_name": deal.deal_name or getattr(deal, "title", ""),
        "sponsor_name": getattr(deal, "sponsor_name", None) or "",
        "borrower_name": getattr(deal, "borrower_name", None) or "",
        "currency": getattr(deal, "currency", "USD") or "USD",
        "requested_amount": getattr(deal, "requested_amount", None),
        "stage": getattr(deal, "stage", None),
    }

    deal_context_blob = _load_deal_context_from_blob(deal, deal_fields)
    # Capture ORM attributes before to_thread — ORM objects are session-bound
    deal_folder_path = deal.deal_folder_path
    deal_ticker = getattr(deal, "ticker", None) or None
    deal_geography = (
        deal_fields.get("property_location")
        or deal_fields.get("geography")
        or deal_fields.get("collateral_location")
    )

    version_tag = f"v4-{now.strftime('%Y%m%dT%H%M%S')}"
    logger.info("V4_ASYNC_START deal_id=%s version=%s", deal_id, version_tag)

    # ══════════════════════════════════════════════════════════════
    # Phase 1: Parallel retrieval + deterministic stages
    # Each to_thread call that touches DB creates its own session.
    # After gather() returns, all threads have completed — main db
    # session is exclusively owned by the event loop thread again.
    # ══════════════════════════════════════════════════════════════
    SessionLocal = async_session_factory

    def _gather_texts_threadsafe() -> dict:
        with SessionLocal() as session:
            deal_obj = session.execute(
                select(Deal).where(Deal.id == deal_id, Deal.fund_id == fund_id),
            ).scalar_one()
            return _gather_deal_texts(session, fund_id=fund_id, deal=deal_obj)

    def _get_macro_threadsafe() -> dict:
        from vertical_engines.credit.market_data import get_macro_snapshot
        with SessionLocal() as session:
            return get_macro_snapshot(session, deal_geography=deal_geography)

    def _fetch_benchmarks_threadsafe() -> list[dict]:
        from ai_engine.governance.policy_loader import (
            SEARCH_API_KEY as _SK,
        )
        from ai_engine.governance.policy_loader import (
            SEARCH_ENDPOINT as _SE,
        )
        from vertical_engines.credit.retrieval import retrieve_market_benchmarks
        results: list[dict] = []
        chapters = ("ch03_exit", "ch08_returns", "ch09_downside", "ch12_peers")

        def _fetch(chapter: str) -> list[dict]:
            try:
                return retrieve_market_benchmarks(
                    chapter, search_endpoint=_SE, search_api_key=_SK, top_k=12,
                )
            except Exception as exc:
                logger.warning("V4_MARKET_BENCHMARKS_WARN chapter=%s error=%s", chapter, exc)
                return []

        from concurrent.futures import ThreadPoolExecutor as _TPE
        with _TPE(max_workers=4) as pool:
            for chunks in pool.map(_fetch, chapters):
                results.extend(chunks)
        return results

    def _compute_concentration_threadsafe():
        from ai_engine.governance.policy_loader import load_policy_thresholds as _lp
        policy = _lp()
        pending = {
            "deal_name": deal_fields["deal_name"],
            "currency": deal_fields["currency"],
            "requested_amount": deal_fields["requested_amount"],
        }
        with SessionLocal() as session:
            return compute_concentration(
                session, fund_id=fund_id, include_pending_deal=pending, policy=policy,
            )

    (context, macro_snapshot, _market_benchmarks, concentration_profile) = (
        await asyncio.gather(
            asyncio.to_thread(_gather_texts_threadsafe),
            asyncio.to_thread(_get_macro_threadsafe),
            asyncio.to_thread(_fetch_benchmarks_threadsafe),
            asyncio.to_thread(_compute_concentration_threadsafe),
        )
    )
    # INVARIANT: All to_thread tasks completed. Main db session exclusively owned.

    corpus = context["corpus_text"]
    evidence_map = context["evidence_map"]
    evidence_chunks = context.get("raw_chunks", [])
    retrieval_audit = context.get("retrieval_audit", {})
    saturation_report = context.get("saturation_report", {})
    chapter_evidence = context.get("chapter_evidence", {})

    if not corpus or len(corpus.strip()) < 200:
        return {
            "error": "Insufficient document corpus for V4 review",
            "dealId": str(deal_id),
            "corpusLength": len(corpus) if corpus else 0,
        }

    concentration_dict = concentration_profile.to_dict()

    from vertical_engines.credit.market_data import compute_macro_stress_severity
    macro_stress = compute_macro_stress_severity(macro_snapshot)
    macro_stress_flag = macro_stress["level"] in ("MODERATE", "SEVERE")

    logger.info(
        "V4_ASYNC_PHASE1_COMPLETE deal_id=%s corpus_len=%d benchmarks=%d",
        deal_id, len(corpus), len(_market_benchmarks),
    )

    # ══════════════════════════════════════════════════════════════
    # Phase 2: Structured analysis (needs corpus from Phase 1)
    # ══════════════════════════════════════════════════════════════
    model_structured = get_model("structured")
    pre_instrument_type = _pre_classify_from_corpus(corpus, deal_fields)
    deal_review_prompt = _build_deal_review_prompt_v2(
        pre_instrument_type,
        deal_role_map=deal_fields.get("deal_role_map"),
        third_party_counterparties=deal_fields.get("third_party_counterparties"),
    )
    logger.info("V4_PRE_CLASSIFIED deal_id=%s type=%s", deal_id, pre_instrument_type)

    analysis = await guarded(_async_call_openai(
        deal_review_prompt,
        corpus,
        max_tokens=max_tokens_structured,
        model=model_structured,
        budget=budget,
        label="v4_stage3_analysis",
    ))

    instrument_type = classify_instrument_type(analysis)
    logger.info("V4_INSTRUMENT_CLASSIFIED deal_id=%s type=%s", deal_id, instrument_type)

    # ══════════════════════════════════════════════════════════════
    # Phase 3: Parallel stages (EDGAR, policy, sponsor, KYC, quant)
    # Uses to_thread for complex sync functions. Non-fatal stages
    # (EDGAR, KYC) tolerate failures via return_exceptions=True.
    # ══════════════════════════════════════════════════════════════

    def _run_edgar_sync() -> str:
        _target_vehicle = ""
        if isinstance(analysis, dict):
            _tv = analysis.get("targetVehicle")
            if (
                _tv and isinstance(_tv, str)
                and _tv.strip().lower() not in (
                    "", "pending diligence", "n/a", "not specified", "unknown",
                )
            ):
                _target_vehicle = _tv.strip()
        edgar_entities = extract_searchable_entities(
            deal_fields, analysis,
            ticker=deal_ticker,
            instrument_type=instrument_type,
        )
        edgar_multi = fetch_edgar_multi_entity(
            edgar_entities, instrument_type=instrument_type,
        )
        ctx = build_edgar_multi_entity_context(
            edgar_multi,
            deal_name=deal_fields.get("deal_name", ""),
            target_vehicle=_target_vehicle,
        )
        logger.info(
            "V4_STAGE_4_7_EDGAR_COMPLETE",
            extra={
                "deal_id": str(deal_id),
                "entities_tried": edgar_multi["entities_tried"],
                "entities_found": edgar_multi["entities_found"],
                "unique_ciks": edgar_multi["unique_ciks"],
                "context_chars": len(ctx),
            },
        )
        return ctx

    def _run_policy_pipeline_sync() -> tuple[dict, dict]:
        from ai_engine.governance.policy_loader import load_policy_thresholds as _lp
        policy = _lp()
        hard_checks = _run_hard_policy_checks(
            concentration_dict=concentration_dict,
            analysis=analysis,
            deal_fields=deal_fields,
            policy=policy,
        )
        policy_text = _gather_policy_context(
            fund_id,
            deal_fields["deal_name"],
            deal_folder_path=deal_folder_path,
        )
        policy_result = _run_policy_compliance(
            corpus,
            policy_text,
            analysis,
            hard_check_results=hard_checks,
        )
        return hard_checks, policy_result

    def _run_sponsor_sync() -> dict:
        model_sponsor = get_model("sponsor")

        def _sponsor_call(
            system: str, user: str, *, max_tokens: int = max_tokens_sponsor,
        ):
            return _call_openai(
                system, user, max_tokens=max_tokens, model=model_sponsor,
                budget=budget, label="v4_stage9_sponsor",
            )

        # Build sponsor-specific corpus from ch04 evidence
        index_key_persons: list[str] = []
        sponsor_evidence_text: str | None = None
        ch04_data = chapter_evidence.get("ch04_sponsor")
        if ch04_data and ch04_data.get("chunks"):
            _seen_kp: set[str] = set()
            for chunk in evidence_chunks:
                for kp in chunk.get("key_persons_mentioned", []):
                    kp_clean = kp.strip()
                    if kp_clean and kp_clean.lower() not in _seen_kp:
                        _seen_kp.add(kp_clean.lower())
                        index_key_persons.append(kp_clean)
            ch04_chunks = ch04_data["chunks"]
            ch04_parts: list[str] = []
            for chunk in ch04_chunks:
                content = chunk.get("content", "")
                if content:
                    blob = chunk.get("blob_name", chunk.get("title", ""))
                    header = f"--- [{blob}] doc_type={chunk.get('doc_type', '?')} ---"
                    ch04_parts.append(f"{header}\n{content}")
            sponsor_evidence_text = "\n\n".join(ch04_parts) if ch04_parts else None

        return analyze_sponsor(
            corpus=corpus,
            deal_fields=deal_fields,
            analysis=analysis,
            call_openai_fn=_sponsor_call,
            index_key_persons=index_key_persons if index_key_persons else None,
            sponsor_evidence_text=sponsor_evidence_text,
        )

    def _run_kyc_sync() -> tuple[dict, str]:
        from vertical_engines.credit.kyc import (
            build_kyc_appendix,
            run_kyc_screenings,
        )
        # Extract index_key_persons (same logic as sponsor)
        index_key_persons: list[str] = []
        ch04_data = chapter_evidence.get("ch04_sponsor")
        if ch04_data and ch04_data.get("chunks"):
            _seen: set[str] = set()
            for chunk in evidence_chunks:
                for kp in chunk.get("key_persons_mentioned", []):
                    kp_clean = kp.strip()
                    if kp_clean and kp_clean.lower() not in _seen:
                        _seen.add(kp_clean.lower())
                        index_key_persons.append(kp_clean)

        results = run_kyc_screenings(
            analysis=analysis,
            deal_fields=deal_fields,
            index_key_persons=index_key_persons,
            sponsor_output={},  # sponsor may not be done yet
        )
        appendix = build_kyc_appendix(
            results, deal_name=deal_fields.get("deal_name", ""),
        )
        return results, appendix

    def _run_quant_sync() -> dict:
        return compute_quant_profile(
            analysis,
            deal_fields=deal_fields,
            macro_snapshot=macro_snapshot,
            concentration_profile=concentration_dict,
        ).to_dict()

    results_3 = await asyncio.gather(
        asyncio.to_thread(_run_edgar_sync),
        asyncio.to_thread(_run_policy_pipeline_sync),
        asyncio.to_thread(_run_sponsor_sync),
        asyncio.to_thread(_run_kyc_sync),
        asyncio.to_thread(_run_quant_sync),
        return_exceptions=True,
    )
    # INVARIANT: All to_thread tasks completed. Main db session exclusively owned.

    # ── Unpack Phase 3 results with BaseException guards ──────────
    stage_names = ["EDGAR", "Policy", "Sponsor", "KYC", "Quant"]
    for i, result in enumerate(results_3):
        if isinstance(result, BaseException):
            if stage_names[i] in ("EDGAR", "KYC"):
                logger.warning(
                    "V4_ASYNC_NONFATAL_STAGE_%s_FAILED error=%s",
                    stage_names[i], type(result).__name__,
                )
            else:
                logger.error(
                    "V4_ASYNC_FATAL_STAGE_%s_FAILED error=%s",
                    stage_names[i], type(result).__name__,
                )
                raise result

    edgar_context: str = results_3[0] if not isinstance(results_3[0], BaseException) else ""

    if isinstance(results_3[1], BaseException):
        hard_check_results: dict = {}
        policy_dict: dict = {}
    else:
        hard_check_results, policy_dict = results_3[1]

    sponsor_output: dict = results_3[2] if not isinstance(results_3[2], BaseException) else {}

    if isinstance(results_3[3], BaseException):
        kyc_results: dict[str, Any] = {}
        kyc_appendix_text: str = ""
    else:
        kyc_results, kyc_appendix_text = results_3[3]

    quant_dict: dict = results_3[4] if not isinstance(results_3[4], BaseException) else {}

    # Persist KYC screenings to DB (main thread, main session)
    if kyc_results and kyc_results.get("summary", {}).get("skipped") is not True:
        try:
            from vertical_engines.credit.kyc import (
                persist_kyc_screenings_to_db,
            )
            persist_kyc_screenings_to_db(
                db, fund_id=fund_id, deal_id=deal_id,
                kyc_results=kyc_results, actor_id=actor_id,
            )
        except Exception as _kyc_db_exc:
            logger.warning(
                "KYC_PIPELINE_DB_PERSIST_FAILED deal_id=%s error=%s",
                deal_id, type(_kyc_db_exc).__name__,
            )

    logger.info(
        "V4_ASYNC_PHASE3_COMPLETE deal_id=%s edgar=%d policy=%s sponsor_flags=%d kyc=%s",
        deal_id,
        len(edgar_context),
        policy_dict.get("overall_status", "N/A"),
        len(sponsor_output.get("governance_red_flags", [])),
        kyc_results.get("summary", {}).get("total_matches", "N/A"),
    )

    # ══════════════════════════════════════════════════════════════
    # Phase 4: Evidence Pack Build (convergence — <1s)
    # ══════════════════════════════════════════════════════════════
    evidence_pack = build_evidence_pack(
        analysis=analysis,
        quant_dict=quant_dict,
        concentration_dict=concentration_dict,
        policy_dict=policy_dict,
        macro_snapshot=macro_snapshot,
        sponsor_output=sponsor_output,
        deal_fields=deal_fields,
        evidence_map=evidence_map,
        market_benchmarks=_market_benchmarks,
    )
    try:
        validate_evidence_pack(evidence_pack)
    except ValueError as exc:
        logger.error("V4_EVIDENCE_PACK_INVALID errors=%s", exc)
        return {
            "error": "EvidencePack validation failed",
            "dealId": str(deal_id),
            "validationErrors": [str(exc)],
        }

    if edgar_context.strip():
        evidence_pack["edgar_public_filings"] = edgar_context
    if deal_context_blob:
        evidence_pack["deal_context"] = deal_context_blob

    model_evidence = get_model("evidence_pack")
    pack_row = persist_evidence_pack(
        db, fund_id=fund_id, deal_id=deal_id, pack=evidence_pack,
        version_tag=version_tag, model_version=model_evidence, actor_id=actor_id,
    )
    evidence_pack_id = pack_row.id
    logger.info(
        "V4_EVIDENCE_PACK_FROZEN deal_id=%s pack_id=%s tokens=%d",
        deal_id, evidence_pack_id, pack_row.token_count,
    )

    # ══════════════════════════════════════════════════════════════
    # Phase 5: IC Critic — MUST complete before chapter generation
    # ══════════════════════════════════════════════════════════════
    model_critic = get_model("critic")
    critic_context = {
        "structured_analysis": analysis,
        "ic_brief": {},
        "full_memo": "",
        "quant_profile": quant_dict,
        "concentration_profile": concentration_dict,
        "policy_compliance": policy_dict,
        "deal_fields": deal_fields,
        "macro_snapshot": macro_snapshot,
        "macro_stress_flag": macro_stress_flag,
        "instrument_type": instrument_type,
    }

    def _critic_call(
        system: str, user: str, *, max_tokens: int = max_tokens_critic,
    ):
        return _call_openai(
            system, user, max_tokens=max_tokens, model=model_critic,
            budget=budget, label="v4_stage11_critic",
        )

    critic_verdict = await asyncio.to_thread(
        critique_intelligence, critic_context, call_openai_fn=_critic_call,
    )
    critic_dict = critic_verdict.to_dict()
    critic_dict_default = critic_dict

    # ── Critic escalation ─────────────────────────────────────────
    critic_escalated = False
    critic_dict_escalation: dict[str, Any] | None = None
    _conf = critic_dict.get("confidence_score", 1.0)
    _fatal = critic_dict.get("fatal_flaws", [])
    _rewrite = critic_dict.get("rewrite_required", False)

    if _conf < 0.75 or _fatal or _rewrite:
        logger.warning(
            "V4_CRITIC_ESCALATION deal_id=%s confidence=%.2f fatal_flaws=%d rewrite=%s",
            deal_id, _conf, len(_fatal), _rewrite,
        )
        model_critic_esc = get_model("critic_escalation")

        def _critic_esc_call(
            system: str, user: str, *, max_tokens: int = max_tokens_escalation,
        ):
            return _call_openai(
                system, user, max_tokens=max_tokens, model=model_critic_esc,
                budget=budget, label="v4_stage11_critic_escalation",
                stage="critic_escalation",
            )

        critic_verdict_esc = await asyncio.to_thread(
            critique_intelligence, critic_context, call_openai_fn=_critic_esc_call,
        )
        critic_dict_escalation = critic_verdict_esc.to_dict()
        critic_dict = critic_dict_escalation
        critic_escalated = True
        logger.info(
            "V4_CRITIC_ESCALATION_COMPLETE deal_id=%s "
            "default_confidence=%.2f escalated_confidence=%.2f",
            deal_id,
            critic_dict_default.get("confidence_score", 0),
            critic_dict.get("confidence_score", 0),
        )

    # Inject critic output into evidence pack (consumed by chapter prompts)
    evidence_pack["critic_output"] = {
        "confidence_score": critic_dict.get("confidence_score"),
        "fatal_flaws": critic_dict.get("fatal_flaws", []),
        "material_gaps": critic_dict.get("material_gaps", []),
        "rewrite_required": critic_dict.get("rewrite_required", False),
        "escalated": critic_escalated,
        "default_verdict": {
            "confidence_score": critic_dict_default.get("confidence_score"),
            "fatal_flaws": critic_dict_default.get("fatal_flaws", []),
            "material_gaps": critic_dict_default.get("material_gaps", []),
            "rewrite_required": critic_dict_default.get("rewrite_required", False),
        },
        "escalation_verdict": {
            "confidence_score": critic_dict_escalation.get("confidence_score"),
            "fatal_flaws": critic_dict_escalation.get("fatal_flaws", []),
            "material_gaps": critic_dict_escalation.get("material_gaps", []),
            "rewrite_required": critic_dict_escalation.get("rewrite_required", False),
        }
        if critic_dict_escalation is not None
        else None,
    }

    # ── Decision Anchor ───────────────────────────────────────────
    decision_anchor = _compute_decision_anchor(
        hard_check_results=hard_check_results,
        policy_dict=policy_dict,
        critic_dict=critic_dict,
        concentration_dict=concentration_dict,
        quant_dict=quant_dict,
    )
    evidence_pack["decision_anchor"] = decision_anchor
    logger.info(
        "V4_DECISION_ANCHOR deal_id=%s decision=%s icGate=%s",
        deal_id, decision_anchor["finalDecision"], decision_anchor["icGate"],
    )

    # ══════════════════════════════════════════════════════════════
    # Phase 6: Memo Book generation
    # ══════════════════════════════════════════════════════════════
    model_memo = get_model("memo")

    def _memo_call_openai(
        system: str, user: str, *,
        max_tokens: int = max_tokens_memo,
        model: str | None = None,
    ):
        effective_model = model or model_memo
        return _call_openai(
            system, user, max_tokens=max_tokens, model=effective_model,
            budget=budget, label="v4_stage12_chapter", stage="memo",
        )

    memo_result = await async_generate_memo_book(
        db,
        fund_id=fund_id,
        deal_id=deal_id,
        evidence_pack=evidence_pack,
        evidence_pack_id=evidence_pack_id,
        evidence_map=evidence_map,
        evidence_chunks=evidence_chunks,
        quant_dict=quant_dict,
        critic_findings=critic_dict,
        policy_dict=policy_dict,
        sponsor_output=sponsor_output,
        version_tag=version_tag,
        call_openai_fn=_memo_call_openai,
        model=model_memo,
        model_mini=get_model("memo_mini"),
        actor_id=actor_id,
        decision_anchor=decision_anchor,
        sem=sem,
    )

    chapters = memo_result.get("chapters", [])
    full_memo_text = memo_result.get("fullMemo", "")
    chapter_texts = memo_result.get("chapter_texts", {})
    citations_used = memo_result.get("citations_used", [])
    chapter_citations = _index_chapter_citations(chapters, citations_used)
    unsupported_claims_detected = memo_result.get("unsupported_claims_detected", False)
    critical_gaps_all = memo_result.get("critical_gaps", [])

    if kyc_appendix_text:
        full_memo_text = full_memo_text + "\n\n---\n\n" + kyc_appendix_text

    # ══════════════════════════════════════════════════════════════
    # Phase 7: Post-processing, tone normalizer, persist
    # ══════════════════════════════════════════════════════════════

    # ── Post-Memo Critic Review + Feedback Loop ───────────────────
    critic_context_post = {**critic_context, "full_memo": full_memo_text}
    critic_post_verdict = await asyncio.to_thread(
        critique_intelligence, critic_context_post, call_openai_fn=_critic_call,
    )
    critic_post_dict = critic_post_verdict.to_dict()
    critic_rewrite_count = 0

    if critic_post_dict.get("rewrite_required") and chapter_texts:
        logger.warning(
            "V4_CRITIC_POST_MEMO_REWRITE deal_id=%s fatal_flaws=%d confidence=%.2f",
            deal_id,
            len(critic_post_dict.get("fatal_flaws", [])),
            critic_post_dict.get("confidence_score", 0),
        )
        affected_tags: set[str] = set()
        for flaw in critic_post_dict.get("fatal_flaws", []):
            flaw_lower = str(flaw).lower()
            for ch_tag in chapter_texts:
                ch_short = ch_tag.replace("ch", "").split("_")[0]
                if ch_short in flaw_lower or ch_tag in flaw_lower:
                    affected_tags.add(ch_tag)
        for gap in critic_post_dict.get("material_gaps", []):
            gap_lower = str(gap).lower()
            for ch_tag in chapter_texts:
                ch_short = ch_tag.replace("ch", "").split("_")[0]
                if ch_short in gap_lower or ch_tag in gap_lower:
                    affected_tags.add(ch_tag)

        if not affected_tags:
            affected_tags = {"ch01_exec", "ch13_recommendation"}

        critic_addendum = (
            "CRITIC FINDINGS (address these issues):\n"
            + "\n".join(f"- FATAL: {f}" for f in critic_post_dict.get("fatal_flaws", []))
            + "\n".join(f"- GAP: {g}" for g in critic_post_dict.get("material_gaps", []))
        )

        from vertical_engines.credit.memo_chapter_engine import (
            regenerate_chapter_with_critic,
        )

        rewrite_tasks: list[Any] = []
        rewrite_tags: list[str] = []
        for ch_tag in affected_tags:
            if ch_tag not in chapter_texts:
                continue
            rewrite_tags.append(ch_tag)
            rewrite_tasks.append(
                asyncio.to_thread(
                    regenerate_chapter_with_critic,
                    ch_tag=ch_tag,
                    original_text=chapter_texts[ch_tag],
                    critic_addendum=critic_addendum,
                    evidence_pack=evidence_pack,
                    call_openai_fn=_memo_call_openai,
                ),
            )

        if rewrite_tasks:
            rewrite_results = await asyncio.gather(
                *rewrite_tasks, return_exceptions=True,
            )
            for ch_tag, result in zip(rewrite_tags, rewrite_results, strict=False):
                if isinstance(result, BaseException):
                    logger.warning(
                        "V4_ASYNC_CRITIC_REWRITE_FAILED chapter=%s deal_id=%s error=%s",
                        ch_tag, deal_id, type(result).__name__,
                    )
                    continue
                if result:
                    chapter_texts[ch_tag] = result
                    for ch in chapters:
                        if ch.get("chapter_tag") == ch_tag:
                            ch["section_text"] = result
                    critic_rewrite_count += 1
            # Rebuild full memo text once after all rewrites
            full_memo_text = "\n\n---\n\n".join(
                chapter_texts[t] for t in sorted(chapter_texts)
            )

        critic_dict = critic_post_dict
        evidence_pack["critic_output"]["post_memo_review"] = critic_post_dict
        evidence_pack["critic_output"]["rewrite_count"] = critic_rewrite_count
    elif critic_post_dict.get("fatal_flaws"):
        critic_dict = critic_post_dict
        evidence_pack["critic_output"]["post_memo_review"] = critic_post_dict

    # ── Confidence Score (deterministic, before tone) ─────────────
    from vertical_engines.credit.deep_review_confidence import (
        apply_tone_normalizer_adjustment,
        compute_underwriting_confidence,
    )

    im_recommendation = memo_result.get("recommendation", "")

    _epm_chapter_counts: dict[str, dict] = {}
    for _ch_key, _ch_data in chapter_evidence.items():
        _ch_stats = _ch_data.get("stats", {}) if isinstance(_ch_data, dict) else {}
        _epm_chapter_counts[_ch_key] = {
            "unique_docs": _ch_stats.get("unique_docs", 0),
            "chunk_count": _ch_stats.get("chunk_count", 0),
        }

    _epm_terms = {}
    if isinstance(analysis, dict):
        _epm_terms = analysis.get("investmentTerms", {})
        if not isinstance(_epm_terms, dict):
            _epm_terms = {}

    evidence_pack_meta = {
        "chapter_counts": _epm_chapter_counts,
        "investment_terms": _epm_terms,
    }

    uw_confidence = compute_underwriting_confidence(
        retrieval_audit=retrieval_audit,
        saturation_report=saturation_report,
        hard_check_results=hard_check_results,
        concentration_profile=concentration_dict,
        critic_output=critic_dict,
        quant_profile=quant_dict,
        evidence_pack_meta=evidence_pack_meta,
    )
    confidence_score: int = uw_confidence["confidence_score"]
    confidence_level: str = uw_confidence["confidence_level"]
    confidence_breakdown: dict = uw_confidence["breakdown"]
    confidence_caps: list = uw_confidence["caps_applied"]
    pre_tone_confidence_score = confidence_score
    pre_tone_confidence_level = confidence_level
    pre_tone_confidence_breakdown = dict(confidence_breakdown)
    pre_tone_confidence_caps = list(confidence_caps)

    ic_gate: str = decision_anchor["icGate"]
    ic_gate_reasons: list = []
    if ic_gate == "BLOCKED" or ic_gate == "CONDITIONAL":
        ic_gate_reasons = [decision_anchor.get("decisionRationale", "")]

    _legacy_conf = _compute_confidence_score(
        quant_dict=quant_dict,
        concentration_dict=concentration_dict,
        policy_dict=policy_dict,
        critic_dict=critic_dict,
        im_recommendation=im_recommendation,
    )
    final_confidence: float = _legacy_conf["final_confidence"]
    evidence_confidence: float = _legacy_conf["evidence_confidence"]

    token_summary = budget.summary()
    logger.info(
        "V4_ASYNC_COMPLETE deal_id=%s version=%s chapters=%d confidence=%.2f "
        "ic_gate=%s tokens=%s",
        deal_id, version_tag, len(chapters), final_confidence, ic_gate, token_summary,
    )

    # ── Tone Normalizer (already async — await directly) ──────────
    tone_review_log: list = []
    tone_pass1_changes: dict = {}
    tone_pass2_changes: list = []
    _tone_signal_original: str = ""
    _tone_signal_final: str = ""
    pre_tone_chapter_texts = dict(chapter_texts)
    post_tone_chapter_texts = dict(chapter_texts)

    if chapter_texts:
        try:
            from vertical_engines.credit.tone_normalizer import (
                run_tone_normalizer as _run_tone_normalizer,
            )
            logger.info(
                "TONE_NORMALIZER_START deal_id=%s chapters=%d signal=%s",
                deal_id, len(chapter_texts), im_recommendation,
            )

            tone_result = await _run_tone_normalizer(
                chapter_texts=chapter_texts,
                critic_output=critic_dict,
                current_signal=im_recommendation,
            )

            if tone_result.get("chapters"):
                from app.domains.credit.modules.ai.models import MemoChapter as _MemoChapter
                for _ch_tag, _revised in tone_result["chapters"].items():
                    if _revised and _revised.strip():
                        db.execute(
                            update(_MemoChapter)
                            .where(
                                _MemoChapter.deal_id == deal_id,
                                _MemoChapter.version_tag == version_tag,
                                _MemoChapter.chapter_tag == _ch_tag,
                            )
                            .values(content_md=_revised),
                        )
                        post_tone_chapter_texts[_ch_tag] = _revised
                db.flush()

            if tone_result.get("signal_escalated"):
                _new_signal = tone_result.get("signal_final", im_recommendation)
                logger.warning(
                    "TONE_SIGNAL_ESCALATED deal_id=%s %s → %s",
                    deal_id, im_recommendation, _new_signal,
                )
                im_recommendation = _new_signal

            tone_review_log = tone_result.get("tone_review_log", [])
            tone_pass1_changes = tone_result.get("pass1_changes", {})
            tone_pass2_changes = tone_result.get("pass2_changes", [])
            _tone_signal_original = tone_result.get("signal_original", im_recommendation)
            _tone_signal_final = tone_result.get("signal_final", im_recommendation)

        except Exception as _tone_exc:
            logger.warning(
                "TONE_NORMALIZER_FAILED deal_id=%s error=%s — continuing",
                deal_id, type(_tone_exc).__name__,
            )

    # Post-tone confidence adjustment
    uw_confidence = apply_tone_normalizer_adjustment(
        uw_confidence,
        tone_signal_escalated=bool(
            tone_pass2_changes
            and any("escalat" in str(c).lower() for c in tone_pass2_changes),
        )
        if chapter_texts
        else False,
        tone_pass2_changes=tone_pass2_changes,
    )
    confidence_score = uw_confidence["confidence_score"]
    confidence_level = uw_confidence["confidence_level"]
    confidence_breakdown = uw_confidence["breakdown"]
    confidence_caps = uw_confidence["caps_applied"]

    # ── Persist final metadata ────────────────────────────────────
    from app.domains.credit.modules.ai.models import MemoEvidencePack

    db.execute(
        update(MemoEvidencePack)
        .where(MemoEvidencePack.id == evidence_pack_id)
        .values(
            evidence_json={
                **pack_row.evidence_json,
                "citations": citations_used,
                "chapter_citations": chapter_citations,
                "critic_output": evidence_pack.get("critic_output", {}),
                "decision_anchor": decision_anchor,
                "final_confidence": final_confidence,
                "evidence_confidence": evidence_confidence,
                "confidence_score_pre_tone": pre_tone_confidence_score,
                "confidence_level_pre_tone": pre_tone_confidence_level,
                "confidence_breakdown_pre_tone": pre_tone_confidence_breakdown,
                "confidence_caps_applied_pre_tone": pre_tone_confidence_caps,
                "confidence_score": confidence_score,
                "confidence_level": confidence_level,
                "confidence_breakdown": confidence_breakdown,
                "confidence_caps_applied": confidence_caps,
                "ic_gate": ic_gate,
                "ic_gate_reasons": ic_gate_reasons,
                "instrument_type": instrument_type,
                "pipeline_version": "v4.4-ic-grade",
                "retrieval_policy": retrieval_audit.get(
                    "retrieval_policy", "IC_GRADE_V1",
                ),
                "stages_completed": 13,
                "chapter_count": len(chapters),
                "citation_governance": {
                    "citations_used": len(citations_used),
                    "unique_chunks": len(
                        {
                            c.get("chunk_id")
                            for c in citations_used
                            if c.get("chunk_id") != "NONE"
                        },
                    ),
                    "unsupported_claims_detected": unsupported_claims_detected,
                    "self_audit_pass": not unsupported_claims_detected,
                },
                "retrieval_audit": retrieval_audit,
                "saturation_report": saturation_report,
                "appendix_1_source_index": memo_result.get(
                    "appendix_1_source_index", "",
                ),
                "appendix_kyc_checks": kyc_appendix_text,
                "kyc_screening_summary": kyc_results.get("summary", {}),
                "tone_artifacts": _build_tone_artifacts(
                    pre_tone_chapters=pre_tone_chapter_texts,
                    post_tone_chapters=post_tone_chapter_texts,
                    tone_review_log=tone_review_log,
                    tone_pass1_changes=tone_pass1_changes,
                    tone_pass2_changes=tone_pass2_changes,
                    signal_original=_tone_signal_original,
                    signal_final=_tone_signal_final,
                ),
            },
        ),
    )

    # ── Persist Unified Underwriting Artifact ─────────────────────
    from vertical_engines.credit.underwriting_artifact import (
        derive_risk_band as _derive_risk_band,
    )
    from vertical_engines.credit.underwriting_artifact import (
        persist_underwriting_artifact,
    )

    persist_underwriting_artifact(
        db,
        fund_id=fund_id,
        deal_id=deal_id,
        evidence_pack=evidence_pack,
        evidence_pack_id=evidence_pack_id,
        im_recommendation=im_recommendation,
        final_confidence=final_confidence,
        analysis=analysis,
        critic_dict=critic_dict,
        policy_dict=policy_dict,
        chapters_completed=len(chapters),
        model_version=model_memo,
        generated_at=now,
        version_tag=version_tag,
        actor_id=actor_id,
        confidence_score=confidence_score,
        confidence_level=confidence_level,
        confidence_breakdown=confidence_breakdown,
        confidence_caps=confidence_caps,
        critical_gaps=critical_gaps_all,
    )

    # ── Persist DealIntelligenceProfile + DealICBrief ─────────────
    _v4_risk_band = _derive_risk_band(analysis)
    _v4_risk_band_label = {"HIGH": "HIGH", "MEDIUM": "MODERATE", "LOW": "LOW"}.get(
        _v4_risk_band, _v4_risk_band,
    )
    _v4_returns = analysis.get("expectedReturns", {})
    _v4_risks = analysis.get("riskFactors", [])
    if not isinstance(_v4_risks, list):
        _v4_risks = []

    _v4_profile_metadata = {
        "evidence_map": evidence_map,
        "quant_profile": quant_dict,
        "sensitivity_matrix": quant_dict.get("sensitivity_matrix", []),
        "concentration_profile": concentration_dict,
        "macro_snapshot": macro_snapshot,
        "macro_stress_flag": macro_stress_flag,
        "critic_output": critic_dict,
        "policy_compliance": policy_dict,
        "decision_anchor": decision_anchor,
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "confidence_breakdown": confidence_breakdown,
        "confidence_caps_applied": confidence_caps,
        "legacy_confidence_score": final_confidence,
        "evidence_confidence": evidence_confidence,
        "ic_gate": ic_gate,
        "ic_gate_reasons": ic_gate_reasons,
        "instrument_type": instrument_type,
        "pipeline_version": "v4",
        "token_budget": token_summary,
        "chapter_citations": chapter_citations,
        "tone_artifacts": _build_tone_artifacts(
            pre_tone_chapters=pre_tone_chapter_texts,
            post_tone_chapters=post_tone_chapter_texts,
            tone_review_log=tone_review_log,
            tone_pass1_changes=tone_pass1_changes,
            tone_pass2_changes=tone_pass2_changes,
            signal_original=_tone_signal_original,
            signal_final=_tone_signal_final,
        ),
        "tone_signal_original": _tone_signal_original,
        "tone_signal_final": _tone_signal_final,
    }

    _v4_profile = DealIntelligenceProfile(
        fund_id=fund_id,
        deal_id=deal_id,
        strategy_type=_title_case_strategy(
            _trunc(
                analysis.get("strategyType")
                or deal_fields.get("strategy_type")
                or "Private Credit",
                80,
            ),
        ),
        geography=_trunc(
            analysis.get("geography") or deal_fields.get("geography"), 120,
        ),
        sector_focus=_trunc(analysis.get("sectorFocus"), 160),
        target_return=_trunc(
            _v4_returns.get("targetIRR") or _v4_returns.get("couponRate"), 60,
        ),
        risk_band=_trunc(_v4_risk_band_label, 20),
        liquidity_profile=_trunc(analysis.get("liquidityProfile"), 80),
        capital_structure_type=_trunc(analysis.get("capitalStructurePosition"), 80),
        key_risks=[
            {
                "riskType": r.get("factor", ""),
                "severity": r.get("severity", "LOW"),
                "mitigation": r.get("mitigation", ""),
            }
            for r in _v4_risks
            if isinstance(r, dict)
        ],
        differentiators=analysis.get("keyDifferentiators", []),
        summary_ic_ready=analysis.get("executiveSummary", "AI review pending."),
        last_ai_refresh=now,
        metadata_json=_v4_profile_metadata,
        created_by=actor_id,
        updated_by=actor_id,
    )

    _exec_summary = chapter_texts.get(
        "ch01_executive_summary", analysis.get("executiveSummary", ""),
    )
    _opp_overview = chapter_texts.get(
        "ch02_opportunity", analysis.get("opportunityOverview", ""),
    )
    _return_profile = chapter_texts.get(
        "ch08_returns", analysis.get("returnProfile", ""),
    )
    _downside_case = chapter_texts.get(
        "ch09_downside", analysis.get("downsideCase", ""),
    )
    _risk_summary = chapter_texts.get("ch10_risk", analysis.get("riskSummary", ""))
    _peer_compare = chapter_texts.get("ch12_peers", analysis.get("peerComparison", ""))
    _rec_signal = _trunc(
        (
            im_recommendation or decision_anchor.get("finalDecision", "CONDITIONAL")
        ).upper(),
        20,
    )

    _v4_brief = DealICBrief(
        fund_id=fund_id,
        deal_id=deal_id,
        executive_summary=_exec_summary or "See IC Memorandum.",
        opportunity_overview=_opp_overview or "See IC Memorandum.",
        return_profile=_return_profile or "See IC Memorandum.",
        downside_case=_downside_case or "See IC Memorandum.",
        risk_summary=_risk_summary or "See IC Memorandum.",
        comparison_peer_funds=_peer_compare or "See IC Memorandum.",
        recommendation_signal=_rec_signal,
        created_by=actor_id,
        updated_by=actor_id,
    )

    _v4_risk_flags = [
        DealRiskFlag(
            fund_id=fund_id,
            deal_id=deal_id,
            risk_type=_trunc(risk.get("factor", "UNKNOWN"), 40),
            severity=_trunc(risk.get("severity", "LOW"), 20),
            reasoning=(
                f"{risk.get('factor', '')}: "
                f"{risk.get('mitigation', 'No mitigation identified.')}"
            ),
            source_document=_trunc(deal_folder_path, 800),
            created_by=actor_id,
            updated_by=actor_id,
        )
        for risk in _v4_risks
        if isinstance(risk, dict)
    ]

    with db.begin_nested():
        db.execute(
            delete(DealIntelligenceProfile).where(
                DealIntelligenceProfile.fund_id == fund_id,
                DealIntelligenceProfile.deal_id == deal_id,
            ),
        )
        db.execute(
            delete(DealRiskFlag).where(
                DealRiskFlag.fund_id == fund_id,
                DealRiskFlag.deal_id == deal_id,
            ),
        )
        db.execute(
            delete(DealICBrief).where(
                DealICBrief.fund_id == fund_id,
                DealICBrief.deal_id == deal_id,
            ),
        )
        db.flush()
        db.add(_v4_profile)
        for _flag in _v4_risk_flags:
            db.add(_flag)
        db.add(_v4_brief)

    logger.info(
        "V4_ASYNC_PROFILE_PERSISTED deal_id=%s strategy=%s risk_band=%s signal=%s",
        deal_id, _v4_profile.strategy_type, _v4_risk_band_label, _rec_signal,
    )

    return {
        "dealId": str(deal_id),
        "dealName": deal_fields["deal_name"],
        "pipelineVersion": "v4",
        "versionTag": version_tag,
        "evidencePackId": str(evidence_pack_id),
        "evidencePackTokens": pack_row.token_count,
        "chaptersCompleted": len(chapters),
        "chaptersTotal": 13,
        "chapters": [
            {
                "chapter_number": ch["chapter_number"],
                "chapter_tag": ch["chapter_tag"],
                "chapter_title": ch["chapter_title"],
            }
            for ch in chapters
        ],
        "criticConfidence": critic_dict.get("confidence_score"),
        "criticDefaultConfidence": critic_dict_default.get("confidence_score"),
        "criticFatalFlaws": len(critic_dict.get("fatal_flaws", [])),
        "criticRewriteRequired": critic_dict.get("rewrite_required", False),
        "criticEscalated": critic_escalated,
        "fullMode": full_mode,
        "finalConfidence": final_confidence,
        "evidenceConfidence": evidence_confidence,
        "confidenceScore": confidence_score,
        "confidenceLevel": confidence_level,
        "confidenceBreakdown": confidence_breakdown,
        "confidenceCapsApplied": confidence_caps,
        "icGate": ic_gate,
        "icGateReasons": ic_gate_reasons,
        "instrumentType": instrument_type,
        "quantStatus": quant_dict.get("metrics_status"),
        "concentrationBreached": concentration_dict.get("any_limit_breached", False),
        "policyStatus": policy_dict.get("overall_status"),
        "sponsorFlags": len(sponsor_output.get("governance_red_flags", [])),
        "macroStressFlag": macro_stress_flag,
        "kycScreeningSummary": kyc_results.get("summary", {}),
        "decisionAnchor": decision_anchor,
        "tokenUsage": token_summary,
        "citationGovernance": {
            "citationsUsed": len(citations_used),
            "uniqueChunks": len(
                {
                    c.get("chunk_id")
                    for c in citations_used
                    if c.get("chunk_id") != "NONE"
                },
            ),
            "unsupportedClaimsDetected": unsupported_claims_detected,
            "selfAuditPass": not unsupported_claims_detected,
        },
        "toneReviewLog": tone_review_log,
        "tonePass1Changes": tone_pass1_changes,
        "tonePass2Changes": tone_pass2_changes,
        "toneSignalOriginal": _tone_signal_original,
        "toneSignalFinal": _tone_signal_final,
        "fullMemo": full_memo_text,
        "asOf": now.isoformat(),
    }


def run_all_deals_deep_review_v4(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    force: bool = False,
    full_mode: bool = False,
) -> dict[str, Any]:
    """Run V4 deep review for every pipeline deal with blob documents.

    Session-isolated: each deal runs in its own session to prevent
    cascading corruption.
    """

    deals = list(
        db.execute(
            select(Deal).where(
                Deal.fund_id == fund_id,
                Deal.deal_folder_path.is_not(None),
            ),
        )
        .scalars()
        .all(),
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    SessionLocal = async_session_factory
    results: list[dict[str, Any]] = []

    def _review_deal(deal):
        try:
            with SessionLocal() as session:
                result = run_deal_deep_review_v4(
                    session,
                    fund_id=fund_id,
                    deal_id=deal.id,
                    actor_id=actor_id,
                    force=force,
                    full_mode=full_mode,
                )
                if "error" not in result:
                    session.execute(
                        text(
                            "UPDATE pipeline_deals "
                            "SET intelligence_status = CAST(:s AS intelligence_status_enum), "
                            "    intelligence_generated_at = :ts "
                            "WHERE id = :id",
                        ),
                        {
                            "s": "READY",
                            "ts": dt.datetime.now(dt.UTC),
                            "id": str(deal.id),
                        },
                    )
                    session.commit()
                    logger.info("V4_STATUS_READY deal_id=%s", deal.id)
                else:
                    logger.warning(
                        "V4_RESULT_ERROR deal_id=%s error=%s",
                        deal.id,
                        result.get("error"),
                    )
                    try:
                        session.execute(
                            text(
                                "UPDATE pipeline_deals "
                                "SET intelligence_status = CAST(:s AS intelligence_status_enum) "
                                "WHERE id = :id",
                            ),
                            {"s": "FAILED", "id": str(deal.id)},
                        )
                        session.commit()
                    except Exception:
                        session.rollback()
                return result
        except Exception as exc:
            logger.warning("V4 deep review failed for deal %s: %s", deal.id, exc)
            return {"dealId": str(deal.id), "error": str(exc)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(_review_deal, deal): deal for deal in deals}
        for future in as_completed(futures):
            results.append(future.result())

    return {
        "asOf": _now_utc().isoformat(),
        "pipelineVersion": "v4",
        "totalDeals": len(deals),
        "reviewed": len([r for r in results if "error" not in r]),
        "errors": len([r for r in results if "error" in r]),
        "results": results,
    }


async def async_run_all_deals_deep_review_v4(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    force: bool = False,
    full_mode: bool = False,
) -> dict[str, Any]:
    """Async batch deep review — runs ALL deals in parallel via asyncio.gather.

    Each deal gets its own session and runs the full async DAG orchestrator.
    Concurrency is bounded by the per-deal LLM semaphore inside
    ``async_run_deal_deep_review_v4``.
    """
    from app.services.azure.pipeline_dispatch import update_deal_intelligence_status

    deals = list(
        db.execute(
            select(Deal).where(
                Deal.fund_id == fund_id,
                Deal.deal_folder_path.is_not(None),
            ),
        )
        .scalars()
        .all(),
    )

    SessionLocal = async_session_factory

    # Capture deal IDs before entering async — ORM objects are session-bound
    deal_ids = [(deal.id, fund_id) for deal in deals]

    async def _review_deal(deal_id: uuid.UUID) -> dict[str, Any]:
        session = SessionLocal()
        try:
            result = await async_run_deal_deep_review_v4(
                session,
                fund_id=fund_id,
                deal_id=deal_id,
                actor_id=actor_id,
                force=force,
                full_mode=full_mode,
            )
            if "error" not in result:
                update_deal_intelligence_status(
                    session,
                    deal_id=deal_id,
                    fund_id=fund_id,
                    status="READY",
                    generated_at=dt.datetime.now(dt.UTC),
                )
                session.commit()
                logger.info("V4_BATCH_READY deal_id=%s", deal_id)
            else:
                logger.warning(
                    "V4_BATCH_SOFT_ERROR deal_id=%s error=%s",
                    deal_id, result.get("error"),
                )
                try:
                    update_deal_intelligence_status(
                        session, deal_id=deal_id, fund_id=fund_id, status="FAILED",
                    )
                    session.commit()
                except Exception:
                    session.rollback()
            return result
        except Exception as exc:
            session.rollback()
            logger.warning("V4_BATCH_FAILED deal_id=%s error=%s", deal_id, type(exc).__name__)
            try:
                update_deal_intelligence_status(
                    session, deal_id=deal_id, fund_id=fund_id, status="FAILED",
                )
                session.commit()
            except Exception:
                session.rollback()
            return {"dealId": str(deal_id), "error": str(exc)}
        finally:
            session.close()

    raw_results = await asyncio.gather(
        *[_review_deal(did) for did, _fid in deal_ids],
        return_exceptions=True,
    )

    results: list[dict[str, Any]] = []
    for (did, _fid), raw in zip(deal_ids, raw_results, strict=False):
        if isinstance(raw, BaseException):
            logger.error("V4_BATCH_GATHER_EXCEPTION deal_id=%s error=%s", did, type(raw).__name__)
            results.append({"dealId": str(did), "error": str(raw)})
        else:
            results.append(raw)

    return {
        "asOf": _now_utc().isoformat(),
        "pipelineVersion": "v4-async",
        "totalDeals": len(deals),
        "reviewed": len([r for r in results if "error" not in r]),
        "errors": len([r for r in results if "error" in r]),
        "results": results,
    }
