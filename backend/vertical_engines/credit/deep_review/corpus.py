"""Deep review corpus building — evidence gathering, text extraction, and budget management."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    DocumentRegistry,
)
from app.domains.credit.modules.deals.models import PipelineDeal as Deal  # pipeline domain
from app.services.blob_storage import blob_uri, download_bytes
from app.services.text_extract import extract_text_from_docx, extract_text_from_pdf
from vertical_engines.credit.deep_review.helpers import _MODEL, _now_utc, _trunc  # noqa: F401

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Sectional token budget (Task 6 — Pre-V3 Hardening)
# ---------------------------------------------------------------------------
# Total ~120 000 chars (~30 k tokens).  Split by section priority so that
# financial/legal context (most critical for IC decisions) gets the largest
# share, followed by risk/covenants, then market/strategy.
_TOTAL_BUDGET_CHARS = 300_000
_BUDGET_FINANCIAL_LEGAL = int(_TOTAL_BUDGET_CHARS * 0.40)  # 120 000
_BUDGET_RISK_COVENANTS = int(_TOTAL_BUDGET_CHARS * 0.30)  # 90 000
_BUDGET_MARKET_STRATEGY = int(_TOTAL_BUDGET_CHARS * 0.30)  # 90 000

# Doc-type classification for sectional budgeting
# ---------------------------------------------------------------------------
# Hard policy limits — now sourced from PolicyThresholds (policy_loader.py).
# Kept as backward-compat aliases for any external callers.
# Internal code uses policy.* instead.
# ---------------------------------------------------------------------------

_FINANCIAL_LEGAL_TYPES = frozenset(
    {
        "TERM_SHEET",
        "CREDIT_AGREEMENT",
        "FACILITY_AGREEMENT",
        "LOAN_AGREEMENT",
        "SECURITY_AGREEMENT",
        "INTERCREDITOR",
        "GUARANTEE",
        "PLEDGE",
        "SUBSCRIPTION_AGREEMENT",
        "SIDE_LETTER",
        "LEGAL",
        "FINANCIAL",
        "FINANCIAL_STATEMENTS",
        "FUND_POLICY",
        "FUND_CONSTITUTION",
    },
)
_RISK_COVENANT_TYPES = frozenset(
    {
        "RISK_ASSESSMENT",
        "COVENANT_COMPLIANCE",
        "COVENANT",
        "RISK",
        "COMPLIANCE",
        "REGULATORY",
        "REGULATORY_CIMA",
        "INSURANCE",
        "WATCHLIST",
        "MONITORING",
    },
)
# Anything else falls into market/strategy bucket


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------
_EXTRACTABLE_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv"}


def _extract_text_from_blob(container: str, blob_path: str) -> str:
    """Download blob and extract text.  Return empty string on failure.

    Skips unsupported file types (e.g. .mp4, .mp3, .xlsx) BEFORE
    downloading to avoid pulling large binaries into memory.
    """
    suffix = Path(blob_path).suffix.lower()
    if suffix not in _EXTRACTABLE_EXTENSIONS:
        logger.debug("blob.skip_unsupported", suffix=suffix, blob_path=blob_path)
        return ""
    try:
        data = download_bytes(blob_uri=blob_uri(container, blob_path))
    except Exception:
        return ""
    try:
        if suffix == ".pdf":
            return extract_text_from_pdf(data).text
        if suffix == ".docx":
            return extract_text_from_docx(data).text
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


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
        6. Structured retrieval audit artifact for compliance.

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
    from app.services.search_index import AzureSearchChunksClient
    from vertical_engines.credit.memo import CHAPTER_REGISTRY
    from vertical_engines.credit.retrieval import (
        RETRIEVAL_POLICY_NAME,
        build_ic_corpus,
        build_retrieval_audit,
        enforce_evidence_saturation,
        gather_chapter_evidence,
    )

    deal_name = deal.deal_name or deal.title or ""
    searcher = AzureSearchChunksClient()
    f_id = str(fund_id)
    d_id = str(deal.id)

    # ── Resolve actual index identifiers (v5 uses folder-derived fund_id)
    # Returns (fund_id, deal_id, scope_mode) — scope_mode indicates whether
    # the fund_id is shared across multiple deals (STRICT) or exclusive.
    f_id, d_id, scope_mode = searcher.resolve_index_scope(
        fund_id=f_id,
        deal_id=d_id,
        deal_name=deal_name,
        deal_folder_path=deal.deal_folder_path,
    )
    d_id = d_id or str(deal.id)

    # CU pipeline sets deal_name as deal_id in the index (indexer maps
    # /deal_name → deal_id).  Ensure d_id matches so the filter captures
    # enriched CU chunks.
    # SAFETY: With STRICT scope_mode, the AND clause prevents cross-deal
    # contamination even if fund_id is a shared parent entity.
    if deal_name:
        d_id = deal_name

    logger.info(
        "ic_grade_retrieval.start",
        deal=deal_name,
        policy=RETRIEVAL_POLICY_NAME,
        chapters=len(CHAPTER_REGISTRY),
        fund_id=f_id,
        deal_id=d_id,
        scope_mode=scope_mode,
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
            searcher=searcher,
            scope_mode=scope_mode,
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
    saturation_report = enforce_evidence_saturation(
        corpus_result["chapter_stats"],
        strict=False,  # Log warnings, don't abort
    )

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

    # ── Fallback: legacy blob download (only if no indexed chunks) ──
    logger.warning(
        "rag_empty.fallback_blob_download",
        deal_id=d_id,
        fund_id=f_id,
        entity_type="deal",
    )
    legacy_text = _gather_deal_texts_legacy(db, fund_id=fund_id, deal=deal)
    return {
        "corpus_text": legacy_text,
        "evidence_map": [],
        "raw_chunks": [],
        "chapter_evidence": {},
        "retrieval_audit": retrieval_audit,
        "saturation_report": saturation_report,
    }


def _classify_doc_type(doc_type: str) -> str:
    """Classify a doc_type string into a budget bucket (legacy — kept for compat)."""
    dt_upper = (doc_type or "").upper()
    if dt_upper in _FINANCIAL_LEGAL_TYPES:
        return "financial_legal"
    if dt_upper in _RISK_COVENANT_TYPES:
        return "risk_covenants"
    return "market_strategy"




def _gather_deal_texts_legacy(db: Session, *, fund_id: uuid.UUID, deal: Deal) -> str:
    """Legacy blob-based text gathering — fallback when RAG index has no
    chunks for this deal.  Will be removed once all deals are indexed."""
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == "investment-pipeline-intelligence",
            ),
        )
        .scalars()
        .all(),
    )
    folder = (
        (deal.deal_folder_path or "").split("/")[-1]
        if deal.deal_folder_path
        else deal.deal_name
    )
    parts: list[str] = []
    total = 0
    for doc in docs:
        if folder and folder.lower() not in (doc.blob_path or "").lower():
            continue
        text = _extract_text_from_blob(doc.container_name, doc.blob_path)
        if not text.strip():
            continue
        remaining = _TOTAL_BUDGET_CHARS - total
        if remaining <= 0:
            break
        chunk = text[:remaining]
        parts.append(f"--- Document: {doc.blob_path} ---\n{chunk}")
        total += len(chunk)
    return "\n\n".join(parts)


def _gather_investment_texts(
    db: Session, *, fund_id: uuid.UUID, investment: ActiveInvestment,
) -> str:
    """Retrieve investment document content via RAG retrieval.

    REFACTOR (Phase 2, Step 6): Same RAG-first approach as _gather_deal_texts.
    Falls back to blob download if no indexed chunks exist.
    """
    from ai_engine.extraction.embedding_service import generate_embeddings
    from ai_engine.extraction.search_upsert_service import search_deal_chunks

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
        chunks = search_deal_chunks(
            deal_id=investment_deal_id,
            query_text=query_text,
            query_vector=query_vector,
            top=80,
        )
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

    # ── Fallback: legacy blob download ────────────────────────────
    logger.warning(
        "rag_empty.fallback_blob_download",
        investment_id=str(investment.id),
        fund_id=str(fund_id),
        entity_type="investment",
    )
    return _gather_investment_texts_legacy(db, fund_id=fund_id, investment=investment)


def _gather_investment_texts_legacy(
    db: Session, *, fund_id: uuid.UUID, investment: ActiveInvestment,
) -> str:
    """Legacy blob-based text gathering for investments."""
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == investment.source_container,
            ),
        )
        .scalars()
        .all(),
    )
    folder = (
        investment.source_folder.split("/")[-1]
        if investment.source_folder
        else investment.investment_name
    )
    parts: list[str] = []
    total = 0
    for doc in docs:
        if folder and folder.lower() not in (doc.blob_path or "").lower():
            continue
        text = _extract_text_from_blob(doc.container_name, doc.blob_path)
        if not text.strip():
            continue
        remaining = _TOTAL_BUDGET_CHARS - total
        if remaining <= 0:
            break
        chunk = text[:remaining]
        parts.append(f"--- Document: {doc.blob_path} ---\n{chunk}")
        total += len(chunk)
    return "\n\n".join(parts)


__all__ = [
    "_gather_deal_texts",
    "_gather_investment_texts",
    "_load_deal_context_from_blob",
]
