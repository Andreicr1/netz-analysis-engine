from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import (
    DocumentClassification,
    DocumentRegistry,
    KnowledgeAnchor,
)
from app.services.storage_client import get_storage_client

DATE_RE = re.compile(r"\b(20\d{2}[-/]\d{2}[-/]\d{2})\b")
LAW_RE = re.compile(r"governed by the laws? of ([A-Za-z\s]+)", re.IGNORECASE)
SECTION_RE = re.compile(r"\b(section|sec\.)\s+(\d+[A-Za-z0-9\-\.]*)", re.IGNORECASE)
OBLIGATION_KEYWORDS = ("must", "shall", "required", "requirement")


def _extract_text(registry: DocumentRegistry) -> str:
    try:
        import asyncio

        storage = get_storage_client()
        path = f"{registry.container_name}/{registry.blob_path}" if registry.container_name else registry.blob_path

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                data = pool.submit(asyncio.run, storage.read(path)).result()
        else:
            data = asyncio.run(storage.read(path))
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return f"{registry.title} {registry.blob_path}"


def _clip(value: str, size: int = 450) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) <= size:
        return cleaned
    return cleaned[: size - 3] + "..."


def _build_anchors(doc: DocumentRegistry, doc_type: str, text: str) -> list[dict[str, str | None]]:
    lowered = text.lower()
    anchors: list[dict[str, str | None]] = []

    if "netz" in lowered and "fund" in lowered:
        anchors.append({"anchor_type": "FUND_NAME", "anchor_value": "Netz Fund", "source_snippet": _clip(text), "page_reference": None})

    if any(token in lowered for token in ["administrator", "custodian", "counsel", "service provider"]):
        for token in ["administrator", "custodian", "counsel", "service provider"]:
            if token in lowered:
                anchors.append({"anchor_type": "PROVIDER_NAME", "anchor_value": token.title(), "source_snippet": _clip(text), "page_reference": None})

    for match in DATE_RE.finditer(text):
        anchors.append({"anchor_type": "EFFECTIVE_DATE", "anchor_value": match.group(1).replace("/", "-"), "source_snippet": _clip(text), "page_reference": None})

    law_match = LAW_RE.search(text)
    if law_match:
        anchors.append({"anchor_type": "GOVERNING_LAW", "anchor_value": _clip(law_match.group(1).strip(), 120), "source_snippet": _clip(text), "page_reference": None})

    for match in SECTION_RE.finditer(text):
        anchors.append({"anchor_type": "REGULATORY_REFERENCE", "anchor_value": f"{match.group(1)} {match.group(2)}", "source_snippet": _clip(text), "page_reference": None})

    for keyword in OBLIGATION_KEYWORDS:
        if keyword in lowered:
            anchors.append({"anchor_type": "OBLIGATION_KEYWORD", "anchor_value": keyword, "source_snippet": _clip(text), "page_reference": None})

    if not anchors:
        anchors.append({"anchor_type": "DOC_TYPE", "anchor_value": doc_type, "source_snippet": _clip(text), "page_reference": None})

    return anchors[:40]


def extract_knowledge_anchors(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> list[KnowledgeAnchor]:
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

    doc_ids = [doc.id for doc, _ in rows]
    if doc_ids:
        db.execute(delete(KnowledgeAnchor).where(
            KnowledgeAnchor.fund_id == fund_id,
            KnowledgeAnchor.doc_id.in_(doc_ids),
        ))

    all_new_anchors: list[KnowledgeAnchor] = []
    for doc, classification in rows:
        text = _extract_text(doc)
        anchors = _build_anchors(doc, classification.doc_type, text)

        for anchor in anchors:
            all_new_anchors.append(KnowledgeAnchor(
                fund_id=fund_id,
                access_level="internal",
                doc_id=doc.id,
                anchor_type=str(anchor["anchor_type"]),
                anchor_value=str(anchor["anchor_value"]),
                source_snippet=anchor.get("source_snippet"),
                page_reference=anchor.get("page_reference"),
                created_by=actor_id,
                updated_by=actor_id,
            ))

    if all_new_anchors:
        db.add_all(all_new_anchors)
        db.flush()

    db.commit()
    return all_new_anchors
