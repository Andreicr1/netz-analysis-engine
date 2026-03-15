from __future__ import annotations

import datetime as dt
import hashlib
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.classification.document_classifier import classify_registered_documents
from ai_engine.governance.authority_resolver import resolve_authority_profiles
from ai_engine.knowledge.knowledge_anchor_extractor import extract_knowledge_anchors
from app.domains.credit.modules.ai.models import DocumentRegistry
from app.services.blob_storage import BlobEntry, list_blobs

logger = logging.getLogger(__name__)


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


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.UTC)
        return parsed.astimezone(dt.UTC)
    except Exception:
        return None


def _title_from_blob_path(blob_path: str) -> str:
    cleaned = (blob_path or "").rstrip("/")
    if not cleaned:
        return "Untitled"
    return cleaned.split("/")[-1]


def _checksum(entry: BlobEntry, container_name: str) -> str:
    base = f"{container_name}:{entry.name}:{entry.size_bytes}:{entry.last_modified}:{entry.etag}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def scan_document_registry(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[DocumentRegistry]:
    now = _now_utc()
    touched: list[DocumentRegistry] = []

    for container_name, metadata in CONTAINER_METADATA.items():
        try:
            # delimiter="" → recursive listing of ALL blobs including nested
            # subdirectories (e.g. investment-pipeline-intelligence/Blue Owl/*.pdf).
            # A prefix-only listing (delimiter="/") would miss files in
            # sub-folders, which is required for the full document registry.
            entries = [
                item
                for item in list_blobs(container=container_name, prefix=None, delimiter="")
                if not item.is_folder
            ]
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

        for entry in entries:
            checksum = _checksum(entry, container_name)
            modified = _parse_iso(entry.last_modified)
            existing = existing_map.get(entry.name)

            payload = {
                "fund_id": fund_id,
                "access_level": "internal",
                "container_name": container_name,
                "blob_path": entry.name,
                "title": _title_from_blob_path(entry.name),
                "domain_tag": metadata["domain_tag"],
                "authority": metadata["authority"],
                "shareability": metadata["shareability"],
                "lifecycle_stage": metadata["lifecycle_stage"],
                "last_ingested_at": now,
                "checksum": checksum,
                "etag": entry.etag,
                "last_modified_utc": modified,
                "as_of": now,
                "data_latency": None,
                "data_quality": "OK",
                "root_folder": container_name,
                "folder_path": entry.name,
                "institutional_type": "OPERATIONAL_EVIDENCE",
                "classifier_version": "wave-ai2-scan-v1",
                "source_signals": {
                    "scanner": "container+etag+last_modified",
                    "size_bytes": entry.size_bytes,
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

            changed = bool(existing.etag != payload["etag"] or existing.last_modified_utc != payload["last_modified_utc"])
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
