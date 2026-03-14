from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    DocumentRegistry,
    KnowledgeEntity,
    KnowledgeLink,
    ManagerProfile,
    ObligationEvidenceMap,
    ObligationRegister,
)
from app.domains.credit.modules.deals.models import Deal
from app.domains.credit.modules.documents.models import DocumentChunk

logger = logging.getLogger(__name__)

CONTAINER_AUTHORITY: dict[str, str] = {
    "dataroom-investor-facing": "NARRATIVE",
    "fund-constitution-governance": "BINDING",
    "regulatory-library-cima": "BINDING",
    "service-providers-contracts": "BINDING",
    "risk-policy-internal": "POLICY",
    "investment-pipeline-intelligence": "INTELLIGENCE",
    "portfolio-monitoring-evidence": "EVIDENCE",
}

LINK_TYPES = {
    "REFERENCES",
    "DERIVES_OBLIGATION",
    "SATISFIES",
    "CONFLICTS_WITH",
    "REQUIRES",
    "RELATES_TO_MANAGER",
    "RELATES_TO_DEAL",
}


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _normalize(value: str | None) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def _text_terms(value: str | None, *, max_terms: int = 8) -> list[str]:
    words = [w for w in _normalize(value).split() if len(w) >= 4]
    ordered: list[str] = []
    for word in words:
        if word not in ordered:
            ordered.append(word)
        if len(ordered) >= max_terms:
            break
    return ordered


def _resolved_authority(doc: DocumentRegistry) -> str:
    return CONTAINER_AUTHORITY.get(doc.container_name, doc.authority or "EVIDENCE")


def _allowed_link_types(authority_tier: str) -> set[str]:
    if authority_tier in {"BINDING", "POLICY"}:
        return LINK_TYPES - {"SATISFIES"}
    if authority_tier == "INTELLIGENCE":
        return {"REFERENCES", "RELATES_TO_MANAGER", "RELATES_TO_DEAL"}
    if authority_tier == "EVIDENCE":
        return {"SATISFIES", "REFERENCES"}
    return {"REFERENCES"}


def _upsert_entity(
    db: Session,
    *,
    fund_id: uuid.UUID,
    entity_type: str,
    canonical_name: str,
    actor_id: str,
) -> KnowledgeEntity:
    existing = db.execute(
        select(KnowledgeEntity).where(
            KnowledgeEntity.fund_id == fund_id,
            KnowledgeEntity.entity_type == entity_type,
            KnowledgeEntity.canonical_name == canonical_name,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.updated_by = actor_id
        db.flush()
        return existing

    row = KnowledgeEntity(
        fund_id=fund_id,
        access_level="internal",
        entity_type=entity_type,
        canonical_name=canonical_name,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    db.flush()
    return row


def _upsert_link(
    db: Session,
    *,
    fund_id: uuid.UUID,
    source_document_id: uuid.UUID,
    target_entity_id: uuid.UUID,
    link_type: str,
    authority_tier: str,
    confidence_score: float,
    evidence_snippet: str | None,
    actor_id: str,
) -> bool:
    existing = db.execute(
        select(KnowledgeLink).where(
            KnowledgeLink.fund_id == fund_id,
            KnowledgeLink.source_document_id == source_document_id,
            KnowledgeLink.target_entity_id == target_entity_id,
            KnowledgeLink.link_type == link_type,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.authority_tier = authority_tier
        existing.confidence_score = confidence_score
        existing.evidence_snippet = evidence_snippet
        existing.updated_by = actor_id
        db.flush()
        return False

    db.add(
        KnowledgeLink(
            fund_id=fund_id,
            access_level="internal",
            source_document_id=source_document_id,
            target_entity_id=target_entity_id,
            link_type=link_type,
            authority_tier=authority_tier,
            confidence_score=confidence_score,
            evidence_snippet=evidence_snippet,
            created_by=actor_id,
            updated_by=actor_id,
        )
    )
    db.flush()
    return True


def _preload_corpora(db: Session, docs: list[DocumentRegistry]) -> dict[uuid.UUID, str]:
    """Batch-load chunk text for all documents and return {doc.id: normalized_corpus}."""
    version_map: dict[uuid.UUID, list[DocumentRegistry]] = defaultdict(list)
    for doc in docs:
        if doc.version_id is not None:
            version_map[doc.version_id].append(doc)

    chunks_by_version: dict[uuid.UUID, list[str]] = defaultdict(list)
    if version_map:
        all_version_ids = list(version_map.keys())
        fund_id = docs[0].fund_id
        rows = list(
            db.execute(
                select(DocumentChunk.version_id, DocumentChunk.text)
                .where(DocumentChunk.fund_id == fund_id, DocumentChunk.version_id.in_(all_version_ids))
                .limit(len(all_version_ids) * 60)
            ).all()
        )
        for vid, text in rows:
            chunks_by_version[vid].append(text or "")

    result: dict[uuid.UUID, str] = {}
    for doc in docs:
        chunk_texts = chunks_by_version.get(doc.version_id, [])[:60] if doc.version_id else []
        text = " ".join([doc.title or "", doc.blob_path or ""] + chunk_texts)
        result[doc.id] = _normalize(text)
    return result


def _document_corpus(db: Session, doc: DocumentRegistry, *, corpus_cache: dict[uuid.UUID, str] | None = None) -> str:
    if corpus_cache is not None and doc.id in corpus_cache:
        return corpus_cache[doc.id]
    chunks = []
    if doc.version_id is not None:
        chunks = list(
            db.execute(
                select(DocumentChunk.text)
                .where(DocumentChunk.fund_id == doc.fund_id, DocumentChunk.version_id == doc.version_id)
                .limit(60)
            ).all()
        )
    text = " ".join([doc.title or "", doc.blob_path or ""] + [row[0] or "" for row in chunks])
    return _normalize(text)


def _source_registry_doc_id(db: Session, *, fund_id: uuid.UUID, source_documents: list[dict] | None) -> uuid.UUID | None:
    if not source_documents:
        return None

    for item in source_documents:
        raw_document_id = item.get("documentId")
        if not raw_document_id:
            continue
        try:
            document_id = uuid.UUID(str(raw_document_id))
        except Exception:
            continue
        row = db.execute(
            select(DocumentRegistry.id).where(DocumentRegistry.fund_id == fund_id, DocumentRegistry.document_id == document_id)
        ).first()
        if row:
            return row[0]
    return None


def build_entity_index(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    as_of: dt.datetime | None = None,
) -> list[tuple[KnowledgeEntity, list[str]]]:
    entries: list[tuple[KnowledgeEntity, list[str]]] = []
    effective_as_of = as_of or _now_utc()

    # Four independent queries executed sequentially because they share a
    # single SQLAlchemy Session (not thread-safe).  Consolidating into a
    # single UNION query is impractical since each targets a different table
    # with distinct columns and filter predicates.
    managers = list(
        db.execute(select(ManagerProfile).where(ManagerProfile.fund_id == fund_id, ManagerProfile.as_of <= effective_as_of)).scalars().all()
    )
    deals = list(db.execute(select(Deal).where(Deal.fund_id == fund_id)).scalars().all())
    obligations = list(
        db.execute(select(ObligationRegister).where(ObligationRegister.fund_id == fund_id, ObligationRegister.as_of <= effective_as_of)).scalars().all()
    )
    provider_docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == "service-providers-contracts",
                DocumentRegistry.as_of <= effective_as_of,
            )
        ).scalars().all()
    )

    for manager in managers:
        canonical_name = (manager.name or "").strip()
        if not canonical_name:
            continue
        entity = _upsert_entity(db, fund_id=fund_id, entity_type="MANAGER", canonical_name=canonical_name, actor_id=actor_id)
        entries.append((entity, [_normalize(canonical_name)]))

    for deal in deals:
        canonical_name = (deal.deal_name or deal.title or "").strip()
        if not canonical_name:
            continue
        entity = _upsert_entity(db, fund_id=fund_id, entity_type="DEAL", canonical_name=canonical_name, actor_id=actor_id)
        terms = [_normalize(canonical_name)]
        if deal.sponsor_name:
            terms.append(_normalize(deal.sponsor_name))
        entries.append((entity, [t for t in terms if t]))

    for obligation in obligations:
        canonical_name = (obligation.obligation_id or "").strip()
        if not canonical_name:
            continue
        entity = _upsert_entity(db, fund_id=fund_id, entity_type="OBLIGATION", canonical_name=canonical_name, actor_id=actor_id)
        terms = _text_terms(obligation.obligation_text, max_terms=10)
        if canonical_name:
            terms.insert(0, _normalize(canonical_name))
        entries.append((entity, [t for t in terms if t]))

    for provider_doc in provider_docs:
        name = re.sub(r"\.[a-z0-9]+$", "", provider_doc.title or "", flags=re.IGNORECASE).strip()
        if not name:
            continue
        entity = _upsert_entity(db, fund_id=fund_id, entity_type="PROVIDER", canonical_name=name, actor_id=actor_id)
        entries.append((entity, [_normalize(name)]))

    db.commit()
    return entries


def link_document(
    db: Session,
    *,
    fund_id: uuid.UUID,
    document_id: uuid.UUID,
    entity_index: list[tuple[KnowledgeEntity, list[str]]],
    actor_id: str = "ai-engine",
    corpus_cache: dict[uuid.UUID, str] | None = None,
) -> int:
    doc = db.execute(
        select(DocumentRegistry).where(DocumentRegistry.fund_id == fund_id, DocumentRegistry.id == document_id)
    ).scalar_one_or_none()
    if doc is None:
        return 0

    corpus = _document_corpus(db, doc, corpus_cache=corpus_cache)
    authority_tier = _resolved_authority(doc)
    allowed = _allowed_link_types(authority_tier)

    created = 0
    for entity, terms in entity_index:
        matched_term = next((term for term in terms if term and term in corpus), None)
        if not matched_term:
            continue

        if entity.entity_type == "MANAGER":
            link_type = "RELATES_TO_MANAGER"
        elif entity.entity_type == "DEAL":
            link_type = "RELATES_TO_DEAL"
        elif entity.entity_type == "OBLIGATION" and authority_tier in {"BINDING", "POLICY"}:
            if doc.container_name == "service-providers-contracts":
                link_type = "REQUIRES"
            else:
                link_type = "DERIVES_OBLIGATION"
        else:
            link_type = "REFERENCES"

        if link_type not in allowed:
            continue

        confidence = 0.92 if matched_term == _normalize(entity.canonical_name) else 0.72
        evidence_snippet = f"{doc.title} :: {matched_term}" if doc.title else matched_term
        if _upsert_link(
            db,
            fund_id=fund_id,
            source_document_id=doc.id,
            target_entity_id=entity.id,
            link_type=link_type,
            authority_tier=authority_tier,
            confidence_score=confidence,
            evidence_snippet=evidence_snippet,
            actor_id=actor_id,
        ):
            created += 1

    db.commit()
    return created


def map_obligation_evidence(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    as_of: dt.datetime | None = None,
) -> tuple[int, int]:
    now = as_of or _now_utc()

    obligation_entities = list(
        db.execute(
            select(KnowledgeEntity).where(KnowledgeEntity.fund_id == fund_id, KnowledgeEntity.entity_type == "OBLIGATION")
        ).scalars().all()
    )
    obligations = list(
        db.execute(select(ObligationRegister).where(ObligationRegister.fund_id == fund_id, ObligationRegister.as_of <= now)).scalars().all()
    )
    obligation_by_key = {row.obligation_id: row for row in obligations}

    evidence_docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.container_name == "portfolio-monitoring-evidence",
                DocumentRegistry.as_of <= now,
            )
        ).scalars().all()
    )
    evidence_corpus = _preload_corpora(db, evidence_docs) if evidence_docs else {}

    satisfied = 0
    created_links = 0

    for entity in obligation_entities:
        source_obligation = obligation_by_key.get(entity.canonical_name)
        terms = _text_terms(source_obligation.obligation_text if source_obligation else entity.canonical_name, max_terms=12)
        best_doc_id: uuid.UUID | None = None
        best_score = 0

        for evidence_doc in evidence_docs:
            corpus = evidence_corpus.get(evidence_doc.id, "")
            score = sum(1 for term in terms if term and term in corpus)
            if score > best_score:
                best_score = score
                best_doc_id = evidence_doc.id

        if best_score >= 3:
            status = "MATCHED"
            confidence = 0.91
        elif best_score >= 1:
            status = "PARTIAL"
            confidence = 0.64
        else:
            status = "NONE"
            confidence = 0.0
            best_doc_id = None

        existing_map = db.execute(
            select(ObligationEvidenceMap).where(
                ObligationEvidenceMap.fund_id == fund_id,
                ObligationEvidenceMap.obligation_id == entity.id,
            )
        ).scalar_one_or_none()

        if existing_map is None:
            db.add(
                ObligationEvidenceMap(
                    fund_id=fund_id,
                    access_level="internal",
                    obligation_id=entity.id,
                    evidence_document_id=best_doc_id,
                    satisfaction_status=status,
                    last_checked_at=now,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
        else:
            existing_map.evidence_document_id = best_doc_id
            existing_map.satisfaction_status = status
            existing_map.last_checked_at = now
            existing_map.updated_by = actor_id

        if best_doc_id is not None:
            evidence_doc = next((d for d in evidence_docs if d.id == best_doc_id), None)
            if evidence_doc is not None:
                authority_tier = _resolved_authority(evidence_doc)
                if "SATISFIES" in _allowed_link_types(authority_tier):
                    if _upsert_link(
                        db,
                        fund_id=fund_id,
                        source_document_id=best_doc_id,
                        target_entity_id=entity.id,
                        link_type="SATISFIES",
                        authority_tier=authority_tier,
                        confidence_score=confidence,
                        evidence_snippet=f"Evidence match score={best_score}",
                        actor_id=actor_id,
                    ):
                        created_links += 1

        if status == "MATCHED":
            satisfied += 1

    db.commit()
    return satisfied, created_links


def detect_binding_conflicts(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    as_of: dt.datetime | None = None,
) -> tuple[int, int]:
    effective_as_of = as_of or _now_utc()
    obligations = list(
        db.execute(select(ObligationRegister).where(ObligationRegister.fund_id == fund_id, ObligationRegister.as_of <= effective_as_of)).scalars().all()
    )
    entities = list(
        db.execute(
            select(KnowledgeEntity).where(KnowledgeEntity.fund_id == fund_id, KnowledgeEntity.entity_type == "OBLIGATION")
        ).scalars().all()
    )
    entity_by_obligation_id = {entity.canonical_name: entity for entity in entities}

    grouped: dict[str, list[ObligationRegister]] = defaultdict(list)
    for row in obligations:
        key = " ".join(_text_terms(row.obligation_text, max_terms=8))
        if key:
            grouped[key].append(row)

    conflicts_detected = 0
    created_links = 0

    for group_rows in grouped.values():
        if len(group_rows) < 2:
            continue

        due_rules = {(_normalize(row.due_rule) or "ongoing") for row in group_rows}
        if len(due_rules) <= 1:
            continue

        conflicts_detected += 1

        for row in group_rows:
            source_doc_id = _source_registry_doc_id(db, fund_id=fund_id, source_documents=row.source_documents)
            if source_doc_id is None:
                continue

            source_doc = db.execute(
                select(DocumentRegistry).where(DocumentRegistry.fund_id == fund_id, DocumentRegistry.id == source_doc_id)
            ).scalar_one_or_none()
            if source_doc is None:
                continue

            authority_tier = _resolved_authority(source_doc)
            if authority_tier not in {"BINDING", "POLICY"}:
                continue

            target_entity = entity_by_obligation_id.get(row.obligation_id)
            if target_entity is None:
                continue

            if _upsert_link(
                db,
                fund_id=fund_id,
                source_document_id=source_doc_id,
                target_entity_id=target_entity.id,
                link_type="CONFLICTS_WITH",
                authority_tier=authority_tier,
                confidence_score=0.95,
                evidence_snippet=f"Due rule conflict: {row.due_rule}",
                actor_id=actor_id,
            ):
                created_links += 1

    db.commit()
    return conflicts_detected, created_links


def run_cross_container_linking(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
    as_of: dt.datetime | None = None,
) -> dict:
    effective_as_of = as_of or _now_utc()

    entity_index = build_entity_index(db, fund_id=fund_id, actor_id=actor_id, as_of=effective_as_of)
    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.as_of <= effective_as_of,
            )
        ).scalars().all()
    )

    corpus_cache = _preload_corpora(db, docs) if docs else {}

    links_created = 0
    for doc in docs:
        links_created += link_document(
            db,
            fund_id=fund_id,
            document_id=doc.id,
            entity_index=entity_index,
            actor_id=actor_id,
            corpus_cache=corpus_cache,
        )

    obligations_satisfied, sat_links = map_obligation_evidence(db, fund_id=fund_id, actor_id=actor_id, as_of=effective_as_of)
    conflicts_detected, conflict_links = detect_binding_conflicts(db, fund_id=fund_id, actor_id=actor_id, as_of=effective_as_of)
    links_created += sat_links + conflict_links

    status = "PASS"
    if len(entity_index) == 0:
        status = "BLOCK"
    elif conflicts_detected > 0:
        status = "PARTIAL"

    return {
        "mode": "CROSS_CONTAINER_LINKING",
        "asOf": effective_as_of.isoformat(),
        "status": status,
        "payload": {
            "entitiesLinked": len(entity_index),
            "linksCreated": links_created,
            "obligationsSatisfied": obligations_satisfied,
            "conflictsDetected": conflicts_detected,
        },
    }


def get_entity_links_snapshot(
    db: Session,
    *,
    fund_id: uuid.UUID,
    entity_id: uuid.UUID,
    as_of: dt.datetime,
) -> dict:
    rows = list(
        db.execute(
            select(KnowledgeLink).where(
                KnowledgeLink.fund_id == fund_id,
                KnowledgeLink.target_entity_id == entity_id,
                KnowledgeLink.created_at <= as_of,
            )
        ).scalars().all()
    )

    links = [
        {
            "linkId": str(row.id),
            "sourceDocumentId": str(row.source_document_id),
            "targetEntityId": str(row.target_entity_id),
            "linkType": row.link_type,
            "authorityTier": row.authority_tier,
            "confidenceScore": row.confidence_score,
            "evidenceSnippet": row.evidence_snippet,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]

    return {
        "mode": "CROSS_CONTAINER_LINKING",
        "asOf": as_of.isoformat(),
        "status": "PASS",
        "payload": {
            "entitiesLinked": 1,
            "linksCreated": len(rows),
            "obligationsSatisfied": sum(1 for row in rows if row.link_type == "SATISFIES"),
            "conflictsDetected": sum(1 for row in rows if row.link_type == "CONFLICTS_WITH"),
            "links": links,
        },
    }


def get_obligation_status_snapshot(
    db: Session,
    *,
    fund_id: uuid.UUID,
    as_of: dt.datetime,
) -> dict:
    rows = list(
        db.execute(
            select(ObligationEvidenceMap, KnowledgeEntity)
            .join(KnowledgeEntity, KnowledgeEntity.id == ObligationEvidenceMap.obligation_id)
            .where(
                ObligationEvidenceMap.fund_id == fund_id,
                ObligationEvidenceMap.last_checked_at <= as_of,
            )
        ).all()
    )

    obligations = [
        {
            "obligationEntityId": str(entity.id),
            "obligationCanonicalName": entity.canonical_name,
            "evidenceDocumentId": str(mapping.evidence_document_id) if mapping.evidence_document_id else None,
            "satisfactionStatus": mapping.satisfaction_status,
            "lastCheckedAt": mapping.last_checked_at.isoformat(),
        }
        for mapping, entity in rows
    ]

    return {
        "mode": "CROSS_CONTAINER_LINKING",
        "asOf": as_of.isoformat(),
        "status": "PASS",
        "payload": {
            "entitiesLinked": len({str(entity.id) for _, entity in rows}),
            "linksCreated": 0,
            "obligationsSatisfied": sum(1 for mapping, _ in rows if mapping.satisfaction_status == "MATCHED"),
            "conflictsDetected": 0,
            "obligations": obligations,
        },
    }
