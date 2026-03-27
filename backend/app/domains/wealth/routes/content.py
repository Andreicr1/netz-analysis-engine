"""Content Production API routes — outlooks, flash reports, spotlights.

Feature-gated by ``FEATURE_WEALTH_CONTENT``.
Content governance: all content has status workflow (draft → review → approved → published).
Self-approval blocked: approved_by != created_by.
Download endpoint checks status >= approved before serving.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import settings
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.content import WealthContent
from app.domains.wealth.schemas.content import ContentSummary, ContentTrigger
from app.shared.enums import Role

logger = structlog.get_logger()

router = APIRouter(prefix="/content", tags=["content"])

_content_semaphore: asyncio.Semaphore | None = None


def _get_content_semaphore() -> asyncio.Semaphore:
    global _content_semaphore
    if _content_semaphore is None:
        _content_semaphore = asyncio.Semaphore(3)
    return _content_semaphore


def _require_feature() -> None:
    """Raise 404 if content production feature is disabled."""
    if not settings.feature_wealth_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content production feature is not enabled",
        )


def _require_ic_role(actor: Actor) -> None:
    """Verify actor has INVESTMENT_TEAM or ADMIN role."""
    if not actor.has_role(Role.INVESTMENT_TEAM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Committee role required",
        )


# ── Trigger endpoints ─────────────────────────────────────────────


@router.post(
    "/outlooks",
    response_model=ContentSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Investment Outlook generation",
)
async def trigger_outlook(
    body: ContentTrigger | None = None,
    language: Literal["pt", "en"] = Query(default="pt", description="Content language"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ContentSummary:
    """Trigger async Investment Outlook generation."""
    _require_feature()
    _require_ic_role(actor)

    content = WealthContent(
        organization_id=org_id,
        content_type="investment_outlook",
        title="Investment Outlook",
        language=language,
        status="draft",
        created_by=user.actor_id,
    )
    db.add(content)
    await db.flush()

    content_id = content.id

    asyncio.create_task(
        _run_content_generation(
            content_id=str(content_id),
            content_type="investment_outlook",
            org_id=org_id,
            actor_id=user.actor_id,
            language=language,
            config=body.config_overrides if body else None,
        ),
    )

    await db.commit()
    return ContentSummary.model_validate(content)


@router.post(
    "/flash-reports",
    response_model=ContentSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Flash Report generation",
)
async def trigger_flash_report(
    body: ContentTrigger | None = None,
    language: Literal["pt", "en"] = Query(default="pt", description="Content language"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ContentSummary:
    """Trigger async Flash Report generation."""
    _require_feature()
    _require_ic_role(actor)

    content = WealthContent(
        organization_id=org_id,
        content_type="flash_report",
        title="Market Flash Report",
        language=language,
        status="draft",
        created_by=user.actor_id,
    )
    db.add(content)
    await db.flush()

    content_id = content.id

    asyncio.create_task(
        _run_content_generation(
            content_id=str(content_id),
            content_type="flash_report",
            org_id=org_id,
            actor_id=user.actor_id,
            language=language,
            config=body.config_overrides if body else None,
            event_context=body.config_overrides if body else None,
        ),
    )

    await db.commit()
    return ContentSummary.model_validate(content)


@router.post(
    "/spotlights",
    response_model=ContentSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Manager Spotlight generation",
)
async def trigger_spotlight(
    instrument_id: uuid.UUID = Query(..., description="Target fund for spotlight"),
    body: ContentTrigger | None = None,
    language: Literal["pt", "en"] = Query(default="pt", description="Content language"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ContentSummary:
    """Trigger async Manager Spotlight generation."""
    _require_feature()
    _require_ic_role(actor)

    # Verify fund exists
    from app.domains.wealth.models.fund import Fund

    fund_result = await db.execute(
        select(Fund).where(Fund.fund_id == instrument_id),
    )
    fund = fund_result.scalar_one_or_none()
    if not fund:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fund {instrument_id} not found",
        )

    content = WealthContent(
        organization_id=org_id,
        content_type="manager_spotlight",
        title=f"Manager Spotlight — {fund.name}",
        language=language,
        status="draft",
        content_data={"instrument_id": str(instrument_id)},
        created_by=user.actor_id,
    )
    db.add(content)
    await db.flush()

    content_id = content.id

    asyncio.create_task(
        _run_content_generation(
            content_id=str(content_id),
            content_type="manager_spotlight",
            org_id=org_id,
            actor_id=user.actor_id,
            language=language,
            config=body.config_overrides if body else None,
            instrument_id=str(instrument_id),
        ),
    )

    await db.commit()
    return ContentSummary.model_validate(content)


# ── List + read ────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[ContentSummary],
    summary="List generated content with status",
)
async def list_content(
    content_type: str | None = Query(default=None, description="Filter by content type"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ContentSummary]:
    """List all wealth content items."""
    _require_feature()

    query = select(WealthContent).order_by(WealthContent.created_at.desc())
    if content_type:
        query = query.where(WealthContent.content_type == content_type)

    result = await db.execute(query)
    items = result.scalars().all()
    return [ContentSummary.model_validate(item) for item in items]


# ── Approval ───────────────────────────────────────────────────────


@router.post(
    "/{content_id}/approve",
    response_model=ContentSummary,
    summary="Approve content (IC role, self-approval blocked)",
)
async def approve_content(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> ContentSummary:
    """Approve content for distribution.

    Self-approval blocked: approver must be different from creator.
    """
    _require_feature()
    _require_ic_role(actor)

    result = await db.execute(
        select(WealthContent).where(WealthContent.id == content_id).with_for_update(),
    )
    content = result.scalar_one_or_none()
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content {content_id} not found",
        )

    if content.status not in ("draft", "review"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content cannot be approved from status '{content.status}'",
        )

    if not content.content_md:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content has not been generated yet (still processing or failed)",
        )

    # Self-approval prevention
    if content.created_by == user.actor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-approval is not allowed. A different IC member must approve.",
        )

    content.status = "approved"
    content.approved_by = user.actor_id
    content.approved_at = datetime.now(UTC)
    await db.commit()

    return ContentSummary.model_validate(content)


# ── Download ───────────────────────────────────────────────────────


@router.get(
    "/{content_id}/download",
    summary="Download content PDF (requires approved status)",
)
async def download_content(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Download content as PDF. Requires status >= approved."""
    _require_feature()

    result = await db.execute(
        select(WealthContent).where(WealthContent.id == content_id),
    )
    content = result.scalar_one_or_none()
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Content {content_id} not found",
        )

    if content.status not in ("approved", "published"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Content must be approved before download (current status: {content.status})",
        )

    if not content.content_md:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content has no generated text",
        )

    # Generate PDF on-demand from content_md
    pdf_buf = await asyncio.to_thread(
        _render_content_pdf,
        content_type=content.content_type,
        content_md=content.content_md,
        language=content.language,
        fund_name=content.title,
    )

    filename = f"{content.content_type}_{content.language}.pdf"
    return Response(
        content=pdf_buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Background generation helpers ──────────────────────────────────


async def _run_content_generation(
    *,
    content_id: str,
    content_type: str,
    org_id: str,
    actor_id: str,
    language: str,
    config: dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    instrument_id: str | None = None,
) -> None:
    """Background task: run content generation in a sync thread."""
    async with _get_content_semaphore():
        try:
            result = await asyncio.to_thread(
                _sync_generate_content,
                content_id=content_id,
                content_type=content_type,
                org_id=org_id,
                actor_id=actor_id,
                language=language,
                config=config,
                event_context=event_context,
                instrument_id=instrument_id,
            )

            # Update content record with result
            from app.core.db.engine import async_session_factory

            async with async_session_factory() as db:
                safe_oid = str(uuid.UUID(org_id)).replace("'", "")
                await db.execute(
                    text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"),
                )
                stmt = select(WealthContent).where(WealthContent.id == uuid.UUID(content_id))
                row = await db.execute(stmt)
                content = row.scalar_one_or_none()
                if content:
                    content.content_md = result.get("content_md")
                    content.status = "review" if result.get("content_md") else "draft"
                    content.content_data = result.get("content_data", content.content_data)
                    await db.commit()

            logger.info(
                "content_generation_completed",
                content_id=content_id,
                content_type=content_type,
                status=result.get("status"),
            )

        except Exception:
            logger.exception(
                "content_generation_background_failed",
                content_id=content_id,
                content_type=content_type,
            )
            # Mark content as failed so the UI can display the error
            try:
                async with async_session_factory() as err_db:
                    safe_oid2 = str(uuid.UUID(org_id)).replace("'", "")
                    await err_db.execute(
                        text(f"SET LOCAL app.current_organization_id = '{safe_oid2}'"),
                    )
                    stmt = select(WealthContent).where(WealthContent.id == uuid.UUID(content_id))
                    row = await err_db.execute(stmt)
                    content = row.scalar_one_or_none()
                    if content:
                        content.status = "failed"
                        content.content_data = {
                            **(content.content_data or {}),
                            "error_message": "Content generation failed. Please try again or contact support.",
                        }
                        await err_db.commit()
            except Exception:
                logger.exception("content_generation_failed_status_update_error", content_id=content_id)


def _sync_generate_content(
    *,
    content_id: str,
    content_type: str,
    org_id: str,
    actor_id: str,
    language: str,
    config: dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    instrument_id: str | None = None,
) -> dict[str, Any]:
    """Sync wrapper: creates sync Session inside thread."""
    from ai_engine.llm import call_openai as _call_openai
    from app.core.db.session import sync_session_factory

    with sync_session_factory() as db:
        db.expire_on_commit = False
        from sqlalchemy import text
        safe_oid = str(org_id).replace("'", "")
        db.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))

        if content_type == "investment_outlook":
            from vertical_engines.wealth.investment_outlook import InvestmentOutlook

            engine = InvestmentOutlook(config=config, call_openai_fn=_call_openai)
            result = engine.generate(
                db, organization_id=org_id, actor_id=actor_id, language=language,
            )
            return {
                "content_md": result.content_md,
                "status": result.status,
            }

        if content_type == "flash_report":
            from vertical_engines.wealth.flash_report import FlashReport

            engine = FlashReport(config=config, call_openai_fn=_call_openai)
            result = engine.generate(
                db, organization_id=org_id, actor_id=actor_id,
                event_context=event_context, language=language,
            )
            return {
                "content_md": result.content_md,
                "status": result.status,
            }

        if content_type == "manager_spotlight":
            from vertical_engines.wealth.manager_spotlight import ManagerSpotlight

            if not instrument_id:
                return {"content_md": None, "status": "failed"}

            engine = ManagerSpotlight(config=config, call_openai_fn=_call_openai)
            result = engine.generate(
                db, instrument_id=instrument_id, organization_id=org_id,
                actor_id=actor_id, language=language,
            )
            return {
                "content_md": result.content_md,
                "content_data": {"instrument_id": instrument_id},
                "status": result.status,
            }

        return {"content_md": None, "status": "failed"}


def _render_content_pdf(
    *,
    content_type: str,
    content_md: str,
    language: str,
    fund_name: str = "",
) -> Any:
    """Render content PDF based on type."""
    from io import BytesIO

    from vertical_engines.wealth.content_pdf import render_content_pdf
    from vertical_engines.wealth.fact_sheet.i18n import LABELS

    labels = LABELS[language]

    _TITLE_MAP: dict[str, str] = {
        "investment_outlook": labels["investment_outlook_title"],
        "flash_report": labels["flash_report_title"],
        "manager_spotlight": labels["manager_spotlight_title"],
    }

    title = _TITLE_MAP.get(content_type)
    if title is None:
        return BytesIO(b"%PDF-1.4\n")

    subtitle = ""
    if content_type == "manager_spotlight":
        subtitle = fund_name or "Fund Manager Analysis"

    return render_content_pdf(
        content_md,
        title=title,
        subtitle=subtitle,
        language=language,
    )
