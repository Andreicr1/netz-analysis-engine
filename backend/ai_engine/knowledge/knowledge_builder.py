from __future__ import annotations

import datetime as dt
import re
import uuid
from collections import defaultdict

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.domains.credit.modules.ai.models import DocumentRegistry, ManagerProfile
from app.domains.credit.modules.documents.models import DocumentChunk, DocumentVersion
from app.services.search_index import AzureSearchMetadataClient


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _ensure_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _manager_name_from_path(root_folder: str | None, folder_path: str | None) -> str | None:
    root = (root_folder or "").strip().lower()
    if root != "2 deals & managers":
        return None
    folder = (folder_path or "").strip().strip("/")
    if not folder:
        return None
    return folder.split("/")[0].strip()


def _infer_strategy(text: str) -> str:
    lowered = text.lower()
    if "real estate" in lowered:
        return "Real Estate Credit"
    if "direct lending" in lowered:
        return "Direct Lending"
    if "distressed" in lowered:
        return "Distressed Credit"
    if "asset-backed" in lowered or "asset backed" in lowered:
        return "Asset-Backed Credit"
    if "private credit" in lowered:
        return "Private Credit"
    return "Not Explicitly Declared"


def _infer_region(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["united states", "u.s.", " us ", "north america"]):
        return "US"
    if any(token in lowered for token in ["europe", "eu", "uk"]):
        return "Europe"
    if any(token in lowered for token in ["latam", "latin america", "brazil"]):
        return "LatAm"
    return "Not Explicitly Declared"


def _infer_vehicle_type(text: str) -> str:
    lowered = text.lower()
    if "closed-end" in lowered or "closed end" in lowered:
        return "Closed-End Fund"
    if "open-end" in lowered or "open end" in lowered:
        return "Open-End Fund"
    if "spv" in lowered:
        return "SPV"
    if "fund" in lowered:
        return "Fund"
    return "Not Explicitly Declared"


def _infer_reporting_cadence(text: str) -> str:
    lowered = text.lower()
    if "quarterly" in lowered:
        return "Quarterly"
    if "monthly" in lowered:
        return "Monthly"
    if "semi-annual" in lowered or "semi annual" in lowered:
        return "Semi-Annual"
    if "annual" in lowered:
        return "Annual"
    return "Not Explicitly Declared"


def _extract_declared_target_return(text: str) -> str | None:
    pattern = re.compile(r"(?:target return|target irr|expected return)\D{0,20}(\d{1,2}(?:\.\d{1,2})?\s?%)", re.IGNORECASE)
    match = pattern.search(text)
    if match:
        return match.group(1).replace(" ", "")
    return None


def _extract_risks(text: str) -> list[str]:
    lowered = text.lower()
    risk_map = {
        "Concentration": ["concentration"],
        "Refinancing": ["refinancing", "refinance"],
        "Liquidity": ["liquidity"],
        "Credit": ["credit risk", "default"],
        "Valuation": ["valuation"],
    }
    detected: list[str] = []
    for label, signals in risk_map.items():
        if any(signal in lowered for signal in signals):
            detected.append(label)
    return detected


def build_manager_profiles(
    db: Session,
    *,
    fund_id: uuid.UUID,
    manager: str | None = None,
    actor_id: str = "ai-engine",
) -> list[ManagerProfile]:
    now = _now_utc()
    manager_filter = (manager or "").strip().lower()

    docs = list(
        db.execute(
            select(DocumentRegistry).where(
                DocumentRegistry.fund_id == fund_id,
                DocumentRegistry.root_folder == "2 Deals & Managers",
            ),
        ).scalars().all(),
    )

    by_manager: dict[str, list[DocumentRegistry]] = defaultdict(list)
    for row in docs:
        name = _manager_name_from_path(row.root_folder, row.folder_path)
        if not name:
            continue
        if manager_filter and manager_filter != name.lower():
            continue
        by_manager[name].append(row)

    # Pre-load ALL chunks for ALL version_ids at once to avoid N+1
    all_version_ids = [
        r.version_id
        for docs in by_manager.values()
        for r in docs
        if r.version_id is not None
    ]
    chunks_by_version: dict[uuid.UUID, list[str]] = defaultdict(list)
    if all_version_ids:
        all_chunk_rows = list(
            db.execute(
                select(DocumentChunk.version_id, DocumentChunk.text)
                .join(DocumentVersion, and_(DocumentVersion.id == DocumentChunk.version_id, DocumentVersion.fund_id == fund_id))
                .where(DocumentChunk.fund_id == fund_id, DocumentChunk.version_id.in_(all_version_ids))
                .limit(2000),
            ).all(),
        )
        for vid, text in all_chunk_rows:
            chunks_by_version[vid].append(text or "")

    saved: list[ManagerProfile] = []
    for manager_name, manager_docs in by_manager.items():
        version_ids = [r.version_id for r in manager_docs]
        combined = "\n".join(
            chunk_text
            for vid in version_ids
            if vid is not None
            for chunk_text in chunks_by_version.get(vid, [])[:80]
        )
        fallback = "\n".join((r.title or "") for r in manager_docs)
        text = combined if combined.strip() else fallback

        source_documents = [
            {
                "documentId": str(d.document_id),
                "versionId": str(d.version_id),
                "title": d.title,
                "path": f"{(d.root_folder or '').strip()}/{(d.folder_path or '').strip()}",
            }
            for d in manager_docs
        ]
        last_update = _ensure_utc(max((d.as_of for d in manager_docs), default=now))

        payload = {
            "fund_id": fund_id,
            "access_level": "internal",
            "name": manager_name,
            "strategy": _infer_strategy(text),
            "region": _infer_region(text),
            "vehicle_type": _infer_vehicle_type(text),
            "declared_target_return": _extract_declared_target_return(text),
            "reporting_cadence": _infer_reporting_cadence(text),
            "key_risks_declared": _extract_risks(text),
            "last_document_update": last_update,
            "source_documents": source_documents,
            "as_of": now,
            "data_latency": max(0, int((now - last_update).total_seconds())) if last_update is not None else None,
            "data_quality": "OK",
            "created_by": actor_id,
            "updated_by": actor_id,
        }

        existing = db.execute(
            select(ManagerProfile).where(
                ManagerProfile.fund_id == fund_id,
                ManagerProfile.name == manager_name,
            ),
        ).scalar_one_or_none()

        if existing is None:
            row = ManagerProfile(**payload)
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
                    "id": f"ai-manager-profile-{item.id}",
                    "fund_id": str(item.fund_id),
                    "title": f"Manager Profile - {item.name}",
                    "content": f"{item.strategy} | {item.region} | {item.reporting_cadence}",
                    "doc_type": "AI_MANAGER_PROFILE",
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
