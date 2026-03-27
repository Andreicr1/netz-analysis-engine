"""AI Memo Chapters sub-router — chapters, evidence pack, IM draft/PDF, regenerate, rebuild."""
from __future__ import annotations

import uuid
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.db.session import get_sync_db_with_rls
from app.core.security.clerk_auth import Actor, require_roles
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.modules.ai._helpers import (
    _normalize_chapter_content,
    _utcnow,
)
from app.domains.credit.modules.ai.models import InvestmentMemorandumDraft
from app.domains.credit.modules.ai.schemas import (
    EvidencePackResponse,
    ICMemorandumPdfResponse,
    InvestmentMemorandumOut,
    InvestmentMemorandumResponse,
    MemoChapterOut,
    MemoChapterRegenerateRequest,
    MemoChapterRegenerateResponse,
    MemoChaptersResponse,
    MemoChapterVersionItem,
    MemoChapterVersionsResponse,
)
from app.domains.credit.modules.deals.models import Deal
from app.shared.enums import Role

router = APIRouter()


@router.get("/pipeline/deals/{deal_id}/memo-chapters", response_model=MemoChaptersResponse)
def get_deal_memo_chapters(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> MemoChaptersResponse:
    """Retrieve all chapters of the current V4 memo book for a deal."""
    from app.domains.credit.modules.ai.models import MemoChapter, MemoEvidencePack

    pack = db.execute(
        select(MemoEvidencePack).where(
            MemoEvidencePack.fund_id == fund_id,
            MemoEvidencePack.deal_id == deal_id,
            MemoEvidencePack.is_current == True,  # noqa: E712
        ).order_by(MemoEvidencePack.generated_at.desc()).limit(1),
    ).scalar_one_or_none()

    if not pack:
        return MemoChaptersResponse(
            asOf=_utcnow(),
            dataLatency=None,
            dataQuality="OK",
            dealId=str(deal_id),
        )

    rows = db.execute(
        select(MemoChapter).where(
            MemoChapter.evidence_pack_id == pack.id,
            MemoChapter.is_current == True,  # noqa: E712
        ).order_by(MemoChapter.chapter_number),
    ).scalars().all()

    chapters = [
        MemoChapterOut(
            chapter_number=ch.chapter_number,
            chapter_tag=ch.chapter_tag,
            chapter_title=ch.chapter_title,
            content_md=ch.content_md,
            model_version=ch.model_version,
            token_count_input=ch.token_count_input,
            token_count_output=ch.token_count_output,
            generated_at=ch.generated_at,
        )
        for ch in rows
    ]

    return MemoChaptersResponse(
        asOf=_utcnow(),
        dataLatency=None,
        dataQuality="OK",
        dealId=str(deal_id),
        evidencePackId=str(pack.id),
        versionTag=pack.version_tag,
        chapters=chapters,
    )


@router.get("/pipeline/deals/{deal_id}/evidence-pack", response_model=EvidencePackResponse)
def get_deal_evidence_pack(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> EvidencePackResponse:
    """Retrieve the current frozen EvidencePack for a deal."""
    from app.domains.credit.modules.ai.models import MemoEvidencePack

    pack = db.execute(
        select(MemoEvidencePack).where(
            MemoEvidencePack.fund_id == fund_id,
            MemoEvidencePack.deal_id == deal_id,
            MemoEvidencePack.is_current == True,  # noqa: E712
        ).order_by(MemoEvidencePack.generated_at.desc()).limit(1),
    ).scalar_one_or_none()

    if not pack:
        return EvidencePackResponse(
            asOf=_utcnow(),
            dataLatency=None,
            dataQuality="OK",
            dealId=str(deal_id),
        )

    return EvidencePackResponse(
        asOf=_utcnow(),
        dataLatency=None,
        dataQuality="OK",
        dealId=str(deal_id),
        evidencePackId=str(pack.id),
        versionTag=pack.version_tag,
        tokenCount=pack.token_count,
        generatedAt=pack.generated_at,
        modelVersion=pack.model_version,
        evidenceJson=pack.evidence_json,
    )


@router.get("/pipeline/deals/{deal_id}/im-draft", response_model=InvestmentMemorandumResponse)
def get_deal_im_draft(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> InvestmentMemorandumResponse:
    """Retrieve the latest Investment Memorandum draft for a deal."""
    row = db.execute(
        select(InvestmentMemorandumDraft)
        .where(
            InvestmentMemorandumDraft.fund_id == fund_id,
            InvestmentMemorandumDraft.deal_id == deal_id,
        )
        .order_by(InvestmentMemorandumDraft.generated_at.desc())
        .limit(1),
    ).scalar_one_or_none()

    return InvestmentMemorandumResponse(
        asOf=row.generated_at if row else _utcnow(),
        dataLatency=None,
        dataQuality="OK",
        item=InvestmentMemorandumOut.model_validate(row) if row else None,
    )


@router.get("/pipeline/deals/{deal_id}/im-pdf", response_model=ICMemorandumPdfResponse)
async def get_deal_im_pdf(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> ICMemorandumPdfResponse:
    """Generate IC Memorandum PDF from V4 memo_chapters (Deep Review)."""
    import logging
    import pathlib
    import re as _re
    from datetime import datetime as _dt

    from ai_engine.pipeline.storage_routing import gold_ic_memo_path
    from app.services.storage_client import get_storage_client

    log = logging.getLogger("ai.im_pdf")

    from sqlalchemy import text as sa_text

    from app.domains.credit.modules.ai.models import DealUnderwritingArtifact as UWArtifact

    result = await db.execute(
        sa_text("""
            SELECT chapter_number, chapter_tag, chapter_title, content_md,
                   version_tag, model_version, generated_at
            FROM memo_chapters
            WHERE deal_id = :did AND fund_id = :fid
                  AND is_current = true
            ORDER BY chapter_number
        """),
        {"did": str(deal_id), "fid": str(fund_id)},
    )
    chapters_rows = result.fetchall()

    if not chapters_rows:
        im_result = await db.execute(
            select(InvestmentMemorandumDraft)
            .where(
                InvestmentMemorandumDraft.fund_id == fund_id,
                InvestmentMemorandumDraft.deal_id == deal_id,
            )
            .order_by(InvestmentMemorandumDraft.generated_at.desc())
            .limit(1),
        )
        im_row = im_result.scalar_one_or_none()
        if not im_row:
            return ICMemorandumPdfResponse(
                available=False,
                message="No IC Memorandum chapters found. Run Deep Review V4 first.",
            )
        return ICMemorandumPdfResponse(
            available=False,
            message="No V4 memo chapters found for this deal. Run Deep Review V4 to generate.",
        )

    chapters = [
        {
            "number": r[0],
            "tag": r[1],
            "title": r[2],
            "content": r[3] or "",
            "version_tag": r[4] or "",
            "model": r[5] or "",
        }
        for r in chapters_rows
    ]

    artifact_result = await db.execute(
        select(UWArtifact)
        .where(UWArtifact.deal_id == deal_id, UWArtifact.is_active == True)  # noqa: E712
        .order_by(UWArtifact.created_at.desc())
        .limit(1),
    )
    artifact_row = artifact_result.scalar_one_or_none()

    artifact = {}
    if artifact_row:
        artifact = {
            "recommendation": artifact_row.recommendation or "CONDITIONAL",
            "confidence_level": artifact_row.confidence_level or "MEDIUM",
            "risk_band": artifact_row.risk_band or "HIGH",
            "chapters_completed": artifact_row.chapters_completed or len(chapters),
            "model_version": artifact_row.model_version or "gpt-4.1",
            "version_number": artifact_row.version_number or 1,
            "created_at": artifact_row.generated_at,
        }

    deal_result = await db.execute(
        select(Deal).where(Deal.id == deal_id),
    )
    deal_row = deal_result.scalar_one_or_none()
    deal_name = (deal_row.deal_name or deal_row.title) if deal_row else "Unknown Deal"

    version_tag = chapters[0]["version_tag"] if chapters else "v4"
    model_ver = artifact.get("model_version", "gpt-4.1")
    rec = artifact.get("recommendation", "CONDITIONAL")
    risk_band = artifact.get("risk_band", "HIGH")
    confidence = artifact.get("confidence_level", "MEDIUM")
    ch_done = artifact.get("chapters_completed", len(chapters))
    created_at = artifact.get("created_at")
    gen_str = created_at.strftime("%Y-%m-%d %H:%M UTC") if created_at else _dt.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    lines.append(f"# Investment Memorandum — {deal_name}")
    lines.append("")
    lines.append(f"*V4 Pipeline | {version_tag} | Model: {model_ver}*")
    lines.append("")
    lines.append(f"*Generated: {gen_str} | Chapters: {ch_done}/14*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("| **Field** | **Value** |")
    lines.append("|:---|:---|")
    lines.append(f"| **Deal Name** | {deal_name} |")
    lines.append(f"| **Version Tag** | {version_tag} |")
    lines.append(f"| **IC Recommendation** | {rec} |")
    lines.append(f"| **Risk Band** | {risk_band} |")
    lines.append(f"| **Confidence Level** | {confidence} |")
    lines.append(f"| **Model** | {model_ver} |")
    lines.append(f"| **Chapters** | {ch_done}/14 |")
    lines.append(f"| **Generated** | {gen_str} |")
    lines.append("| **Pipeline Version** | V4 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for ch in chapters:
        content = ch["content"].strip()
        if not content:
            continue
        content = _normalize_chapter_content(
            content, ch["number"], ch["title"],
        )
        lines.append("")
        lines.append("---")
        lines.append("")
        has_heading = _re.match(r"^##\s+\d+\.", content)
        if not has_heading:
            lines.append(f"## {ch['number']}. {ch['title']}")
            lines.append("")
        lines.append(content)
    lines.append("")
    md_text = "\n".join(lines)

    from ai_engine.pdf.memo_md_to_pdf import generate_memo_pdf

    safe_version = _re.sub(r'[<>:"/\\|?*]', "_", version_tag)
    local_cache_dir = pathlib.Path("public/ic-memoranda") / str(deal_id)
    local_cache_dir.mkdir(parents=True, exist_ok=True)
    local_cache_path = local_cache_dir / f"{safe_version}.pdf"

    md_path = local_cache_dir / f"{safe_version}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    try:
        generate_memo_pdf(str(md_path), str(local_cache_path))
    except Exception as exc:
        log.error("PDF generation failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

    generated_at_dt = created_at or _dt.now(UTC)

    org_id = _role_guard.organization_id
    filename = f"IC_Memorandum_{safe_version}.pdf"
    storage_path = gold_ic_memo_path(org_id, str(deal_id), filename)
    storage = get_storage_client()

    with open(local_cache_path, "rb") as f:
        pdf_bytes = f.read()

    if not await storage.exists(storage_path):
        await storage.write(storage_path, pdf_bytes, content_type="application/pdf")
        log.info("IC Memo uploaded: %s", storage_path)

    signed_url = await storage.generate_read_url(storage_path, expires_in=1800)
    return ICMemorandumPdfResponse(
        signedPdfUrl=signed_url,
        versionTag=version_tag,
        generatedAt=generated_at_dt,
        modelVersion=model_ver,
    )


@router.get("/pipeline/deals/{deal_id}/im-pdf/download")
def download_deal_im_pdf(
    deal_id: uuid.UUID,
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Serve a locally-cached IC Memorandum PDF directly (dev fallback)."""
    import pathlib
    cache_dir = pathlib.Path("public/ic-memoranda") / str(deal_id)
    pdfs = sorted(cache_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True) if cache_dir.exists() else []
    if not pdfs:
        raise HTTPException(status_code=404, detail="No cached PDF found. Request /im-pdf first to generate.")
    return FileResponse(
        path=str(pdfs[0]),
        media_type="application/pdf",
        filename=f"IC_Memorandum_{deal_id}.pdf",
    )


@router.get(
    "/pipeline/deals/{deal_id}/memo-chapters/versions",
    response_model=MemoChapterVersionsResponse,
)
def get_memo_chapter_versions(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
) -> MemoChapterVersionsResponse:
    """Return the current chapter versions for a deal's IC Memorandum."""
    from sqlalchemy import text as sa_text

    rows = db.execute(
        sa_text("""
            SELECT DISTINCT ON (chapter_number)
                   chapter_number, chapter_tag, chapter_title,
                   version_tag, model_version, generated_at,
                   content_md, evidence_pack_id
            FROM memo_chapters
            WHERE deal_id = :did AND fund_id = :fid
            ORDER BY chapter_number, generated_at DESC NULLS LAST
        """),
        {"did": str(deal_id), "fid": str(fund_id)},
    ).fetchall()

    chapters: list[MemoChapterVersionItem] = []
    version_tags: set[str] = set()

    for r in rows:
        content_md = r[6] or ""
        preview = (content_md[:200] + "...") if len(content_md) > 200 else content_md
        vtag = r[3] or ""
        if vtag:
            version_tags.add(vtag)
        chapters.append(MemoChapterVersionItem(
            chapter_number=r[0],
            chapter_tag=r[1],
            chapter_title=r[2],
            version_tag=r[3],
            model_version=r[4],
            generated_at=r[5],
            content_preview=preview,
            evidence_pack_id=str(r[7]) if r[7] else None,
        ))

    return MemoChapterVersionsResponse(
        deal_id=str(deal_id),
        chapters=chapters,
        total_chapters=len(chapters),
        version_mix=len(version_tags) > 1,
    )


@router.post(
    "/pipeline/deals/{deal_id}/memo-chapters/{chapter_number}/regenerate",
    response_model=MemoChapterRegenerateResponse,
)
def regenerate_memo_chapter(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    chapter_number: int,
    body: MemoChapterRegenerateRequest,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> MemoChapterRegenerateResponse:
    """Regenerate a single IC Memorandum chapter and persist the result."""
    import json
    import logging
    from datetime import datetime as _dt

    from sqlalchemy import update

    log = logging.getLogger("ai.regenerate_chapter")

    from vertical_engines.credit.memo import (
        CHAPTER_REGISTRY,
        generate_chapter,
        select_chapter_chunks,
    )

    registry_entry = None
    for ch_num, ch_tag, ch_title in CHAPTER_REGISTRY:
        if ch_num == chapter_number:
            registry_entry = (ch_num, ch_tag, ch_title)
            break

    if registry_entry is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid chapter_number {chapter_number}. Must be 1-14.",
        )

    ch_num, ch_tag, ch_title = registry_entry

    from app.domains.credit.modules.ai.models import MemoChapter, MemoEvidencePack

    pack_row = db.execute(
        select(MemoEvidencePack).where(
            MemoEvidencePack.deal_id == deal_id,
            MemoEvidencePack.fund_id == fund_id,
            MemoEvidencePack.is_current == True,  # noqa: E712
        ).order_by(MemoEvidencePack.generated_at.desc()).limit(1),
    ).scalar_one_or_none()

    if not pack_row:
        raise HTTPException(
            status_code=404,
            detail="No current EvidencePack found for this deal. Run Deep Review V4 first.",
        )

    evidence_pack: dict = pack_row.evidence_json
    evidence_pack_id = pack_row.id

    from app.domains.credit.modules.deals.models import Deal
    from vertical_engines.credit.retrieval import (
        build_ic_corpus,
        gather_chapter_evidence,
    )

    deal_row = db.execute(
        select(Deal).where(Deal.id == deal_id),
    ).scalar_one_or_none()
    deal_name = (deal_row.deal_name or deal_row.title) if deal_row else "Unknown Deal"

    org_id = str(_role_guard.organization_id) if _role_guard.organization_id else None

    chapter_evidence: dict = {}
    ch_result = gather_chapter_evidence(
        chapter_key=ch_tag,
        deal_name=deal_name,
        fund_id=str(fund_id),
        deal_id=str(deal_id),
        organization_id=org_id,
    )
    chapter_evidence[ch_tag] = ch_result

    corpus_result = build_ic_corpus(chapter_evidence)
    raw_chunks = corpus_result["raw_chunks"]
    evidence_map = corpus_result["evidence_map"]
    chunk_source = raw_chunks or evidence_map

    from ai_engine.model_config import get_model
    from ai_engine.openai_client import create_completion

    def call_openai_fn(
        system: str, user: str, *, max_tokens: int = 8000, model: str | None = None,
    ) -> dict:
        effective_model = model or get_model("memo")
        result = create_completion(
            system_prompt=system,
            user_prompt=user,
            model=effective_model,
            max_tokens=max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"},
            stage="memo",
        )
        raw = result.text or ""
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    ch_model = get_model(ch_tag)
    ch_evidence = select_chapter_chunks(chunk_source, ch_tag)

    log.info(
        "REGENERATE ch%02d (%s) with %d evidence chunks, model=%s",
        ch_num, ch_tag, len(ch_evidence), ch_model,
    )

    chapter_result = generate_chapter(
        chapter_num=ch_num,
        chapter_tag=ch_tag,
        chapter_title=ch_title,
        evidence_pack=evidence_pack,
        evidence_chunks=ch_evidence,
        call_openai_fn=call_openai_fn,
        model=ch_model,
    )

    section_text = chapter_result.get("section_text", "")
    section_text = section_text.replace("\x00", "")

    now = _dt.now(UTC)

    db.execute(
        update(MemoChapter)
        .where(
            MemoChapter.deal_id == deal_id,
            MemoChapter.fund_id == fund_id,
            MemoChapter.chapter_number == ch_num,
            MemoChapter.is_current == True,  # noqa: E712
        )
        .values(is_current=False),
    )

    new_row = MemoChapter(
        fund_id=fund_id,
        deal_id=deal_id,
        evidence_pack_id=evidence_pack_id,
        chapter_number=ch_num,
        chapter_tag=ch_tag,
        chapter_title=ch_title[:200],
        content_md=section_text,
        version_tag=(body.version_tag or "v4-rerun-http")[:40],
        generated_at=now,
        model_version=ch_model[:80],
        token_count_input=len(json.dumps(evidence_pack, default=str)) // 4,
        token_count_output=len(section_text) // 4,
        is_current=True,
        created_by=body.actor_id or "ai-engine",
        updated_by=body.actor_id or "ai-engine",
    )
    db.add(new_row)
    db.commit()

    log.info(
        "REGENERATE_DONE ch%02d (%s): %d chars",
        ch_num, ch_tag, len(section_text),
    )

    return MemoChapterRegenerateResponse(
        deal_id=str(deal_id),
        chapter_number=ch_num,
        chapter_tag=ch_tag,
        chapter_title=ch_title,
        version_tag=body.version_tag or "v4-rerun-http",
        model_version=ch_model,
        generated_at=now,
        content_md=section_text,
        chars=len(section_text),
    )


@router.post(
    "/pipeline/deals/{deal_id}/im-pdf/rebuild",
    response_model=ICMemorandumPdfResponse,
)
async def rebuild_deal_im_pdf(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM])),
) -> ICMemorandumPdfResponse:
    """Force-rebuild IC Memorandum PDF from the latest chapters."""
    import logging
    import pathlib
    import re as _re
    from datetime import datetime as _dt

    from ai_engine.pipeline.storage_routing import gold_ic_memo_path
    from app.services.storage_client import get_storage_client

    log = logging.getLogger("ai.im_pdf_rebuild")

    from sqlalchemy import text as sa_text

    from app.domains.credit.modules.ai.models import DealUnderwritingArtifact as UWArtifact

    result = await db.execute(
        sa_text("""
            SELECT chapter_number, chapter_tag, chapter_title, content_md,
                   version_tag, model_version, generated_at
            FROM memo_chapters
            WHERE deal_id = :did AND fund_id = :fid
                  AND is_current = true
            ORDER BY chapter_number
        """),
        {"did": str(deal_id), "fid": str(fund_id)},
    )
    chapters_rows = result.fetchall()

    if not chapters_rows:
        raise HTTPException(
            status_code=404,
            detail="No IC Memorandum chapters found. Run Deep Review V4 first.",
        )

    chapters = [
        {
            "number": r[0],
            "tag": r[1],
            "title": r[2],
            "content": r[3] or "",
            "version_tag": r[4] or "",
            "model": r[5] or "",
        }
        for r in chapters_rows
    ]

    artifact_result = await db.execute(
        select(UWArtifact)
        .where(UWArtifact.deal_id == deal_id, UWArtifact.is_active == True)  # noqa: E712
        .order_by(UWArtifact.created_at.desc())
        .limit(1),
    )
    artifact_row = artifact_result.scalar_one_or_none()

    artifact = {}
    if artifact_row:
        artifact = {
            "recommendation": artifact_row.recommendation or "CONDITIONAL",
            "confidence_level": artifact_row.confidence_level or "MEDIUM",
            "risk_band": artifact_row.risk_band or "HIGH",
            "chapters_completed": artifact_row.chapters_completed or len(chapters),
            "model_version": artifact_row.model_version or "gpt-4.1",
            "version_number": artifact_row.version_number or 1,
            "created_at": artifact_row.generated_at,
        }

    deal_result = await db.execute(
        select(Deal).where(Deal.id == deal_id),
    )
    deal_row = deal_result.scalar_one_or_none()
    deal_name = (deal_row.deal_name or deal_row.title) if deal_row else "Unknown Deal"

    now = _dt.now(UTC)
    timestamp = now.strftime("%Y%m%d-%H%M")
    version_tag = f"rebuilt-{timestamp}"
    model_ver = "mixed"
    rec = artifact.get("recommendation", "CONDITIONAL")
    risk_band = artifact.get("risk_band", "HIGH")
    confidence = artifact.get("confidence_level", "MEDIUM")
    ch_done = artifact.get("chapters_completed", len(chapters))
    gen_str = now.strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    lines.append(f"# Investment Memorandum — {deal_name}")
    lines.append("")
    lines.append(f"*V4 Pipeline | {version_tag} | Model: {model_ver}*")
    lines.append("")
    lines.append(f"*Generated: {gen_str} | Chapters: {ch_done}/14*")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("| **Field** | **Value** |")
    lines.append("|:---|:---|")
    lines.append(f"| **Deal Name** | {deal_name} |")
    lines.append(f"| **Version Tag** | {version_tag} |")
    lines.append(f"| **IC Recommendation** | {rec} |")
    lines.append(f"| **Risk Band** | {risk_band} |")
    lines.append(f"| **Confidence Level** | {confidence} |")
    lines.append(f"| **Model** | {model_ver} |")
    lines.append(f"| **Chapters** | {ch_done}/14 |")
    lines.append(f"| **Generated** | {gen_str} |")
    lines.append("| **Pipeline Version** | V4 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for ch in chapters:
        content = ch["content"].strip()
        if not content:
            continue
        content = _normalize_chapter_content(
            content, ch["number"], ch["title"],
        )
        lines.append("")
        lines.append("---")
        lines.append("")
        has_heading = _re.match(r"^##\s+\d+\.", content)
        if not has_heading:
            lines.append(f"## {ch['number']}. {ch['title']}")
            lines.append("")
        lines.append(content)
    lines.append("")
    md_text = "\n".join(lines)

    from ai_engine.pdf.memo_md_to_pdf import generate_memo_pdf

    safe_version = _re.sub(r'[<>:"/\\|?*]', "_", version_tag)
    local_cache_dir = pathlib.Path("public/ic-memoranda") / str(deal_id)
    local_cache_dir.mkdir(parents=True, exist_ok=True)
    local_cache_path = local_cache_dir / f"{safe_version}.pdf"

    md_path = local_cache_dir / f"{safe_version}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    try:
        generate_memo_pdf(str(md_path), str(local_cache_path))
    except Exception as exc:
        log.error("PDF rebuild failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

    org_id = _role_guard.organization_id
    filename = f"IC_Memorandum_rebuilt-{timestamp}.pdf"
    storage_path = gold_ic_memo_path(org_id, str(deal_id), filename)
    storage = get_storage_client()

    with open(local_cache_path, "rb") as f:
        pdf_bytes = f.read()

    await storage.write(storage_path, pdf_bytes, content_type="application/pdf")
    log.info("IC Memo rebuilt and uploaded: %s", storage_path)

    signed_url = await storage.generate_read_url(storage_path, expires_in=1800)
    return ICMemorandumPdfResponse(
        signedPdfUrl=signed_url,
        versionTag=version_tag,
        generatedAt=now,
        modelVersion=model_ver,
    )


@router.get("/pipeline/deals/{deal_id}/pipeline-memo-pdf")
def get_pipeline_memo_pdf(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_sync_db_with_rls),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """Generate and stream a Pipeline Intelligence PDF (ReportLab/Unicode)."""
    import logging
    log = logging.getLogger("ai.pipeline_memo_pdf")

    from ai_engine.pdf.pipeline_memo_pdf import _load_pipeline_data, generate_pipeline_memo_pdf

    try:
        data = _load_pipeline_data(deal_id=str(deal_id))
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="Deal not found or no pipeline intelligence available.",
        )

    if not data.get("research_output"):
        raise HTTPException(
            status_code=404,
            detail="Pipeline intelligence not yet generated for this deal.",
        )

    try:
        pdf_bytes = generate_pipeline_memo_pdf(data)
    except Exception as exc:
        log.error("Pipeline memo PDF generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {exc}",
        )

    from starlette.responses import Response
    safe_name = (data.get("deal_name") or "deal").replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="Pipeline_Memo_{safe_name}.pdf"',
        },
    )
