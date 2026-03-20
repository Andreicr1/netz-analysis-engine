"""Deep review corpus building — evidence gathering, text extraction, and budget management."""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
)
from app.domains.credit.modules.deals.models import PipelineDeal as Deal  # pipeline domain
from app.services.blob_storage import blob_uri, download_bytes

logger = structlog.get_logger()

_TOTAL_BUDGET_CHARS = 300_000


# ---------------------------------------------------------------------------
# Deal context loader — enriches deal_fields from blob-stored JSON
# ---------------------------------------------------------------------------
_RAW_DOCS_CONTAINER = "investment-pipeline-intelligence"


def _load_deal_context_from_blob(
    deal: Deal,
    deal_fields: dict[str, Any],
) -> dict[str, Any]:
    """Download deal_context.json + fund_context.json from blob storage
    and merge rich structured metadata into deal_fields.

    This provides the LLM with vehicles, investment terms, key contacts,
    fund strategy, fee structure, and entity tree — information that
    exists in the deal room but is NOT stored in the DB Deal record.

    Returns the enriched deal_context dict (or empty dict on failure).
    """
    folder = (
        (deal.deal_folder_path or "").rstrip("/").split("/")[-1]
        if deal.deal_folder_path
        else deal.deal_name or ""
    )
    if not folder:
        return {}

    deal_ctx: dict[str, Any] = {}
    fund_ctx: dict[str, Any] = {}

    # ── Load deal_context.json ──────────────────────
    try:
        blob_path = f"{folder}/deal_context.json"
        data = download_bytes(blob_uri=blob_uri(_RAW_DOCS_CONTAINER, blob_path))
        deal_ctx = json.loads(data.decode("utf-8"))
        logger.info(
            "deal_context.loaded", blob=blob_path, keys=list(deal_ctx.keys()),
        )
    except Exception as exc:
        logger.debug("deal_context.unavailable", folder=folder, error=str(exc))

    # ── Load fund_context.json ──────────────────────
    try:
        blob_path = f"{folder}/fund_context.json"
        data = download_bytes(blob_uri=blob_uri(_RAW_DOCS_CONTAINER, blob_path))
        fund_ctx = json.loads(data.decode("utf-8"))
        logger.info(
            "fund_context.loaded", blob=blob_path, keys=list(fund_ctx.keys()),
        )
    except Exception as exc:
        logger.debug("fund_context.unavailable", folder=folder, error=str(exc))

    if not deal_ctx and not fund_ctx:
        return {}

    # ── Merge into deal_fields ──────────────────────
    # Investment context (commitment, target vehicle, liquidity terms, return targets)
    inv_ctx = deal_ctx.get("investment_context", {})
    if inv_ctx:
        deal_fields["target_vehicle"] = inv_ctx.get("target_vehicle", "")
        deal_fields["netz_vehicle"] = inv_ctx.get("netz_vehicle", "")
        deal_fields["subscription_structure"] = inv_ctx.get(
            "subscription_structure", "",
        )
        commitment = inv_ctx.get("commitment", {})
        if commitment:
            deal_fields["commitment_usd"] = commitment.get(
                "amount_usd",
            ) or commitment.get("target_max_usd")
            deal_fields["portfolio_weight_max"] = commitment.get(
                "portfolio_weight_max", "",
            )
        deal_fields["liquidity_terms"] = inv_ctx.get("liquidity_terms", {})
        deal_fields["return_target"] = inv_ctx.get("return_target", {})
        deal_fields["investment_status"] = inv_ctx.get("status", "")

    # Deal-level fields
    # ── Deal Role Map ──────────────────────────────────────────────
    # Supports TWO schemas:
    #   Fund deals   → deal_ctx has "manager" (external GP/sponsor)
    #   Loan deals   → deal_ctx has "borrower" + "lender" (no manager)
    # The role map is injected into deal_fields so the LLM gets
    # unambiguous, pre-computed entity-role assignments.
    deal_role_map: dict[str, Any] = {}
    deal_type_raw = deal_ctx.get("deal_type", "")

    if deal_ctx.get("borrower") or deal_ctx.get("lender"):
        # Loan-type deal — NO external manager/sponsor
        deal_role_map = {
            "deal_structure": "direct_loan",
            "borrower": deal_ctx.get("borrower", ""),
            "lender": deal_ctx.get("lender", ""),
            "manager": None,
            "note": (
                "This is a DIRECT LOAN, not a fund investment. "
                "There is NO external manager or sponsor. "
                "The lender deploys capital directly to the borrower."
            ),
        }
        # Do NOT set sponsor_name for loan-type deals — there is no
        # external sponsor.  The lender is on the INVESTOR side.
        deal_fields["borrower"] = deal_ctx.get("borrower", "")
        deal_fields["lender"] = deal_ctx.get("lender", "")
        logger.info(
            "deal_role_map.direct_loan",
            borrower=deal_ctx.get("borrower", "")[:60],
            lender=deal_ctx.get("lender", "")[:60],
        )
    elif deal_ctx.get("manager"):
        # Fund-type deal — external manager/sponsor
        deal_role_map = {
            "deal_structure": "fund_investment",
            "manager": deal_ctx["manager"],
            "borrower": None,
            "lender": None,
            "note": (
                "This is a FUND INVESTMENT. The manager/sponsor is the "
                "EXTERNAL counterparty managing the target vehicle."
            ),
        }
        deal_fields["sponsor_name"] = deal_ctx["manager"]

    if deal_role_map:
        deal_fields["deal_role_map"] = deal_role_map
    if deal_type_raw:
        deal_fields["deal_type"] = deal_type_raw

    # ── Third-Party Counterparties ─────────────────────────────────
    # Pre-existing lending relationships with OTHER parties.
    # Documents from these counterparties must NOT be treated as the
    # deal under review — their terms belong to a separate arrangement.
    third_parties = deal_ctx.get("third_party_counterparties", [])
    if third_parties:
        deal_fields["third_party_counterparties"] = third_parties
        tp_names = [tp.get("name", "?") for tp in third_parties]
        logger.info(
            "third_party_counterparties.loaded",
            count=len(third_parties),
            names=tp_names,
        )

    if deal_ctx.get("geography"):
        deal_fields["geography"] = deal_ctx["geography"]
    if deal_ctx.get("strategy_type"):
        deal_fields["strategy_type"] = deal_ctx["strategy_type"]
    if deal_ctx.get("description"):
        deal_fields["deal_description"] = deal_ctx["description"]

    # Vehicles (full structure tree)
    if deal_ctx.get("vehicles"):
        deal_fields["vehicles"] = deal_ctx["vehicles"]

    # Folder structure (helps LLM understand document org)
    if deal_ctx.get("folder_structure"):
        deal_fields["folder_structure"] = deal_ctx["folder_structure"]

    # Fund context fields
    if fund_ctx.get("fund_strategy"):
        deal_fields["fund_strategy"] = fund_ctx["fund_strategy"]
    if fund_ctx.get("fund_jurisdiction"):
        deal_fields["fund_jurisdiction"] = fund_ctx["fund_jurisdiction"]
    if fund_ctx.get("key_terms"):
        deal_fields["key_terms"] = fund_ctx["key_terms"]
    if fund_ctx.get("entities"):
        deal_fields["entities"] = fund_ctx["entities"]
    if fund_ctx.get("validated_vehicles"):
        deal_fields["validated_vehicles"] = fund_ctx["validated_vehicles"]
    if fund_ctx.get("fund_entity_name"):
        deal_fields["fund_entity_name"] = fund_ctx["fund_entity_name"]

    # Build combined deal_context for EvidencePack injection
    combined = {
        "deal_context": deal_ctx,
        "fund_context": {
            k: v
            for k, v in fund_ctx.items()
            if k not in ("bootstrap_version", "candidate_fund_names")
        },
    }

    logger.info(
        "deal_context.enriched",
        deal=deal_fields.get("deal_name", ""),
        added_fields=sum(
            1
            for k in (
                "vehicles",
                "key_terms",
                "entities",
                "liquidity_terms",
                "return_target",
                "fund_strategy",
                "geography",
            )
            if deal_fields.get(k)
        ),
    )

    return combined


def _gather_deal_texts(
    db: Session, *, fund_id: uuid.UUID, deal: Deal,
    organization_id: uuid.UUID | str,
) -> dict[str, Any]:
    """IC-Grade retrieval — per-chapter specialized evidence assembly.

    Architecture (Underwriting Standard v1 — IC_GRADE_V1):
        1. Each chapter fires its own specialized query set via
           ``CHAPTER_QUERY_MAP`` (no generic global queries).
        2. Per-chapter dedup by (blob_name, chunk_index) with global
           dedup pool across chapters.
        3. IC-Grade coverage reranking:
           - DEPTH_FREE = 4 chunks per doc → bonus = 0 (semantic pure)
           - After DEPTH_FREE: bonus = LAMBDA / sqrt(freq - DEPTH_FREE + 1)
           → Semantic reranker score is PRIMARY authority.
           → Coverage is a small corrective, never dominant.
        4. Evidence saturation enforcement per chapter.
        5. Provenance validation — chunks without required fields discarded.
        6. Structured retrieval audit artifact for governance.

    Returns:
        {
            "corpus_text": str,
            "evidence_map": [provenance dicts],
            "raw_chunks": [full-content dicts],
            "chapter_evidence": {ch_key: {...}},
            "retrieval_audit": {structured audit artifact},
            "saturation_report": {gaps, missing_document_classes, all_saturated},
        }

    """
    from vertical_engines.credit.memo import CHAPTER_REGISTRY
    from vertical_engines.credit.retrieval import (
        RETRIEVAL_POLICY_NAME,
        build_ic_corpus,
        build_retrieval_audit,
        enforce_evidence_saturation,
        gather_chapter_evidence,
    )

    deal_name = deal.deal_name or deal.title or ""
    f_id = str(fund_id)
    d_id = str(deal.id)
    org_id = str(organization_id)

    logger.info(
        "ic_grade_retrieval.start",
        deal=deal_name,
        policy=RETRIEVAL_POLICY_NAME,
        chapters=len(CHAPTER_REGISTRY),
        fund_id=f_id,
        deal_id=d_id,
    )

    # ── Per-chapter specialized retrieval (parallel) ──────────────
    from concurrent.futures import ThreadPoolExecutor

    chapter_evidence: dict[str, dict] = {}

    def _fetch_chapter(args):
        _order, ch_key, ch_title = args
        return ch_key, gather_chapter_evidence(
            chapter_key=ch_key,
            deal_name=deal_name,
            fund_id=f_id,
            deal_id=d_id,
            organization_id=org_id,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        for ch_key, ch_result in executor.map(_fetch_chapter, CHAPTER_REGISTRY):
            chapter_evidence[ch_key] = ch_result

    for ch_key, ch_result in chapter_evidence.items():
        logger.info(
            "ic_chapter_evidence.complete",
            chapter=ch_key,
            status=ch_result["coverage_status"],
            chunks=ch_result["stats"]["chunk_count"],
            docs=ch_result["stats"]["unique_docs"],
        )

    # ── Build IC-grade corpus (coverage reranking) ────────────────
    corpus_result = build_ic_corpus(chapter_evidence)

    # ── Evidence saturation enforcement ───────────────────────────
    saturation_result = enforce_evidence_saturation(
        corpus_result["chapter_stats"],
    )
    saturation_report = saturation_result.to_dict()

    # ── Build audit artifact ──────────────────────────────────────
    retrieval_audit = build_retrieval_audit(
        fund_id=f_id,
        deal_id=d_id,
        chapter_evidence=chapter_evidence,
        corpus_result=corpus_result,
        saturation_report=saturation_report,
    )

    corpus = corpus_result["corpus_text"]
    evidence_map = corpus_result["evidence_map"]
    raw_chunks = corpus_result["raw_chunks"]

    if corpus and len(corpus.strip()) >= 200:
        return {
            "corpus_text": corpus,
            "evidence_map": evidence_map,
            "raw_chunks": raw_chunks,
            "chapter_evidence": chapter_evidence,
            "retrieval_audit": retrieval_audit,
            "saturation_report": saturation_report,
        }

    # No indexed chunks — return empty corpus with warning
    logger.warning(
        "rag_empty.no_indexed_chunks",
        deal_id=d_id,
        fund_id=f_id,
        entity_type="deal",
    )
    return {
        "corpus_text": "",
        "evidence_map": [],
        "raw_chunks": [],
        "chapter_evidence": {},
        "retrieval_audit": retrieval_audit,
        "saturation_report": saturation_report,
    }


def _gather_investment_texts(
    db: Session, *, fund_id: uuid.UUID, investment: ActiveInvestment,
    organization_id: uuid.UUID | str,
) -> str:
    """Retrieve investment document content via RAG retrieval.

    Returns empty string if no indexed chunks exist.
    """
    from ai_engine.extraction.embedding_service import generate_embeddings
    from ai_engine.extraction.pgvector_search_service import (
        search_and_rerank_deal_sync as search_deal_chunks,
    )

    inv_name = investment.investment_name or ""

    # ── RAG retrieval (primary) ───────────────────────────────────
    try:
        query_text = f"{inv_name} covenant compliance performance monitoring risk"
        emb = generate_embeddings([query_text])
        query_vector = emb.vectors[0] if emb.vectors else None
    except Exception:
        query_vector = None
        query_text = inv_name

    try:
        investment_deal_id = investment.deal_id or investment.id
        result = search_deal_chunks(
            deal_id=investment_deal_id,
            organization_id=organization_id,
            query_text=query_text,
            query_vector=query_vector,
            candidates=120,
            top=80,
        )
        chunks = result.chunks
    except Exception:
        logger.warning(
            "rag_retrieval.failed",
            investment_id=str(investment.id),
            exc_info=True,
        )
        chunks = []

    if chunks:
        parts: list[str] = []
        total = 0
        for i, chunk in enumerate(chunks):
            content = chunk.get("content", "")
            remaining = _TOTAL_BUDGET_CHARS - total
            if remaining <= 0:
                break
            snippet = content[:remaining]
            header = (
                f"--- Excerpt {i + 1} | {chunk.get('doc_type', 'unknown')} "
                f"| pages {chunk.get('page_start', '?')}-{chunk.get('page_end', '?')} ---"
            )
            parts.append(f"{header}\n{snippet}")
            total += len(snippet)
        return "\n\n".join(parts)

    # No indexed chunks — return empty string with warning
    logger.warning(
        "rag_empty.no_indexed_chunks",
        investment_id=str(investment.id),
        fund_id=str(fund_id),
        entity_type="investment",
    )
    return ""


__all__ = [
    "_gather_deal_texts",
    "_gather_investment_texts",
    "_load_deal_context_from_blob",
]
