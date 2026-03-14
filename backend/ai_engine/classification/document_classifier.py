"""Unified Document Classifier.

REFACTOR (Phase 2, Step 7): Merges the two previously separate classifiers
into a single module with a unified taxonomy:

  classifier.py        → keyword + folder heuristics → INSTITUTIONAL_TYPES
  doc_classifier.py    → content + container heuristics → DOC_TYPES

Unified taxonomy (7 canonical types):
  LEGAL           — LPAs, subscription docs, admin agreements, engagement letters
  REGULATORY      — CIMA filings, compliance manuals, regulatory submissions
  DD_REPORT       — Due diligence reports, IC memos, research output
  TERM_SHEET      — Term sheets, LOIs, indicative terms, fee letters
  INVESTMENT_MEMO — Investment memos, committee presentations
  MARKETING       — Decks, teasers, factsheets, pitches, brochures
  OTHER           — Anything not matching the above

The module exposes:
  classify_document_type(...)    — single-document classification
  classify_documents(...)        — batch: institutional type for Documents
  classify_registered_documents(...) — batch: doc_type for DocumentRegistry
"""
from __future__ import annotations

import datetime as dt
import uuid
from hashlib import sha1
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import DocumentClassification, DocumentRegistry
from app.domains.credit.modules.documents.models import Document, DocumentChunk, DocumentVersion
from app.services.blob_storage import blob_uri, download_bytes
from app.services.search_index import AzureSearchMetadataClient
from app.services.text_extract import extract_text_from_docx, extract_text_from_pdf

# ── Unified taxonomy ──────────────────────────────────────────────────

UNIFIED_DOC_TYPES: tuple[str, ...] = (
    "LEGAL",
    "REGULATORY",
    "DD_REPORT",
    "TERM_SHEET",
    "INVESTMENT_MEMO",
    "MARKETING",
    "OTHER",
)

# Legacy institutional types — mapped to unified taxonomy for backward compat
INSTITUTIONAL_TYPES: tuple[str, ...] = (
    "MARKETING_PROMOTIONAL",
    "LEGAL_BINDING",
    "REGULATORY_CIMA",
    "FINANCIAL_REPORTING",
    "OPERATIONAL_EVIDENCE",
    "INVESTMENT_COMMITTEE",
    "KYC_AML",
    "GOVERNANCE_BOARD",
)

# Legacy doc types
DOC_TYPES: tuple[str, ...] = (
    "FUND_CONSTITUTIONAL",
    "REGULATORY_CIMA",
    "SERVICE_PROVIDER_CONTRACT",
    "INVESTMENT_MEMO",
    "DEAL_MARKETING",
    "RISK_POLICY_INTERNAL",
    "AUDIT_EVIDENCE",
    "INVESTOR_NARRATIVE",
    "OTHER",
)

_UNIFIED_FROM_INSTITUTIONAL: dict[str, str] = {
    "MARKETING_PROMOTIONAL": "MARKETING",
    "LEGAL_BINDING": "LEGAL",
    "REGULATORY_CIMA": "REGULATORY",
    "FINANCIAL_REPORTING": "DD_REPORT",
    "OPERATIONAL_EVIDENCE": "OTHER",
    "INVESTMENT_COMMITTEE": "INVESTMENT_MEMO",
    "KYC_AML": "REGULATORY",
    "GOVERNANCE_BOARD": "LEGAL",
}

_UNIFIED_FROM_DOC_TYPE: dict[str, str] = {
    "FUND_CONSTITUTIONAL": "LEGAL",
    "REGULATORY_CIMA": "REGULATORY",
    "SERVICE_PROVIDER_CONTRACT": "LEGAL",
    "INVESTMENT_MEMO": "INVESTMENT_MEMO",
    "DEAL_MARKETING": "MARKETING",
    "RISK_POLICY_INTERNAL": "DD_REPORT",
    "AUDIT_EVIDENCE": "DD_REPORT",
    "INVESTOR_NARRATIVE": "MARKETING",
    "OTHER": "OTHER",
}


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _to_seconds_delta(reference: dt.datetime | None, now: dt.datetime) -> int | None:
    if reference is None:
        return None
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=dt.UTC)
    return max(0, int((now - reference).total_seconds()))


# ── Unified single-doc classifier ────────────────────────────────────


def classify_document_type(
    *,
    title: str | None = None,
    filename: str | None = None,
    container: str | None = None,
    folder_path: str | None = None,
    content_snippet: str | None = None,
) -> tuple[str, int, str]:
    """Classify a document into the unified taxonomy.

    Returns (unified_type, confidence_score, classification_basis).
    """
    text = " ".join([
        _normalize(title),
        _normalize(filename),
        _normalize(container),
        _normalize(folder_path),
        _normalize(content_snippet)[:2000] if content_snippet else "",
    ])

    # Regulatory — highest priority
    if any(t in text for t in ["cima", "regulatory", "regulation", "compliance manual"]):
        return "REGULATORY", 95, "keyword"

    # Legal — binding docs
    if any(t in text for t in [
        "lpa", "offering", "subscription", "admin agreement", "engagement",
        "custodian", "legal", "constitutional", "fund-rules", "agreement",
        "contract",
    ]):
        return "LEGAL", 93, "keyword"

    # Term sheets
    if any(t in text for t in ["term sheet", "loi", "indicative terms", "fee letter"]):
        return "TERM_SHEET", 92, "keyword"

    # Investment memos
    if any(t in text for t in [
        "investment memo", "ic memo", "approval memo", "investment committee",
        "committee presentation",
    ]):
        return "INVESTMENT_MEMO", 90, "keyword"

    # Due diligence / reports
    if any(t in text for t in [
        "due diligence", "dd report", "audit", "financial", "statement",
        "nav", "valuation", "report", "risk policy", "policy",
    ]):
        return "DD_REPORT", 85, "keyword"

    # Marketing
    if any(t in text for t in [
        "marketing", "deck", "brochure", "teaser", "factsheet", "pitch",
        "investor-facing",
    ]):
        return "MARKETING", 86, "keyword"

    # KYC/AML → Regulatory
    if any(t in text for t in ["kyc", "aml", "know your customer", "anti-money"]):
        return "REGULATORY", 88, "keyword"

    # Governance → Legal
    if any(t in text for t in ["board", "minutes", "governance"]):
        return "LEGAL", 80, "keyword"

    return "OTHER", 60, "default"


def to_unified_type(legacy_type: str) -> str:
    """Map any legacy type string to the unified taxonomy."""
    return (
        _UNIFIED_FROM_INSTITUTIONAL.get(legacy_type)
        or _UNIFIED_FROM_DOC_TYPE.get(legacy_type)
        or legacy_type
    )


# ══════════════════════════════════════════════════════════════════════
#  Batch classifier: institutional type (from classifier.py)
# ══════════════════════════════════════════════════════════════════════


def _classify_document_institutional(
    *, title: str | None, root_folder: str | None, folder_path: str | None,
) -> str:
    """Legacy keyword + folder heuristic → INSTITUTIONAL_TYPES."""
    text = " ".join([_normalize(title), _normalize(root_folder), _normalize(folder_path)])

    if any(t in text for t in ["cima", "regulatory", "regulation", "compliance manual"]):
        return "REGULATORY_CIMA"
    if any(t in text for t in ["lpa", "offering", "subscription", "admin agreement", "engagement", "custodian", "legal"]):
        return "LEGAL_BINDING"
    if any(t in text for t in ["marketing", "deck", "brochure", "teaser", "factsheet", "pitch"]):
        return "MARKETING_PROMOTIONAL"
    if any(t in text for t in ["audit", "financial", "statement", "nav", "valuation", "report"]):
        return "FINANCIAL_REPORTING"
    if any(t in text for t in ["investment committee", "ic memo", "approval memo"]):
        return "INVESTMENT_COMMITTEE"
    if any(t in text for t in ["kyc", "aml", "know your customer", "anti-money laundering"]):
        return "KYC_AML"
    if any(t in text for t in ["board", "minutes", "governance"]):
        return "GOVERNANCE_BOARD"
    return "OPERATIONAL_EVIDENCE"


def classify_documents(
    db: Session,
    *,
    fund_id: uuid.UUID,
    path: str | None = None,
    actor_id: str = "ai-engine",
) -> list[DocumentRegistry]:
    """Batch classify Documents → DocumentRegistry rows.

    Preserves the full logic from the original classifier.py.
    """
    now = _now_utc()
    prefix = (path or "").strip().lower()

    stmt = (
        select(Document, DocumentVersion)
        .join(
            DocumentVersion,
            and_(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.version_number == Document.current_version,
            ),
        )
        .where(
            Document.fund_id == fund_id,
            Document.source == "dataroom",
            DocumentVersion.fund_id == fund_id,
        )
        .order_by(Document.updated_at.desc())
    )
    rows = list(db.execute(stmt).all())

    saved: list[DocumentRegistry] = []
    for document, version in rows:
        if prefix:
            full_path = f"{(document.root_folder or '').strip()}/{(document.folder_path or '').strip()}".lower()
            if prefix not in full_path and prefix not in (document.root_folder or "").lower():
                continue

        institutional_type = _classify_document_institutional(
            title=document.title,
            root_folder=document.root_folder,
            folder_path=document.folder_path,
        )
        if institutional_type not in INSTITUTIONAL_TYPES:
            institutional_type = "OPERATIONAL_EVIDENCE"

        data_latency = _to_seconds_delta(version.uploaded_at or version.updated_at, now)
        source_key = f"{fund_id}:{version.id}:{institutional_type}"

        existing = db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.version_id == version.id,
            )
        ).scalar_one_or_none()

        payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "document_id": document.id,
            "version_id": version.id,
            "blob_path": version.blob_path,
            "root_folder": document.root_folder,
            "folder_path": document.folder_path,
            "title": document.title,
            "institutional_type": institutional_type,
            "source_signals": {
                "rule": "keyword+folder",
                "hash": sha1(source_key.encode("utf-8")).hexdigest(),
            },
            "classifier_version": "wave-ai1-v1",
            "as_of": now,
            "data_latency": data_latency,
            "data_quality": "OK",
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        if existing is None:
            row = DocumentRegistry(**payload)
            db.add(row)
            db.flush()
        else:
            for key, value in payload.items():
                if key == "created_by":
                    continue
                setattr(existing, key, value)
            row = existing
            db.flush()

        saved.append(row)

    if saved:
        try:
            search_docs = [
                {
                    "id": f"ai-doc-registry-{item.id}",
                    "fund_id": str(item.fund_id),
                    "title": item.title or "Untitled",
                    "content": f"{item.institutional_type} | {(item.root_folder or '')}/{(item.folder_path or '')}",
                    "doc_type": "AI_DOCUMENT_REGISTRY",
                    "version": str(item.version_id),
                    "uploaded_at": item.as_of.isoformat(),
                }
                for item in saved
            ]
            AzureSearchMetadataClient().upsert_documents(items=search_docs)
        except Exception:
            for item in saved:
                item.data_quality = "DEGRADED"
                item.updated_by = actor_id

    db.commit()
    return saved


# ══════════════════════════════════════════════════════════════════════
#  Batch classifier: doc_type (from doc_classifier.py)
# ══════════════════════════════════════════════════════════════════════


def _read_text_content(db: Session, doc: DocumentRegistry) -> str:
    """Read text content from DB chunks or blob download."""
    if doc.version_id:
        chunks = list(
            db.execute(
                select(DocumentChunk.text)
                .join(DocumentVersion, DocumentVersion.id == DocumentChunk.version_id)
                .where(
                    DocumentChunk.fund_id == doc.fund_id,
                    DocumentChunk.version_id == doc.version_id,
                )
                .limit(50)
            ).all()
        )
        text = "\n".join((item[0] or "") for item in chunks)
        if text.strip():
            return text

    try:
        uri = blob_uri(doc.container_name, doc.blob_path)
        data = download_bytes(blob_uri=uri)
        suffix = Path(doc.blob_path).suffix.lower()
        if suffix == ".pdf":
            return extract_text_from_pdf(data).text
        if suffix == ".docx":
            return extract_text_from_docx(data).text
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _classify_doc_type(doc: DocumentRegistry, content_text: str) -> tuple[str, int, str]:
    """Legacy content + container heuristic → DOC_TYPES."""
    filename = (doc.blob_path or "").lower()
    container = (doc.container_name or "").lower()
    content = (content_text or "").lower()

    if "regulatory" in container or "cima" in filename or "cima" in content:
        return "REGULATORY_CIMA", 95, "container|content"
    if "constitution" in container or any(t in filename for t in ["lpa", "constitutional", "fund-rules"]):
        return "FUND_CONSTITUTIONAL", 93, "filename"
    if "service-providers" in container or any(t in filename for t in ["agreement", "contract", "engagement"]):
        basis = "container"
        if any(t in content for t in ["administrator", "custodian", "counsel", "service provider"]):
            basis = "container|content"
        return "SERVICE_PROVIDER_CONTRACT", 90, basis
    if "pipeline" in container and any(t in content for t in ["investment memo", "ic memo", "committee"]):
        return "INVESTMENT_MEMO", 88, "container|content"
    if "investor-facing" in container and any(t in filename for t in ["deck", "brochure", "factsheet", "teaser"]):
        return "DEAL_MARKETING", 86, "container|filename"
    if "risk-policy" in container or "policy" in filename:
        return "RISK_POLICY_INTERNAL", 90, "container|filename"
    if "portfolio-monitoring" in container or any(t in filename for t in ["audit", "evidence", "statement"]):
        return "AUDIT_EVIDENCE", 84, "container|filename"
    if "investor-facing" in container:
        return "INVESTOR_NARRATIVE", 82, "container"
    return "OTHER", 60, "container"


def classify_registered_documents(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[DocumentClassification]:
    """Batch classify DocumentRegistry → DocumentClassification rows.

    Preserves the full logic from the original doc_classifier.py.
    """
    docs = list(
        db.execute(
            select(DocumentRegistry)
            .where(DocumentRegistry.fund_id == fund_id)
            .order_by(DocumentRegistry.updated_at.desc())
        ).scalars().all()
    )

    saved: list[DocumentClassification] = []
    for doc in docs:
        content_text = _read_text_content(db, doc)
        doc_type, confidence, basis = _classify_doc_type(doc, content_text)

        existing = db.execute(
            select(DocumentClassification).where(
                DocumentClassification.fund_id == fund_id,
                DocumentClassification.doc_id == doc.id,
            )
        ).scalar_one_or_none()

        payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "doc_id": doc.id,
            "doc_type": doc_type,
            "confidence_score": int(confidence),
            "classification_basis": basis,
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        if existing is None:
            row = DocumentClassification(**payload)
            db.add(row)
            db.flush()
        else:
            for key, value in payload.items():
                if key == "created_by":
                    continue
                setattr(existing, key, value)
            row = existing
            db.flush()

        doc.detected_doc_type = doc_type
        doc.updated_by = actor_id
        saved.append(row)

    db.commit()
    return saved
