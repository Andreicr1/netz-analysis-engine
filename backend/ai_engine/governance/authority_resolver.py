from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    DocumentClassification,
    DocumentGovernanceProfile,
    DocumentRegistry,
)

logger = logging.getLogger(__name__)


AUTHORITY_RANK = {
    "NARRATIVE": 1,
    "INTELLIGENCE": 2,
    "EVIDENCE": 3,
    "POLICY": 4,
    "BINDING": 5,
}

DOC_TYPE_AUTHORITY_OVERRIDE = {
    "REGULATORY_CIMA": "BINDING",
    "FUND_CONSTITUTIONAL": "BINDING",
    "SERVICE_PROVIDER_CONTRACT": "BINDING",
    "INVESTOR_NARRATIVE": "NARRATIVE",
    "DEAL_MARKETING": "NARRATIVE",
}


# ══════════════════════════════════════════════════════════════════════
#  Institutional Issuer Registry — for evidence-weight enrichment
# ══════════════════════════════════════════════════════════════════════

INSTITUTIONAL_ISSUERS: list[dict[str, Any]] = [
    # Big Four audit / advisory
    {"pattern": r"\bpwc\b|pricewaterhousecoopers", "issuer": "PwC", "tier": "EVIDENCE", "category": "audit"},
    {"pattern": r"\b(?:ernst\s*&?\s*young|e\s*&?\s*y)\b", "issuer": "EY", "tier": "EVIDENCE", "category": "audit"},
    {"pattern": r"\bdeloitte\b", "issuer": "Deloitte", "tier": "EVIDENCE", "category": "audit"},
    {"pattern": r"\bkpmg\b", "issuer": "KPMG", "tier": "EVIDENCE", "category": "audit"},
    {"pattern": r"\bbdo\b", "issuer": "BDO", "tier": "EVIDENCE", "category": "audit"},
    {"pattern": r"\bgrant\s+thornton\b", "issuer": "Grant Thornton", "tier": "EVIDENCE", "category": "audit"},
    {"pattern": r"\brsm\b", "issuer": "RSM", "tier": "EVIDENCE", "category": "audit"},
    # Rating agencies
    {"pattern": r"\bmoody'?s\b", "issuer": "Moody's", "tier": "INTELLIGENCE", "category": "rating_agency"},
    {"pattern": r"\bs\s*&?\s*p\s+global|standard\s*&?\s*poor", "issuer": "S&P Global", "tier": "INTELLIGENCE", "category": "rating_agency"},
    {"pattern": r"\bfitch\s+ratings?\b", "issuer": "Fitch Ratings", "tier": "INTELLIGENCE", "category": "rating_agency"},
    {"pattern": r"\bdbrs\b|morningstar\s+dbrs", "issuer": "DBRS Morningstar", "tier": "INTELLIGENCE", "category": "rating_agency"},
    # Law firms
    {"pattern": r"\bclifford\s+chance\b", "issuer": "Clifford Chance", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\blinklaters?\b", "issuer": "Linklaters", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\ballen\s*&?\s*overy\b|a\s*&?\s*o\s+shearman\b", "issuer": "A&O Shearman", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bfreshfields?\b", "issuer": "Freshfields", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\blatham\s*&?\s*watkins\b", "issuer": "Latham & Watkins", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bkirkland\s*&?\s*ellis\b", "issuer": "Kirkland & Ellis", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bdechert\b", "issuer": "Dechert", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bwalkers?\b(?:\s+global)?\b", "issuer": "Walkers", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bmaples?\s+group\b|maples\s+and\s+calder\b", "issuer": "Maples Group", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bogier\b", "issuer": "Ogier", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bsidley\s+austin\b", "issuer": "Sidley Austin", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bdavis\s+polk\b", "issuer": "Davis Polk", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bsimpson\s+thacher\b", "issuer": "Simpson Thacher", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bskadden\b", "issuer": "Skadden", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bwhite\s*&?\s*case\b", "issuer": "White & Case", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bcadwalader\b", "issuer": "Cadwalader", "tier": "BINDING", "category": "legal"},
    {"pattern": r"\bmilbank\b", "issuer": "Milbank", "tier": "BINDING", "category": "legal"},
    # Administrators / custodians
    {"pattern": r"\bcitco\b", "issuer": "Citco", "tier": "EVIDENCE", "category": "administrator"},
    {"pattern": r"\bss\s*&?\s*c\b|state\s+street", "issuer": "State Street", "tier": "EVIDENCE", "category": "administrator"},
    {"pattern": r"\bnt\s+northern\s+trust|northern\s+trust\b", "issuer": "Northern Trust", "tier": "EVIDENCE", "category": "administrator"},
    {"pattern": r"\bbnp\s+paribas\b", "issuer": "BNP Paribas", "tier": "EVIDENCE", "category": "administrator"},
    # Regulators
    {"pattern": r"\bcima\b|cayman\s+islands\s+monetary", "issuer": "CIMA", "tier": "BINDING", "category": "regulator"},
    {"pattern": r"\bfca\b|financial\s+conduct\s+authority", "issuer": "FCA", "tier": "BINDING", "category": "regulator"},
    {"pattern": r"\bsec\b|securities\s+and\s+exchange\s+commission", "issuer": "SEC", "tier": "BINDING", "category": "regulator"},
    # Valuation agents
    {"pattern": r"\bhoulihan\s+lokey\b", "issuer": "Houlihan Lokey", "tier": "EVIDENCE", "category": "valuation"},
    {"pattern": r"\bduff\s*&?\s*phelps\b|kroll\b", "issuer": "Kroll (Duff & Phelps)", "tier": "EVIDENCE", "category": "valuation"},
    {"pattern": r"\bcushman\s*&?\s*wakefield\b", "issuer": "Cushman & Wakefield", "tier": "EVIDENCE", "category": "valuation"},
    {"pattern": r"\bcbre\b", "issuer": "CBRE", "tier": "EVIDENCE", "category": "valuation"},
    {"pattern": r"\bjll\b|jones\s+lang\s+lasalle\b", "issuer": "JLL", "tier": "EVIDENCE", "category": "valuation"},
]

# Pre-compile patterns for performance
_COMPILED_ISSUERS = [
    {**entry, "_re": re.compile(entry["pattern"], re.IGNORECASE)}
    for entry in INSTITUTIONAL_ISSUERS
]


def detect_chunk_issuer(chunk: dict[str, Any]) -> dict[str, Any] | None:
    """Detect institutional issuer from chunk metadata and first 600 chars.

    Returns dict with issuer, tier, category or None if no match.
    """
    title = chunk.get("title", "") or ""
    doc_type = chunk.get("doc_type", "") or ""
    content_preview = (chunk.get("content", "") or "")[:600]
    haystack = f"{title} {doc_type} {content_preview}"

    for entry in _COMPILED_ISSUERS:
        if entry["_re"].search(haystack):
            return {
                "issuer": entry["issuer"],
                "tier": entry["tier"],
                "category": entry["category"],
            }
    return None


def enrich_chunks_with_authority(
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Annotate each chunk with institutional issuer and authority tier.

    Returns:
        enriched_chunks: original chunks with added issuer_* fields
        issuer_summary: {category: [unique issuer names]} for prompt injection

    """
    issuer_summary: dict[str, set[str]] = {}
    enriched: list[dict[str, Any]] = []

    for chunk in chunks:
        c = dict(chunk)
        detection = detect_chunk_issuer(c)
        if detection:
            c["issuer_name"] = detection["issuer"]
            c["issuer_tier"] = detection["tier"]
            c["issuer_category"] = detection["category"]
            cat = detection["category"]
            issuer_summary.setdefault(cat, set()).add(detection["issuer"])
        else:
            c["issuer_name"] = None
            c["issuer_tier"] = None
            c["issuer_category"] = None
        enriched.append(c)

    # Convert sets to sorted lists for JSON serialisation
    summary_out = {k: sorted(v) for k, v in issuer_summary.items()}
    return enriched, summary_out


def _resolve_authority(container_authority: str, doc_type: str) -> str:
    container_level = container_authority if container_authority in AUTHORITY_RANK else "EVIDENCE"
    override = DOC_TYPE_AUTHORITY_OVERRIDE.get(doc_type)

    if override is None:
        return container_level

    if container_level == "INTELLIGENCE" and override == "BINDING":
        return "INTELLIGENCE"

    return max([container_level, override], key=lambda value: AUTHORITY_RANK[value])


def _binding_scope(doc_type: str) -> str:
    if doc_type in {"REGULATORY_CIMA", "FUND_CONSTITUTIONAL", "RISK_POLICY_INTERNAL"}:
        return "FUND"
    if doc_type == "SERVICE_PROVIDER_CONTRACT":
        return "SERVICE_PROVIDER"
    if doc_type in {"INVESTMENT_MEMO", "DEAL_MARKETING"}:
        return "MANAGER"
    return "FUND"


def _jurisdiction(doc: DocumentRegistry, classification: DocumentClassification) -> str | None:
    source = f"{doc.container_name} {doc.blob_path} {classification.doc_type}".lower()
    if "cima" in source or "cayman" in source:
        return "Cayman Islands"
    if "uk" in source:
        return "United Kingdom"
    if "us" in source:
        return "United States"
    return None


def resolve_authority_profiles(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[DocumentGovernanceProfile]:
    rows = list(
        db.execute(
            select(DocumentRegistry, DocumentClassification)
            .join(DocumentClassification, DocumentClassification.doc_id == DocumentRegistry.id)
            .where(
                DocumentRegistry.fund_id == fund_id,
                DocumentClassification.fund_id == fund_id,
            ),
        ).all(),
    )

    existing_profiles = {
        p.doc_id: p
        for p in db.execute(
            select(DocumentGovernanceProfile).where(
                DocumentGovernanceProfile.fund_id == fund_id,
            ),
        ).scalars().all()
    }

    saved: list[DocumentGovernanceProfile] = []
    for document, classification in rows:
        resolved = _resolve_authority(document.authority, classification.doc_type)
        profile_payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "doc_id": document.id,
            "resolved_authority": resolved,
            "binding_scope": _binding_scope(classification.doc_type),
            "shareability_final": document.shareability,
            "jurisdiction": _jurisdiction(document, classification),
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        existing = existing_profiles.get(document.id)

        if existing is None:
            row = DocumentGovernanceProfile(**profile_payload)
            db.add(row)
            db.flush()
        else:
            for key, value in profile_payload.items():
                if key == "created_by":
                    continue
                setattr(existing, key, value)
            row = existing
            db.flush()

        saved.append(row)

    db.commit()
    return saved
