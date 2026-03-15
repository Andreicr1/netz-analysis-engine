"""AI module routes — assembled lazily to avoid ai_engine import chain at startup.

The ai_engine has deep dependencies on Azure services and modules that
are stub-only in Sprint 2b. By deferring router assembly to first access,
the FastAPI app can import and boot without ai_engine being fully wired.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/ai", tags=["ai"])
_assembled = False


def _assemble() -> None:
    global _assembled
    if _assembled:
        return
    _assembled = True

    try:
        from app.domains.credit.modules.ai.copilot import router as copilot_router
        router.include_router(copilot_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.documents import router as documents_router
        router.include_router(documents_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.compliance import router as compliance_router
        router.include_router(compliance_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.pipeline_deals import router as pipeline_deals_router
        router.include_router(pipeline_deals_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.extraction import router as extraction_router
        router.include_router(extraction_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.portfolio import router as portfolio_router
        router.include_router(portfolio_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.deep_review import router as deep_review_router
        router.include_router(deep_review_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.memo_chapters import router as memo_chapters_router
        router.include_router(memo_chapters_router)
    except Exception:
        pass

    try:
        from app.domains.credit.modules.ai.artifacts import router as artifacts_router
        router.include_router(artifacts_router)
    except Exception:
        pass


# Assemble on import — but failures are silenced (Sprint 3 will wire everything)
_assemble()
