"""Deep Review V4 — portfolio periodic reviews.

Provides single-investment and batch periodic AI reviews.
Batch reviews use ThreadPoolExecutor with per-thread session isolation.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_engine.prompts import prompt_registry
from app.domains.credit.modules.ai.models import (
    ActiveInvestment,
    InvestmentMemorandumDraft,
    PeriodicReviewReport,
)
from vertical_engines.credit.deep_review.corpus import _gather_investment_texts
from vertical_engines.credit.deep_review.helpers import (
    _MODEL,
    _call_openai,
    _now_utc,
)

logger = structlog.get_logger()


def get_current_im_draft(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
) -> InvestmentMemorandumDraft | None:
    """Return the current (is_current=True) IM draft for a deal.

    Fallback: if no draft has is_current=True (legacy data), return the
    latest by generated_at.  Returns None if no drafts exist.
    """
    # Primary: explicit current pointer
    current = db.execute(
        select(InvestmentMemorandumDraft).where(
            InvestmentMemorandumDraft.fund_id == fund_id,
            InvestmentMemorandumDraft.deal_id == deal_id,
            InvestmentMemorandumDraft.is_current == True,  # noqa: E712
        ),
    ).scalar_one_or_none()

    if current is not None:
        return current

    # Fallback: latest generated_at (for pre-migration rows)
    return db.execute(
        select(InvestmentMemorandumDraft)
        .where(
            InvestmentMemorandumDraft.fund_id == fund_id,
            InvestmentMemorandumDraft.deal_id == deal_id,
        )
        .order_by(InvestmentMemorandumDraft.generated_at.desc())
        .limit(1),
    ).scalar_one_or_none()


def run_portfolio_review(
    db: Session,
    *,
    fund_id: uuid.UUID,
    investment_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> dict[str, Any]:
    """Run a periodic AI review of an active investment."""
    now = _now_utc()
    investment = db.execute(
        select(ActiveInvestment).where(
            ActiveInvestment.id == investment_id,
            ActiveInvestment.fund_id == fund_id,
        ),
    ).scalar_one_or_none()
    if investment is None:
        return {"error": "Investment not found"}

    corpus = _gather_investment_texts(db, fund_id=fund_id, investment=investment)
    if not corpus.strip():
        return {"error": "No readable documents found for this investment"}

    system_prompt = prompt_registry.render("portfolio_review.j2")
    review = _call_openai(system_prompt, corpus)

    report = PeriodicReviewReport(
        fund_id=fund_id,
        investment_id=investment_id,
        review_type="PERIODIC",
        overall_rating=review.get("overallRating", "AMBER"),
        executive_summary=review.get("executiveSummary", "Review pending."),
        performance_assessment=review.get("performanceAssessment", ""),
        covenant_compliance=review.get("covenantCompliance", ""),
        material_changes=review.get("materialChanges", []),
        risk_evolution=review.get("riskEvolution", ""),
        liquidity_assessment=review.get("liquidityAssessment", ""),
        valuation_view=review.get("valuationView", ""),
        recommended_actions=review.get("recommendedActions", []),
        reviewed_at=now,
        model_version=_MODEL,
        created_by=actor_id,
        updated_by=actor_id,
    )
    with db.begin_nested():
        db.add(report)

    # No db.commit() — caller manages transaction boundary.

    return {
        "investmentId": str(investment_id),
        "investmentName": investment.investment_name,
        "overallRating": report.overall_rating,
        "asOf": now.isoformat(),
    }


def run_all_portfolio_reviews(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor_id: str = "ai-engine",
) -> dict[str, Any]:
    """Run periodic review for every active investment.

    Each investment gets its own DB session for isolation.
    """
    investments = list(
        db.execute(select(ActiveInvestment).where(ActiveInvestment.fund_id == fund_id))
        .scalars()
        .all(),
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from app.core.db.engine import async_session_factory

    # Despite the name, async_session_factory produces sync-compatible sessions
    # when used as a context manager (with ... as session). Each thread gets
    # its own isolated session for transaction safety.
    SessionLocal = async_session_factory
    results = []

    # Extract ORM scalars before spawning threads — ORM objects are session-bound
    investment_ids = [
        (inv.id, inv.fund_id) for inv in investments
    ]

    def _review_investment(inv_id: uuid.UUID, _fund_id: uuid.UUID) -> dict[str, Any]:
        try:
            with SessionLocal() as session:
                result = run_portfolio_review(
                    session,
                    fund_id=_fund_id,
                    investment_id=inv_id,
                    actor_id=actor_id,
                )
                if "error" not in result:
                    session.commit()
                return result
        except Exception:
            logger.warning(
                "portfolio_review.failed",
                investment_id=str(inv_id),
                exc_info=True,
            )
            return {"investmentId": str(inv_id), "error": "Review failed"}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_review_investment, inv_id, f_id): inv_id
            for inv_id, f_id in investment_ids
        }
        for future in as_completed(futures):
            results.append(future.result())

    return {
        "asOf": _now_utc().isoformat(),
        "totalInvestments": len(investments),
        "reviewed": len([r for r in results if "error" not in r]),
        "errors": len([r for r in results if "error" in r]),
        "results": results,
    }


__all__ = [
    "get_current_im_draft",
    "run_portfolio_review",
    "run_all_portfolio_reviews",
]
