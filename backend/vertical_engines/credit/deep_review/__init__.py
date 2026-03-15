"""Deep Review V4 — IC-Grade Investment Memorandum Pipeline.

Six-layer DAG: models → helpers → domain modules → persist → portfolio → service.
This is distinct from the standard two-tier edgar pattern because deep_review
is the only engine that persists other engines' results.

Public API:
    run_deal_deep_review_v4()           — sync single-deal deep review
    async_run_deal_deep_review_v4()     — async single-deal deep review
    run_all_deals_deep_review_v4()      — sync batch deep review
    async_run_all_deals_deep_review_v4() — async batch deep review
    run_portfolio_review()              — single investment periodic review
    run_all_portfolio_reviews()         — batch portfolio reviews
    get_current_im_draft()              — query current IM draft
    compute_underwriting_confidence()   — underwriting reliability score
    apply_tone_normalizer_adjustment()  — post-tone confidence adjustment

Error contract: never-raises (orchestration engine). Functions return result
dicts with status/warnings on failure. exc_info=True in structlog.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_engine.prompts import prompt_registry

# Register package-local templates so prompt_registry.render() can
# resolve deep_review .j2 files by filename.
prompt_registry.add_search_path(Path(__file__).parent / "templates")

# Eagerly import leaf-node symbols only (no transitive deps)
from vertical_engines.credit.deep_review.confidence import (
    apply_tone_normalizer_adjustment,
    compute_underwriting_confidence,
)

if TYPE_CHECKING:
    from vertical_engines.credit.deep_review.portfolio import (
        get_current_im_draft as get_current_im_draft,
    )
    from vertical_engines.credit.deep_review.portfolio import (
        run_all_portfolio_reviews as run_all_portfolio_reviews,
    )
    from vertical_engines.credit.deep_review.portfolio import (
        run_portfolio_review as run_portfolio_review,
    )
    from vertical_engines.credit.deep_review.service import (
        async_run_all_deals_deep_review_v4 as async_run_all_deals_deep_review_v4,
    )
    from vertical_engines.credit.deep_review.service import (
        async_run_deal_deep_review_v4 as async_run_deal_deep_review_v4,
    )
    from vertical_engines.credit.deep_review.service import (
        run_all_deals_deep_review_v4 as run_all_deals_deep_review_v4,
    )
    from vertical_engines.credit.deep_review.service import (
        run_deal_deep_review_v4 as run_deal_deep_review_v4,
    )

__all__ = [
    # service (lazy)
    "run_deal_deep_review_v4",
    "async_run_deal_deep_review_v4",
    "run_all_deals_deep_review_v4",
    "async_run_all_deals_deep_review_v4",
    # portfolio (lazy)
    "run_portfolio_review",
    "run_all_portfolio_reviews",
    "get_current_im_draft",
    # confidence (eager)
    "compute_underwriting_confidence",
    "apply_tone_normalizer_adjustment",
]


def __dir__() -> list[str]:
    return __all__


def __getattr__(name: str) -> Any:
    if name in (
        "run_deal_deep_review_v4",
        "async_run_deal_deep_review_v4",
        "run_all_deals_deep_review_v4",
        "async_run_all_deals_deep_review_v4",
    ):
        from vertical_engines.credit.deep_review.service import (
            async_run_all_deals_deep_review_v4,
            async_run_deal_deep_review_v4,
            run_all_deals_deep_review_v4,
            run_deal_deep_review_v4,
        )
        return {
            "run_deal_deep_review_v4": run_deal_deep_review_v4,
            "async_run_deal_deep_review_v4": async_run_deal_deep_review_v4,
            "run_all_deals_deep_review_v4": run_all_deals_deep_review_v4,
            "async_run_all_deals_deep_review_v4": async_run_all_deals_deep_review_v4,
        }[name]
    if name in ("run_portfolio_review", "run_all_portfolio_reviews", "get_current_im_draft"):
        from vertical_engines.credit.deep_review.portfolio import (
            get_current_im_draft,
            run_all_portfolio_reviews,
            run_portfolio_review,
        )
        return {
            "run_portfolio_review": run_portfolio_review,
            "run_all_portfolio_reviews": run_all_portfolio_reviews,
            "get_current_im_draft": get_current_im_draft,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
