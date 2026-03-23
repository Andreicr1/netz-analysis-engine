from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ai_engine.governance.authority_resolver import resolve_authority_profiles
from ai_engine.knowledge.knowledge_anchor_extractor import extract_knowledge_anchors
from app.domains.credit.modules.ai.models import (
    DocumentClassification,
    DocumentRegistry,
)
from app.domains.credit.modules.documents.models import Document, DocumentChunk, DocumentVersion
from app.services.storage_client import get_storage_client
from app.services.text_extract import extract_text_from_docx, extract_text_from_pdf

logger = logging.getLogger(__name__)


def _run_async(coro):  # noqa: ANN001, ANN202
    """Run an async coroutine from synchronous context (StorageClient bridge)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


CONTAINER_METADATA: dict[str, dict[str, str]] = {
    "dataroom-investor-facing": {
        "domain_tag": "INVESTOR_RELATIONS",
        "authority": "NARRATIVE",
        "shareability": "EXTERNAL",
        "lifecycle_stage": "ACTIVE",
    },
    "fund-constitution-governance": {
        "domain_tag": "FUND_GOVERNANCE",
        "authority": "BINDING",
        "shareability": "INTERNAL",
        "lifecycle_stage": "GOVERNANCE",
    },
    "regulatory-library-cima": {
        "domain_tag": "REGULATORY",
        "authority": "BINDING",
        "shareability": "INTERNAL",
        "lifecycle_stage": "GOVERNANCE",
    },
    "service-providers-contracts": {
        "domain_tag": "SERVICE_PROVIDER",
        "authority": "BINDING",
        "shareability": "INTERNAL",
        "lifecycle_stage": "ACTIVE",
    },
    "risk-policy-internal": {
        "domain_tag": "RISK_POLICY",
        "authority": "POLICY",
        "shareability": "INTERNAL",
        "lifecycle_stage": "GOVERNANCE",
    },
    "investment-pipeline-intelligence": {
        "domain_tag": "PIPELINE",
        "authority": "INTELLIGENCE",
        "shareability": "INTERNAL",
        "lifecycle_stage": "PIPELINE",
    },
    "portfolio-monitoring-evidence": {
        "domain_tag": "PORTFOLIO_MONITORING",
        "authority": "EVIDENCE",
        "shareability": "INTERNAL",
        "lifecycle_stage": "ACTIVE",
    },
}


_INSTITUTIONAL_TYPES: tuple[str, ...] = (
    "MARKETING_PROMOTIONAL", "LEGAL_BINDING", "REGULATORY_CIMA",
    "FINANCIAL_REPORTING", "OPERATIONAL_EVIDENCE", "INVESTMENT_COMMITTEE",
    "KYC_AML", "GOVERNANCE_BOARD",
)


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


def _classify_document_institutional(
    *, title: str | None, root_folder: str | None, folder_path: str | None,
) -> str:
    """Keyword + folder heuristic → institutional type."""
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
    """Batch classify Documents → DocumentRegistry rows."""
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

        data_latency = _to_seconds_delta(version.uploaded_at or version.updated_at, now)
        source_key = f"{fund_id}:{version.id}:{institutional_type}"

        existing = db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.version_id == version.id,
            ),
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
                "hash": hashlib.sha1(source_key.encode("utf-8")).hexdigest(),
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

    db.commit()
    return saved


def _read_text_content(db: Session, doc: DocumentRegistry) -> str:
    """Read text content from DB chunks or blob download."""
    if doc.version_id:
        chunks = list(
            db.execute(
                select(DocumentChunk.text)
                .where(
                    DocumentChunk.fund_id == doc.fund_id,
                    DocumentChunk.version_id == doc.version_id,
                )
                .limit(50),
            ).all(),
        )
        text = "\n".join((item[0] or "") for item in chunks)
        if text.strip():
            return text

    try:
        storage = get_storage_client()
        storage_path = doc.blob_path or ""
        if not storage_path:
            return ""
        data = _run_async(storage.read(storage_path))
        suffix = Path(storage_path).suffix.lower()
        if suffix == ".pdf":
            return extract_text_from_pdf(data).text
        if suffix == ".docx":
            return extract_text_from_docx(data).text
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _classify_doc_type(doc: DocumentRegistry, content_text: str) -> tuple[str, int, str]:
    """Content + container heuristic → doc_type classification."""
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
    """Batch classify DocumentRegistry → DocumentClassification rows."""
    docs = list(
        db.execute(
            select(DocumentRegistry)
            .where(DocumentRegistry.fund_id == fund_id)
            .order_by(DocumentRegistry.updated_at.desc()),
        ).scalars().all(),
    )

    saved: list[DocumentClassification] = []
    for doc in docs:
        content_text = _read_text_content(db, doc)
        doc_type, confidence, basis = _classify_doc_type(doc, content_text)

        existing = db.execute(
            select(DocumentClassification).where(
                DocumentClassification.fund_id == fund_id,
                DocumentClassification.doc_id == doc.id,
            ),
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


def _title_from_blob_path(blob_path: str) -> str:
    cleaned = (blob_path or "").rstrip("/")
    if not cleaned:
        return "Untitled"
    return cleaned.split("/")[-1]


def _checksum(file_path: str, container_name: str) -> str:
    base = f"{container_name}:{file_path}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def scan_document_registry(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[DocumentRegistry]:
    now = _now_utc()
    touched: list[DocumentRegistry] = []

    storage = get_storage_client()

    for container_name, metadata in CONTAINER_METADATA.items():
        try:
            # list_files returns all paths under the prefix (recursive).
            file_paths = _run_async(storage.list_files(container_name))
        except Exception:
            continue

        existing_map: dict[str, DocumentRegistry] = {
            r.blob_path: r
            for r in db.execute(
                select(DocumentRegistry).where(
                    DocumentRegistry.fund_id == fund_id,
                    DocumentRegistry.container_name == container_name,
                ),
            ).scalars().all()
        }

        for file_path in file_paths:
            checksum = _checksum(file_path, container_name)
            existing = existing_map.get(file_path)

            payload = {
                "fund_id": fund_id,
                "access_level": "internal",
                "container_name": container_name,
                "blob_path": file_path,
                "title": _title_from_blob_path(file_path),
                "domain_tag": metadata["domain_tag"],
                "authority": metadata["authority"],
                "shareability": metadata["shareability"],
                "lifecycle_stage": metadata["lifecycle_stage"],
                "last_ingested_at": now,
                "checksum": checksum,
                "as_of": now,
                "data_latency": None,
                "data_quality": "OK",
                "root_folder": container_name,
                "folder_path": file_path,
                "institutional_type": "OPERATIONAL_EVIDENCE",
                "classifier_version": "wave-ai2-scan-v1",
                "source_signals": {
                    "scanner": "storage_client+checksum",
                },
                "created_by": actor_id,
                "updated_by": actor_id,
            }

            if existing is None:
                row = DocumentRegistry(**payload)
                db.add(row)
                db.flush()
                touched.append(row)
                continue

            changed = bool(existing.checksum != payload["checksum"])
            for key, value in payload.items():
                if key == "created_by":
                    continue
                if key == "last_ingested_at" and not changed:
                    continue
                setattr(existing, key, value)
            db.flush()
            touched.append(existing)

    db.commit()
    return touched


def run_documents_ingest_pipeline(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> dict[str, int | str]:
    scanned = scan_document_registry(db, fund_id=fund_id, actor_id=actor_id)
    classified = classify_registered_documents(db, fund_id=fund_id, actor_id=actor_id)
    governance_profiles = resolve_authority_profiles(db, fund_id=fund_id, actor_id=actor_id)
    anchors = extract_knowledge_anchors(db, fund_id=fund_id, actor_id=actor_id)

    return {
        "documentsScanned": len(scanned),
        "documentsClassified": len(classified),
        "governanceProfiles": len(governance_profiles),
        "knowledgeAnchors": len(anchors),
    }
