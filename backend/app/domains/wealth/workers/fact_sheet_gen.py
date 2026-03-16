"""Fact-Sheet Generation Worker — monthly scheduled generation.

Generates default-language ("pt") fact-sheets for all active model portfolios.
English ("en") versions are generated on-demand via the API.

Uses PostgreSQL advisory lock to prevent concurrent runs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select, text

logger = logging.getLogger(__name__)


def run_monthly_fact_sheets() -> dict[str, Any]:
    """Generate fact-sheets for all active model portfolios.

    Called from the worker route trigger. Runs in a sync thread.

    Returns:
        Summary dict with generation results.
    """
    from app.core.db.session import sync_session_factory
    from app.domains.wealth.models.model_portfolio import ModelPortfolio

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

            logger.info("fact_sheet_worker_started", portfolio_count=len(portfolios))

            for portfolio in portfolios:
                try:
                    _generate_for_portfolio(
                        db,
                        portfolio_id=str(portfolio.id),
                        organization_id=portfolio.organization_id,
                    )
                    results.append({
                        "portfolio_id": str(portfolio.id),
                        "status": "completed",
                    })
                except Exception:
                    logger.exception(
                        "fact_sheet_generation_failed",
                        portfolio_id=str(portfolio.id),
                    )
                    errors.append({
                        "portfolio_id": str(portfolio.id),
                        "error": "generation_failed",
                    })

            db.commit()

        finally:
            db.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))

    return {
        "status": "completed",
        "generated": len(results),
        "errors": len(errors),
        "details": results,
        "error_details": errors,
    }


def _generate_for_portfolio(
    db: Any,
    *,
    portfolio_id: str,
    organization_id: str,
) -> None:
    """Generate both executive and institutional fact-sheets for a portfolio."""
    import asyncio

    from ai_engine.pipeline.storage_routing import gold_fact_sheet_path
    from app.services.storage_client import get_storage_client
    from vertical_engines.wealth.fact_sheet import FactSheetEngine

    engine = FactSheetEngine()
    as_of = date.today()
    language = "pt"  # Default language for scheduled generation

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

        storage = get_storage_client()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                storage.write(storage_path, pdf_buf.read(), content_type="application/pdf")
            )
        finally:
            loop.close()

        logger.info(
            "fact_sheet_generated",
            portfolio_id=portfolio_id,
            format=fmt,
            language=language,
            path=storage_path,
        )
