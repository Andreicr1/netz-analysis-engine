"""
memo_evidence_pack.py

Tier-1 EvidencePack builder for Deep Review V4.

Purpose
-------
Build a frozen, audit-safe evidence surface for Investment Memorandum
generation.  **No budget compression** — all institutional evidence is
passed through at full fidelity to maximise analysis quality.

Design Principles
-----------------
- EvidencePack is the ONLY factual substrate allowed into memo chapters.
- No chapter may see raw RAG dumps or unbounded chunk streams.
- No artificial slicing (e.g. "top 10 only") is permitted.
- NO token-budget compression is applied.  Full-context fidelity is
  required for institutional-grade analysis.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid as _uuid
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 3.5  # conservative English finance baseline


def _estimate_tokens(text: str) -> int:
    """Approximate token count from char length."""
    if not text:
        return 0
    return int(len(text) / _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------
# EvidencePack Builder (Public)
# ---------------------------------------------------------------------

def build_evidence_pack(
    *,
    analysis: dict[str, Any],
    quant_dict: dict[str, Any] | None = None,
    concentration_dict: dict[str, Any] | None = None,
    policy_dict: dict[str, Any] | None = None,
    macro_snapshot: dict[str, Any] | None = None,
    sponsor_output: dict[str, Any] | None = None,
    deal_fields: dict[str, Any] | None = None,
    evidence_map: list[dict[str, Any]] | None = None,
    market_benchmarks: list[dict[str, Any]] | None = None,
    curated_surfaces_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a frozen EvidencePack for Deep Review V4.

    **No compression or truncation** — every section is passed through
    at full fidelity so the LLM has the richest possible context for
    each memo chapter.

    Parameters
    ----------
    analysis : dict
        Stage-3 structured analysis from _call_openai.
    quant_dict : dict | None
        Quant-engine output (IRR, DSCR, LTV, …).
    concentration_dict : dict | None
        Concentration-engine output.
    policy_dict : dict | None
        Policy-compliance output.
    macro_snapshot : dict | None
        FRED-sourced macro fields.
    sponsor_output : dict | None
        Sponsor & key-person engine output.
    deal_fields : dict | None
        Lightweight deal metadata.
    evidence_map : list[dict] | None
        RAG evidence chunks with provenance metadata.
    market_benchmarks : list[dict] | None
        Structured benchmark chunks from market-data-index (PitchBook, Preqin,
        Bloomberg, etc.).  Each dict contains content + fields: publisher,
        reference_date, asset_class, sub_strategy, vintage_year, metric_type.
        Used to ground ch08 (Return Modeling) and ch12 (Peer Comparison) with
        authoritative third-party data.
    curated_surfaces_meta : dict | None
        Curation metadata from the evidence_selector dual-surface pipeline.
        Records which curated chunks were used per chapter for traceability.
        Contains per-chapter: governance_chunks_used, terms_chunks_used, etc.
    """

    deal_fields = deal_fields or {}
    investment_terms = analysis.get("investmentTerms", {}) if isinstance(analysis, dict) else {}
    if not isinstance(investment_terms, dict):
        investment_terms = {}

    # -----------------------------------------------------------------
    # 1. Evidence Anchors (Appendix-1 provenance) — ALL chunks kept
    # -----------------------------------------------------------------
    citations: list[dict[str, Any]] = []
    if evidence_map:
        for e in evidence_map:
            citations.append({
                "blob_name": e.get("blob_name", ""),
                "doc_type": e.get("doc_type", ""),
                "page_start": e.get("page_start"),
                "page_end": e.get("page_end"),
                "chunk_id": e.get("chunk_id"),
                "score": e.get("score"),
            })

    # -----------------------------------------------------------------
    # 2. Assemble EvidencePack — FULL FIDELITY, NO COMPRESSION
    # -----------------------------------------------------------------

    # ── INVESTOR IDENTITY — anti-confusion guard ───────────────
    # This block clearly identifies Netz as the INVESTING fund so
    # chapter LLMs never confuse it with the deal sponsor/borrower.
    investor_identity = {
        "fund_name": "Netz Private Credit Fund",
        "role": "INVESTOR — this is OUR fund. It is NOT the deal sponsor, manager, or borrower.",
        "sponsor_of_fund": "Netz Asset Gestão de Recursos LTDA (Brazil)",
        "investment_manager": "Necker Finance (Suisse) SA",
        "administrator": "Zedra Fund Administration (Cayman) Ltd.",
        "vehicles": [
            "Netz Private Credit Fund",
            "WMF Corp",
            "Netz Private Credit US Blocker",
        ],
        "disambiguation_rule": (
            "Any document referencing 'Netz Private Credit Fund', 'Netz Asset Gestão', "
            "'Necker Finance', 'Zedra Fund Administration', 'WMF Corp', or "
            "'Netz Private Credit US Blocker' is describing the INVESTOR SIDE "
            "of the transaction. The DEAL SPONSOR / MANAGER is the EXTERNAL "
            "counterparty identified in deal_identity.sponsor_name. "
            "NEVER identify any Netz entity as the deal sponsor."
        ),
    }

    # ── DEAL ROLE MAP — pre-computed entity-role assignments ──────
    # Injected from deal_context.json via deep_review loader.
    # Provides unambiguous Borrower / Lender / Manager classification.
    deal_role_map = deal_fields.get("deal_role_map", {})
    if deal_role_map:
        investor_identity["deal_role_map"] = deal_role_map
        # For direct loan deals, reinforce that the lender is on the
        # investor side and is NOT the deal sponsor.
        if deal_role_map.get("deal_structure") == "direct_loan":
            investor_identity["disambiguation_rule"] = (
                "This is a DIRECT LOAN deal. "
                f"BORROWER (deal target): {deal_role_map.get('borrower', 'unknown')}. "
                f"LENDER (investor side): {deal_role_map.get('lender', 'unknown')}. "
                "There is NO external manager or sponsor. "
                "The lender entity is a Netz subsidiary deploying capital. "
                "NEVER call the lender the 'Borrower'. "
                "NEVER call the borrower the 'Lender'. "
                "NEVER identify any Netz entity as the deal sponsor."
            )

    # ── THIRD-PARTY COUNTERPARTIES — document attribution guard ──
    # Pre-existing lending relationships with OTHER parties whose
    # documents are in the evidence corpus.  Their terms must NOT be
    # presented as the deal under review.
    third_parties = deal_fields.get("third_party_counterparties", [])
    if third_parties:
        investor_identity["third_party_counterparties"] = third_parties
        tp_warning_parts = []
        for tp in third_parties:
            tp_name = tp.get("name", "unknown")
            tp_docs = tp.get("documents", []) + tp.get("ucc_filings", [])
            tp_warning_parts.append(
                f"{tp_name} (docs: {', '.join(tp_docs[:6])})"
            )
        investor_identity["third_party_attribution_rule"] = (
            "CRITICAL — THIRD-PARTY DOCUMENT ATTRIBUTION: "
            "The evidence corpus contains documents from OTHER counterparties "
            "that have SEPARATE contracts with the borrower. "
            f"Known third-party counterparties: {'; '.join(tp_warning_parts)}. "
            "Terms extracted from these documents (interest rates, fees, "
            "covenants, security pledges) belong to THOSE separate arrangements, "
            "NOT to the deal under review. Present them as 'Existing Debt / "
            "Prior Liens' risk factors. Match source document filenames against "
            "the third-party document list to determine attribution."
        )

    pack: dict[str, Any] = {
        # Investor identity — anti-confusion guard (MUST be read first)
        "investor_identity": investor_identity,
        # Deal identity — the EXTERNAL counterparty being evaluated
        "deal_identity": deal_fields,
        # Analysis core
        "deal_overview": analysis,
        # Quant & concentration
        "quant_profile": quant_dict or {},
        "concentration_profile": concentration_dict or {},
        # Policy
        "policy_compliance": policy_dict or {},
        # Macro
        "macro_snapshot": macro_snapshot or {},
        # Sponsor
        "sponsor_analysis": sponsor_output or {},
        # Structured investment terms for confidence/eval consumers
        "investment_terms": investment_terms,
        # Terms extracted from analysis (preserving nested structure)
        "terms_summary": {
            "collateral": analysis.get("collateral", ""),
            "covenants": analysis.get("covenants", ""),
            "pricing_terms": analysis.get("pricingTerms", ""),
            "maturity_profile": analysis.get("maturityProfile", ""),
        },
        # Risk flags
        "risk_flags": analysis.get("keyRisks", []),
        # Evidence provenance
        "citations": citations,
        # Market benchmarks (PitchBook / Preqin / Bloomberg)
        "market_benchmarks": market_benchmarks or [],
        "market_benchmark_meta": _build_benchmark_meta(market_benchmarks),
        # Curated surfaces traceability (dual-surface architecture)
        "curated_surfaces_meta": curated_surfaces_meta or {},
    }

    return pack


def _build_benchmark_meta(benchmarks: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Derive summary metadata from the market_benchmarks list.

    Returns a compact dict used by chapter prompts to understand the
    breadth of benchmark coverage without iterating all chunks.
    """
    if not benchmarks:
        return {"count": 0, "publishers": [], "reference_dates": [], "asset_classes": []}

    publishers: list[str] = sorted({
        b.get("publisher", "") for b in benchmarks if b.get("publisher")
    })
    reference_dates: list[str] = sorted({
        b.get("reference_date", "") for b in benchmarks if b.get("reference_date")
    }, reverse=True)
    asset_classes: list[str] = sorted({
        b.get("asset_class", "") for b in benchmarks if b.get("asset_class")
    })
    vintage_years: list[str] = sorted({
        str(b.get("vintage_year", "")) for b in benchmarks if b.get("vintage_year")
    }, reverse=True)

    return {
        "count": len(benchmarks),
        "publishers": publishers,
        "reference_dates": reference_dates[:5],   # most recent 5
        "asset_classes": asset_classes,
        "vintage_years": vintage_years[:5],
    }


# ---------------------------------------------------------------------
# compress_to_budget  (NO-OP — kept for backward-compat imports)
# ---------------------------------------------------------------------

def compress_to_budget(
    pack: dict[str, Any],
    *,
    max_tokens: int = 999_999,
) -> dict[str, Any]:
    """Legacy API — returns pack unchanged.  Budget compression has been
    disabled to preserve full-context analysis quality.
    """
    return pack


# ---------------------------------------------------------------------
# EvidencePack Validation (Public)
# ---------------------------------------------------------------------

def validate_evidence_pack(pack: dict[str, Any]) -> None:
    """Institutional validator.

    Ensures EvidencePack is structurally safe before memo generation.
    Accepts both the V4 shape (deal_identity / deal_overview) and the
    legacy shape (deal_id / executive_summary).

    Raises
    ------
    ValueError  if required surfaces are missing.
    """
    if not pack:
        raise ValueError("EvidencePack is empty")

    # Accept either V4 or legacy key sets
    has_v4_keys = "deal_overview" in pack or "deal_identity" in pack
    has_legacy_keys = "deal_id" in pack or "executive_summary" in pack

    if not has_v4_keys and not has_legacy_keys:
        raise ValueError(
            "EvidencePack missing required fields: "
            "need deal_overview/deal_identity (V4) or deal_id/executive_summary (legacy)"
        )

    if not isinstance(pack.get("citations", []), list):
        raise ValueError("EvidencePack citations must be a list")


# ---------------------------------------------------------------------
# persist_evidence_pack  (DB persistence)
# ---------------------------------------------------------------------

def persist_evidence_pack(
    db: Session,
    *,
    fund_id: _uuid.UUID,
    deal_id: _uuid.UUID,
    pack: dict[str, Any],
    version_tag: str,
    model_version: str,
    actor_id: str,
) -> Any:
    """Persist a frozen EvidencePack to the ``memo_evidence_packs`` table.

    Returns the SQLAlchemy row (has ``.id`` and ``.token_count``).
    """
    from app.domains.credit.modules.ai.models import MemoEvidencePack

    # Estimate tokens from serialised JSON (no compression)
    serialized = json.dumps(pack, default=str)
    token_count = _estimate_tokens(serialized)

    # ── Unset is_current on previous packs for this deal ─────────
    from sqlalchemy import update as _sa_update
    db.execute(
        _sa_update(MemoEvidencePack)
        .where(
            MemoEvidencePack.fund_id == fund_id,
            MemoEvidencePack.deal_id == deal_id,
            MemoEvidencePack.is_current == True,  # noqa: E712
        )
        .values(is_current=False)
    )

    row = MemoEvidencePack(
        fund_id=fund_id,
        deal_id=deal_id,
        version_tag=version_tag,
        evidence_json=pack,
        token_count=token_count,
        generated_at=dt.datetime.now(dt.UTC),
        model_version=model_version,
        is_current=True,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    db.flush()

    logger.info(
        "EVIDENCE_PACK_PERSISTED pack_id=%s tokens=%d version=%s",
        row.id, row.token_count, version_tag,
    )
    return row
