from __future__ import annotations

import calendar
import json
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.modules.ai.models import AIAnswer, AIAnswerCitation, AIQuestion
from app.domains.credit.modules.documents.models import Document
from app.domains.credit.reporting.enums import (
    MonthlyPackType,
    NavSnapshotStatus,
    ReportPackStatus,
    ValuationMethod,
)
from app.domains.credit.reporting.models.asset_valuation_snapshots import AssetValuationSnapshot
from app.domains.credit.reporting.models.investor_statements import InvestorStatement
from app.domains.credit.reporting.models.nav_snapshots import NAVSnapshot
from app.domains.credit.reporting.models.report_packs import MonthlyReportPack
from app.services.blob_storage import download_bytes, upload_bytes_append_only

router = APIRouter(tags=["Reporting"], dependencies=[Depends(require_fund_access())])


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_period_month(period_month: str) -> tuple[int, int]:
    raw = (period_month or "").strip()
    if len(raw) != 7 or raw[4] != "-":
        raise ValueError("period_month must be YYYY-MM")
    year = int(raw[0:4])
    month = int(raw[5:7])
    if month < 1 or month > 12:
        raise ValueError("period_month month must be 01..12")
    return year, month


def _month_start_end(period_month: str) -> tuple[date, date]:
    year, month = _parse_period_month(period_month)
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return start, end


def _snapshot_out(s: NAVSnapshot) -> dict:
    return {
        "id": str(s.id),
        "fund_id": str(s.fund_id),
        "period_month": s.period_month,
        "nav_total_usd": float(s.nav_total_usd),
        "cash_balance_usd": float(s.cash_balance_usd),
        "assets_value_usd": float(s.assets_value_usd),
        "liabilities_usd": float(s.liabilities_usd),
        "status": s.status.value,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "created_by": s.created_by,
        "finalized_at": s.finalized_at.isoformat() if s.finalized_at else None,
        "finalized_by": s.finalized_by,
        "published_at": s.published_at.isoformat() if s.published_at else None,
        "published_by": s.published_by,
    }


def _valuation_out(v: AssetValuationSnapshot) -> dict:
    return {
        "id": str(v.id),
        "nav_snapshot_id": str(v.nav_snapshot_id),
        "asset_id": str(v.asset_id),
        "asset_type": v.asset_type,
        "valuation_usd": float(v.valuation_usd),
        "valuation_method": v.valuation_method.value,
        "supporting_document_id": str(v.supporting_document_id) if v.supporting_document_id else None,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "created_by": v.created_by,
    }


def _pack_out(p: MonthlyReportPack) -> dict:
    return {
        "id": str(p.id),
        "fund_id": str(p.fund_id),
        "nav_snapshot_id": str(p.nav_snapshot_id) if p.nav_snapshot_id else None,
        "blob_path": p.blob_path,
        "generated_at": p.generated_at.isoformat() if p.generated_at else None,
        "generated_by": p.generated_by,
        "pack_type": p.pack_type.value if p.pack_type else None,
        "status": p.status.value if getattr(p, "status", None) else None,
        "published_at": p.published_at.isoformat() if p.published_at else None,
    }


@router.post("/funds/{fund_id}/reports/nav/snapshots")
def create_nav_snapshot(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP"])),
):
    period_month = str(payload.get("period_month") or "").strip()
    try:
        _parse_period_month(period_month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    required = ["nav_total_usd", "cash_balance_usd", "assets_value_usd", "liabilities_usd"]
    for k in required:
        if payload.get(k) is None:
            raise HTTPException(status_code=400, detail=f"{k} is required")

    snap = NAVSnapshot(
        fund_id=fund_id,
        access_level="internal",
        period_month=period_month,
        nav_total_usd=float(payload["nav_total_usd"]),
        cash_balance_usd=float(payload["cash_balance_usd"]),
        assets_value_usd=float(payload["assets_value_usd"]),
        liabilities_usd=float(payload["liabilities_usd"]),
        status=NavSnapshotStatus.DRAFT,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(snap)
    db.flush()

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="NAV_SNAPSHOT_CREATED",
        entity_type="nav_snapshot",
        entity_id=snap.id,
        before=None,
        after=_snapshot_out(snap),
    )
    db.commit()
    db.refresh(snap)
    return _snapshot_out(snap)


@router.get("/funds/{fund_id}/reports/nav/snapshots")
def list_nav_snapshots(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR", "INVESTMENT_TEAM"])),
):
    snaps = list(
        db.execute(
            select(NAVSnapshot)
            .where(NAVSnapshot.fund_id == fund_id)
            .order_by(NAVSnapshot.period_month.desc(), NAVSnapshot.created_at.desc()),
        )
        .scalars()
        .all(),
    )

    return {"items": [_snapshot_out(s) for s in snaps]}


@router.get("/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}")
def get_nav_snapshot(
    fund_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR", "INVESTMENT_TEAM"])),
):
    snap = db.execute(
        select(NAVSnapshot).where(NAVSnapshot.fund_id == fund_id, NAVSnapshot.id == snapshot_id),
    ).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="Not found")

    snaps = list(
        db.execute(
            select(NAVSnapshot)
            .where(NAVSnapshot.fund_id == fund_id)
            .order_by(NAVSnapshot.period_month.desc(), NAVSnapshot.created_at.desc()),
        )
        .scalars()
        .all(),
    )
    return {"snapshot": _snapshot_out(snap), "assets": [_valuation_out(v) for v in vals]}


@router.post("/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/finalize")
def finalize_nav_snapshot(
    fund_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP"])),
):
    snap = db.execute(
        select(NAVSnapshot).where(NAVSnapshot.fund_id == fund_id, NAVSnapshot.id == snapshot_id),
    ).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="Not found")

    if snap.status != NavSnapshotStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Snapshot must be DRAFT to finalize")

    vals = list(
        db.execute(
            select(AssetValuationSnapshot).where(
                AssetValuationSnapshot.fund_id == fund_id,
                AssetValuationSnapshot.nav_snapshot_id == snap.id,
            ),
        )
        .scalars()
        .all(),
    )

    missing_evidence = [
        str(v.id)
        for v in vals
        if v.valuation_method != ValuationMethod.AMORTIZED_COST and not v.supporting_document_id
    ]
    if missing_evidence:
        raise HTTPException(
            status_code=400,
            detail=f"Missing supporting_document_id for valuations: {', '.join(missing_evidence)}",
        )

    before = _snapshot_out(snap)
    snap.status = NavSnapshotStatus.FINALIZED
    snap.finalized_at = _utcnow()
    snap.finalized_by = actor.id
    snap.updated_by = actor.id

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="NAV_SNAPSHOT_FINALIZED",
        entity_type="nav_snapshot",
        entity_id=snap.id,
        before=before,
        after=_snapshot_out(snap),
    )

    db.commit()
    db.refresh(snap)
    return _snapshot_out(snap)


@router.post("/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/publish")
def publish_nav_snapshot(
    fund_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE"])),
):
    snap = db.execute(
        select(NAVSnapshot).where(NAVSnapshot.fund_id == fund_id, NAVSnapshot.id == snapshot_id),
    ).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="Not found")

    if snap.status != NavSnapshotStatus.FINALIZED:
        raise HTTPException(status_code=400, detail="Snapshot must be FINALIZED to publish")

    before = _snapshot_out(snap)
    snap.status = NavSnapshotStatus.PUBLISHED
    snap.published_at = _utcnow()
    snap.published_by = actor.id
    snap.updated_by = actor.id

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="NAV_SNAPSHOT_PUBLISHED",
        entity_type="nav_snapshot",
        entity_id=snap.id,
        before=before,
        after=_snapshot_out(snap),
    )

    db.commit()
    db.refresh(snap)
    return _snapshot_out(snap)


@router.post("/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/assets")
def record_asset_valuation(
    fund_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP"])),
):
    snap = db.execute(
        select(NAVSnapshot).where(NAVSnapshot.fund_id == fund_id, NAVSnapshot.id == snapshot_id),
    ).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="Not found")

    if snap.status != NavSnapshotStatus.DRAFT:
        raise HTTPException(status_code=400, detail="Snapshot is frozen (not DRAFT)")

    try:
        asset_id = uuid.UUID(str(payload.get("asset_id")))
    except Exception:
        raise HTTPException(status_code=400, detail="asset_id must be a UUID")

    asset_type = str(payload.get("asset_type") or "").strip()
    if not asset_type:
        raise HTTPException(status_code=400, detail="asset_type is required")

    if payload.get("valuation_usd") is None:
        raise HTTPException(status_code=400, detail="valuation_usd is required")

    try:
        method = ValuationMethod(str(payload.get("valuation_method") or "").strip().upper())
    except Exception:
        raise HTTPException(status_code=400, detail="valuation_method is invalid")

    supporting_document_id = payload.get("supporting_document_id")
    if method != ValuationMethod.AMORTIZED_COST:
        if not supporting_document_id:
            raise HTTPException(status_code=400, detail="supporting_document_id is required for this valuation_method")

    doc_id: uuid.UUID | None = None
    if supporting_document_id:
        try:
            doc_id = uuid.UUID(str(supporting_document_id))
        except Exception:
            raise HTTPException(status_code=400, detail="supporting_document_id must be a UUID")

        exists = db.execute(select(Document).where(Document.fund_id == fund_id, Document.id == doc_id)).scalar_one_or_none()
        if not exists:
            raise HTTPException(status_code=400, detail="supporting_document_id not found for this fund")

    dup = db.execute(
        select(AssetValuationSnapshot).where(
            AssetValuationSnapshot.fund_id == fund_id,
            AssetValuationSnapshot.nav_snapshot_id == snap.id,
            AssetValuationSnapshot.asset_id == asset_id,
        ),
    ).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=400, detail="Valuation for this asset already recorded in this snapshot")

    v = AssetValuationSnapshot(
        fund_id=fund_id,
        access_level="internal",
        nav_snapshot_id=snap.id,
        asset_id=asset_id,
        asset_type=asset_type,
        valuation_usd=float(payload["valuation_usd"]),
        valuation_method=method,
        supporting_document_id=doc_id,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(v)
    db.flush()

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="ASSET_VALUATION_RECORDED",
        entity_type="asset_valuation_snapshot",
        entity_id=v.id,
        before=None,
        after=_valuation_out(v),
    )

    db.commit()
    db.refresh(v)
    return _valuation_out(v)


@router.get("/funds/{fund_id}/reports/nav/snapshots/{snapshot_id}/assets")
def list_asset_valuations(
    fund_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR", "INVESTMENT_TEAM"])),
):
    snap = db.execute(
        select(NAVSnapshot).where(NAVSnapshot.fund_id == fund_id, NAVSnapshot.id == snapshot_id),
    ).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="Not found")

    vals = list(
        db.execute(
            select(AssetValuationSnapshot)
            .where(AssetValuationSnapshot.fund_id == fund_id, AssetValuationSnapshot.nav_snapshot_id == snap.id)
            .order_by(AssetValuationSnapshot.created_at.asc()),
        )
        .scalars()
        .all(),
    )

    return {"items": [_valuation_out(v) for v in vals]}


def _export_evidence_pack(db: Session, *, fund_id: uuid.UUID, limit: int, generated_by: str | None) -> dict:
    answers = list(
        db.execute(select(AIAnswer).where(AIAnswer.fund_id == fund_id).order_by(AIAnswer.created_at_utc.desc()).limit(limit)).scalars().all(),
    )
    answer_ids = [a.id for a in answers]
    questions = list(
        db.execute(select(AIQuestion).where(AIQuestion.fund_id == fund_id, AIQuestion.id.in_([a.question_id for a in answers]))).scalars().all(),
    )
    by_q = {q.id: q for q in questions}

    citations = []
    if answer_ids:
        citations = list(
            db.execute(select(AIAnswerCitation).where(AIAnswerCitation.fund_id == fund_id, AIAnswerCitation.answer_id.in_(answer_ids))).scalars().all(),
        )
    by_answer: dict[uuid.UUID, list[AIAnswerCitation]] = {}
    for c in citations:
        by_answer.setdefault(c.answer_id, []).append(c)

    manifest = {"fund_id": str(fund_id), "generated_by": generated_by, "items": []}
    for a in answers:
        q = by_q.get(a.question_id)
        manifest["items"].append(
            {
                "question_id": str(a.question_id),
                "answer_id": str(a.id),
                "question": q.question_text if q else None,
                "answer": a.answer_text,
                "created_at_utc": a.created_at_utc.isoformat() if a.created_at_utc else None,
                "citations": [
                    {
                        "chunk_id": str(c.chunk_id),
                        "document_id": str(c.document_id),
                        "version_id": str(c.version_id),
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "excerpt": c.excerpt,
                        "source_blob": c.source_blob,
                    }
                    for c in by_answer.get(a.id, [])
                ],
            },
        )
    return manifest


@router.post("/funds/{fund_id}/reports/monthly-pack/generate")
def generate_monthly_pack(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE"])),
):
    try:
        snapshot_id = uuid.UUID(str(payload.get("nav_snapshot_id")))
    except Exception:
        raise HTTPException(status_code=400, detail="nav_snapshot_id must be a UUID")

    try:
        pack_type = MonthlyPackType(str(payload.get("pack_type") or "").strip().upper())
    except Exception:
        raise HTTPException(status_code=400, detail="pack_type must be INVESTOR_REPORT|AUDITOR_PACK|ADMIN_PACKAGE")

    include_binder = bool(payload.get("include_evidence_binder"))
    binder_limit = int(payload.get("evidence_binder_limit") or 20)
    binder_limit = max(1, min(200, binder_limit))

    snap = db.execute(select(NAVSnapshot).where(NAVSnapshot.fund_id == fund_id, NAVSnapshot.id == snapshot_id)).scalar_one_or_none()
    if not snap:
        raise HTTPException(status_code=404, detail="NAV snapshot not found")
    if snap.status not in (NavSnapshotStatus.FINALIZED, NavSnapshotStatus.PUBLISHED):
        raise HTTPException(status_code=400, detail="NAV snapshot must be FINALIZED to generate pack")

    assets = list(
        db.execute(
            select(AssetValuationSnapshot)
            .where(AssetValuationSnapshot.fund_id == fund_id, AssetValuationSnapshot.nav_snapshot_id == snap.id)
            .order_by(AssetValuationSnapshot.created_at.asc()),
        )
        .scalars()
        .all(),
    )

    manifest: dict = {
        "kind": "MONTHLY_REPORT_PACK",
        "fund_id": str(fund_id),
        "nav_snapshot": _snapshot_out(snap),
        "asset_valuations": [_valuation_out(v) for v in assets],
        "pack_type": pack_type.value,
        "generated_at_utc": _utcnow().isoformat(),
        "generated_by": actor.id,
    }

    if include_binder:
        manifest["evidence_binder"] = _export_evidence_pack(db, fund_id=fund_id, limit=binder_limit, generated_by=actor.id)

    payload_bytes = json.dumps(manifest, ensure_ascii=False, default=str, indent=2).encode("utf-8")

    # Persist append-only output
    blob_name = f"{fund_id}/reports/{snap.period_month}/{pack_type.value}/{uuid.uuid4()}.json"
    write_res = upload_bytes_append_only(
        container=settings.AZURE_STORAGE_MONTHLY_REPORTS_CONTAINER,
        blob_name=blob_name,
        data=payload_bytes,
        content_type="application/json",
        metadata={
            "fund_id": str(fund_id),
            "period_month": snap.period_month,
            "pack_type": pack_type.value,
            "nav_snapshot_id": str(snap.id),
        },
    )

    period_start, period_end = _month_start_end(snap.period_month)
    pack = MonthlyReportPack(
        fund_id=fund_id,
        period_start=period_start,
        period_end=period_end,
        status=ReportPackStatus.PUBLISHED,
        published_at=_utcnow(),
        title=f"Monthly Pack {snap.period_month} ({pack_type.value})",
    )

    pack.nav_snapshot_id = snap.id
    pack.blob_path = write_res.blob_uri
    pack.generated_at = _utcnow()
    pack.generated_by = actor.id
    pack.pack_type = pack_type

    db.add(pack)
    db.flush()

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="MONTHLY_PACK_GENERATED",
        entity_type="monthly_report_pack",
        entity_id=pack.id,
        before=None,
        after=_pack_out(pack),
    )

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="REPORT_PUBLISHED",
        entity_type="monthly_report_pack",
        entity_id=pack.id,
        before=None,
        after={"blob_path": pack.blob_path, "pack_type": pack_type.value, "nav_snapshot_id": str(snap.id)},
    )

    db.commit()
    db.refresh(pack)
    return _pack_out(pack)


@router.get("/funds/{fund_id}/reports/monthly-pack/list")
def list_monthly_packs(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR"])),
):
    packs = list(
        db.execute(select(MonthlyReportPack).where(MonthlyReportPack.fund_id == fund_id).order_by(MonthlyReportPack.created_at.desc()))
        .scalars()
        .all(),
    )
    # EPIC11 v1: only show packs that have blob output metadata
    packs = [p for p in packs if getattr(p, "blob_path", None)]
    return {"items": [_pack_out(p) for p in packs]}


@router.get("/funds/{fund_id}/reports/monthly-pack/{pack_id}/download")
def download_monthly_pack(
    fund_id: uuid.UUID,
    pack_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR"])),
):
    pack = db.execute(select(MonthlyReportPack).where(MonthlyReportPack.fund_id == fund_id, MonthlyReportPack.id == pack_id)).scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail="Not found")
    if not pack.blob_path:
        raise HTTPException(status_code=400, detail="Pack has no blob output")

    data = download_bytes(blob_uri=pack.blob_path)
    filename = f"monthly-pack-{pack_id}.json"
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
        status_code=status.HTTP_200_OK,
    )


@router.post("/funds/{fund_id}/reports/investor-statements/generate")
def generate_investor_statement(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE"])),
):
    period_month = str(payload.get("period_month") or "").strip()
    try:
        _parse_period_month(period_month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # v1: single master statement (investor_id optional)
    investor_id = payload.get("investor_id")
    inv_uuid: uuid.UUID | None = None
    if investor_id:
        try:
            inv_uuid = uuid.UUID(str(investor_id))
        except Exception:
            raise HTTPException(status_code=400, detail="investor_id must be a UUID")

    def _num(k: str) -> float:
        v = payload.get(k)
        if v is None:
            return 0.0
        return float(v)

    statement_manifest = {
        "kind": "INVESTOR_STATEMENT",
        "fund_id": str(fund_id),
        "investor_id": str(inv_uuid) if inv_uuid else None,
        "period_month": period_month,
        "commitment": _num("commitment"),
        "capital_called": _num("capital_called"),
        "distributions": _num("distributions"),
        "ending_balance": _num("ending_balance"),
        "generated_at_utc": _utcnow().isoformat(),
        "generated_by": actor.id,
    }

    payload_bytes = json.dumps(statement_manifest, ensure_ascii=False, default=str, indent=2).encode("utf-8")
    blob_name = f"{fund_id}/reports/{period_month}/INVESTOR_STATEMENT/{uuid.uuid4()}.json"
    write_res = upload_bytes_append_only(
        container=settings.AZURE_STORAGE_MONTHLY_REPORTS_CONTAINER,
        blob_name=blob_name,
        data=payload_bytes,
        content_type="application/json",
        metadata={"fund_id": str(fund_id), "period_month": period_month, "kind": "INVESTOR_STATEMENT"},
    )

    row = InvestorStatement(
        fund_id=fund_id,
        access_level="internal",
        investor_id=inv_uuid,
        period_month=period_month,
        commitment=_num("commitment"),
        capital_called=_num("capital_called"),
        distributions=_num("distributions"),
        ending_balance=_num("ending_balance"),
        blob_path=write_res.blob_uri,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(row)
    db.flush()

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="INVESTOR_STATEMENT_GENERATED",
        entity_type="investor_statement",
        entity_id=row.id,
        before=None,
        after={
            "id": str(row.id),
            "period_month": period_month,
            "blob_path": row.blob_path,
            "investor_id": str(inv_uuid) if inv_uuid else None,
        },
    )

    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "blob_path": row.blob_path, "period_month": row.period_month}


@router.get("/funds/{fund_id}/reports/investor-statements")
def list_investor_statements(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR"])),
):
    rows = list(
        db.execute(select(InvestorStatement).where(InvestorStatement.fund_id == fund_id).order_by(InvestorStatement.created_at.desc()))
        .scalars()
        .all(),
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "period_month": r.period_month,
                "investor_id": str(r.investor_id) if r.investor_id else None,
                "blob_path": r.blob_path,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "created_by": r.created_by,
            }
            for r in rows
        ],
    }


@router.get("/funds/{fund_id}/reports/investor-statements/{statement_id}/download")
def download_investor_statement(
    fund_id: uuid.UUID,
    statement_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR"])),
):
    row = db.execute(
        select(InvestorStatement).where(InvestorStatement.fund_id == fund_id, InvestorStatement.id == statement_id),
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    data = download_bytes(blob_uri=row.blob_path)
    filename = f"investor-statement-{statement_id}.json"
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
        status_code=status.HTTP_200_OK,
    )


@router.get("/funds/{fund_id}/reports/archive")
def get_reporting_archive(
    fund_id: uuid.UUID,
    period_month: str | None = None,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "COMPLIANCE", "AUDITOR", "INVESTMENT_TEAM"])),
):
    """Read-only archive of persisted reporting artifacts (no client-side derivation)."""

    period_month = (period_month or "").strip() or None
    if period_month:
        try:
            _parse_period_month(period_month)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    nav_stmt = select(NAVSnapshot).where(
        NAVSnapshot.fund_id == fund_id,
        NAVSnapshot.status == NavSnapshotStatus.PUBLISHED,
    )
    if period_month:
        nav_stmt = nav_stmt.where(NAVSnapshot.period_month == period_month)
    nav = list(db.execute(nav_stmt.order_by(NAVSnapshot.period_month.desc(), NAVSnapshot.published_at.desc())).scalars().all())

    packs_stmt = select(MonthlyReportPack).where(
        MonthlyReportPack.fund_id == fund_id,
        MonthlyReportPack.status == ReportPackStatus.PUBLISHED,
        MonthlyReportPack.blob_path.is_not(None),
    )
    if period_month:
        start, end = _month_start_end(period_month)
        packs_stmt = packs_stmt.where(MonthlyReportPack.period_start == start, MonthlyReportPack.period_end == end)
    packs = list(db.execute(packs_stmt.order_by(MonthlyReportPack.published_at.desc())).scalars().all())

    stmt_stmt = select(InvestorStatement).where(InvestorStatement.fund_id == fund_id)
    if period_month:
        stmt_stmt = stmt_stmt.where(InvestorStatement.period_month == period_month)
    statements = list(db.execute(stmt_stmt.order_by(InvestorStatement.created_at.desc())).scalars().all())

    return {
        "fund_id": str(fund_id),
        "period_month": period_month,
        "nav_snapshots": [_snapshot_out(s) for s in nav],
        "monthly_packs": [_pack_out(p) for p in packs],
        "investor_statements": [
            {
                "id": str(r.id),
                "period_month": r.period_month,
                "investor_id": str(r.investor_id) if r.investor_id else None,
                "blob_path": r.blob_path,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "created_by": r.created_by,
            }
            for r in statements
        ],
    }
