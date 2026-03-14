from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import DocumentRegistry, ObligationRegister
from app.domains.credit.modules.documents.models import DocumentChunk, DocumentVersion
from app.services.search_index import AzureSearchMetadataClient

OBLIGATION_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
DUE_RULE_RE = re.compile(r"(within\s+\d+\s+(?:days?|months?)\s+after\s+[^.;]+|\d+\s+months\s+after\s+fy\s+end)", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _infer_source(path_text: str) -> str:
    lowered = path_text.lower()
    if "cima" in lowered or "regulatory" in lowered:
        return "CIMA"
    if "admin" in lowered or "administrator" in lowered:
        return "Admin"
    if "custodian" in lowered or "bank" in lowered:
        return "Custodian"
    return "Offering"


def _infer_frequency(text: str) -> str:
    lowered = text.lower()
    if "quarterly" in lowered:
        return "Quarterly"
    if "annual" in lowered or "annually" in lowered:
        return "Annual"
    return "Ongoing"


def _infer_due_rule(text: str) -> str:
    match = DUE_RULE_RE.search(text)
    if match:
        return match.group(1).strip()
    date_match = ISO_DATE_RE.search(text)
    if date_match:
        return f"Due on {date_match.group(1)}"
    return "Ongoing - immediate compliance"


def _infer_responsible_party(source: str, text: str) -> str:
    lowered = text.lower()
    if "investment manager" in lowered or "manager" in lowered:
        return "Investment Manager"
    if "administrator" in lowered or source == "Admin":
        return "Fund Administrator"
    if "custodian" in lowered or "bank" in lowered or source == "Custodian":
        return "Custodian"
    if "counsel" in lowered or "legal" in lowered:
        return "Legal Counsel"
    if source == "CIMA":
        return "Compliance Officer"
    return "Fund Management"


def _evidence_expected(source: str) -> str:
    mapping = {
        "CIMA": "Regulatory filing receipt",
        "Admin": "Administrator report / confirmation",
        "Custodian": "Custodian statement",
        "Offering": "Board-approved offering compliance evidence",
    }
    return mapping.get(source, "Formal evidence document")


def extract_obligation_register(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[ObligationRegister]:
    now = _now_utc()

    candidates = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.institutional_type.in_(["LEGAL_BINDING", "REGULATORY_CIMA"]),
            )
        ).scalars().all()
    )

    # ── Batch-load chunks for all candidates ─────────────────────────
    all_version_ids = [doc.version_id for doc in candidates if doc.version_id]
    chunks_by_version: dict[uuid.UUID, list[str]] = {}
    if all_version_ids:
        chunk_rows = db.execute(
            select(DocumentChunk.version_id, DocumentChunk.text)
            .join(DocumentVersion, and_(DocumentVersion.id == DocumentChunk.version_id, DocumentVersion.fund_id == fund_id))
            .where(DocumentChunk.fund_id == fund_id, DocumentChunk.version_id.in_(all_version_ids))
        ).all()
        for version_id, text_val in chunk_rows:
            chunks_by_version.setdefault(version_id, []).append(text_val or "")

    # ── Pre-load existing obligations ──────────────────────────────────
    existing_obligations: dict[str, ObligationRegister] = {
        r.obligation_id: r
        for r in db.execute(
            select(ObligationRegister).where(ObligationRegister.fund_id == fund_id)
        ).scalars().all()
    }

    saved: list[ObligationRegister] = []
    for doc in candidates:
        doc_chunks = chunks_by_version.get(doc.version_id, [])[:120] if doc.version_id else []
        text = "\n".join(doc_chunks)
        if not text.strip():
            text = doc.title or ""

        sentences = OBLIGATION_SENTENCE_RE.split(text)
        matched_sentences = [
            sentence.strip()
            for sentence in sentences
            if sentence and any(
                token in sentence.lower()
                for token in ["shall", "must", "required", "deliver", "submit", "file", "notify", "maintain", "comply"]
            )
        ][:8]

        source_descriptor = f"{doc.root_folder or ''}/{doc.folder_path or ''}"
        source = _infer_source(source_descriptor)

        for index, obligation_text in enumerate(matched_sentences, start=1):
            raw_id = f"{fund_id}:{doc.version_id}:{index}:{obligation_text[:80]}"
            obligation_id = f"OB-{hashlib.sha1(raw_id.encode('utf-8')).hexdigest()[:12].upper()}"

            payload = {
                "fund_id": fund_id,
                "access_level": "internal",
                "obligation_id": obligation_id,
                "source": source,
                "obligation_text": obligation_text[:2000],
                "frequency": _infer_frequency(obligation_text),
                "due_rule": _infer_due_rule(obligation_text),
                "responsible_party": _infer_responsible_party(source, obligation_text),
                "evidence_expected": _evidence_expected(source),
                "status": "MissingEvidence",
                "source_documents": [
                    {
                        "documentId": str(doc.document_id),
                        "versionId": str(doc.version_id),
                        "title": doc.title,
                        "path": source_descriptor,
                    }
                ],
                "as_of": now,
                "data_latency": doc.data_latency,
                "data_quality": "OK",
                "created_by": actor_id,
                "updated_by": actor_id,
            }

            existing = existing_obligations.get(obligation_id)

            if existing is None:
                row = ObligationRegister(**payload)
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
                    "id": f"ai-obligation-{item.id}",
                    "fund_id": str(item.fund_id),
                    "title": item.obligation_id,
                    "content": item.obligation_text[:900],
                    "doc_type": "AI_OBLIGATION_REGISTER",
                    "version": str(item.id),
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
