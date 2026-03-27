"""Fact-Sheet Generation Worker — monthly scheduled generation.

Generates default-language ("pt") fact-sheets for all active model portfolios.
English ("en") versions are generated on-demand via the API.

Uses PostgreSQL advisory lock to prevent concurrent runs.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select, text

logger = structlog.get_logger()


async def run_monthly_fact_sheets() -> dict[str, Any]:
    """Generate fact-sheets for all active model portfolios.

    Called from the worker route trigger via BackgroundTasks.add_task().
    Async so storage writes happen in the event loop (no throwaway loops).

    Returns:
        Summary dict with generation results.
    """
    from app.core.db.session import sync_session_factory
    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.services.storage_client import get_storage_client

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with sync_session_factory() as db:
        db.expire_on_commit = False

        # Advisory lock to prevent concurrent runs
        lock_id = 900_001  # Unique lock ID for fact-sheet worker
        lock_result = db.execute(text(f"SELECT pg_try_advisory_lock({lock_id})"))
        acquired = lock_result.scalar()

        if not acquired:
            logger.info("fact_sheet_worker_skipped", reason="advisory_lock_held")
            return {"status": "skipped", "reason": "Another instance is running"}

        try:
            # Find active portfolios with fund selection
            stmt = (
                select(ModelPortfolio)
                .where(
                    ModelPortfolio.status == "active",
                    ModelPortfolio.fund_selection_schema.isnot(None),
                )
            )
            result = db.execute(stmt)
            portfolios = result.scalars().all()

            # Extract scalar attributes before crossing async boundary
            portfolio_data = [
                (str(p.id), p.organization_id)
                for p in portfolios
            ]

            logger.info("fact_sheet_worker_started", portfolio_count=len(portfolio_data))

            all_pending_writes: list[tuple[str, bytes]] = []

            for pid, org_id in portfolio_data:
                try:
                    pending = _generate_for_portfolio(
                        portfolio_id=pid,
                        organization_id=org_id,
                    )
                    all_pending_writes.extend(pending)
                    results.append({
                        "portfolio_id": pid,
                        "status": "completed",
                    })
                except Exception:
                    logger.exception(
                        "fact_sheet_generation_failed",
                        portfolio_id=pid,
                    )
                    errors.append({
                        "portfolio_id": pid,
                        "error": "generation_failed",
                    })

            db.commit()

        finally:
            db.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))

    # Async storage writes (outside sync session — no throwaway event loops)
    storage = get_storage_client()
    for storage_path, pdf_bytes in all_pending_writes:
        try:
            await storage.write(storage_path, pdf_bytes, content_type="application/pdf")
        except Exception:
            logger.warning("fact_sheet_storage_write_failed", path=storage_path, exc_info=True)

    return {
        "status": "completed",
        "generated": len(results),
        "errors": len(errors),
        "details": results,
        "error_details": errors,
    }


def _generate_for_portfolio(
    *,
    portfolio_id: str,
    organization_id: str,
) -> list[tuple[str, bytes]]:
    """Generate both executive and institutional fact-sheets for a portfolio.

    Uses its own RLS-scoped sync session per portfolio.
    Returns list of (storage_path, pdf_bytes) for async writes.
    """
    from ai_engine.pipeline.storage_routing import gold_fact_sheet_path
    from app.core.db.session import sync_session_factory
    from vertical_engines.wealth.fact_sheet import FactSheetEngine

    engine = FactSheetEngine()
    as_of = date.today()
    language = "pt"  # Default language for scheduled generation
    pending_writes: list[tuple[str, bytes]] = []

    with sync_session_factory() as db:
        db.expire_on_commit = False
        safe_oid = str(organization_id).replace("'", "")
        db.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))

        for fmt in ("executive", "institutional"):
            pdf_buf = engine.generate(
                db,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
                format=fmt,
                language=language,
                as_of=as_of,
            )

            storage_path = gold_fact_sheet_path(
                org_id=uuid.UUID(organization_id),
                vertical="wealth",
                portfolio_id=portfolio_id,
                as_of_date=as_of.isoformat(),
                language=language,
                filename=f"{fmt}.pdf",
            )

            pending_writes.append((storage_path, pdf_buf.read()))

            logger.info(
                "fact_sheet_generated",
                portfolio_id=portfolio_id,
                format=fmt,
                language=language,
                path=storage_path,
            )

    return pending_writes
