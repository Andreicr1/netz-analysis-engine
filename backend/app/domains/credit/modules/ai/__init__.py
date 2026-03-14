"""AI module routes — split into domain sub-routers."""
from fastapi import APIRouter

from app.domains.credit.modules.ai.routes.artifacts import router as artifacts_router
from app.domains.credit.modules.ai.routes.compliance import router as compliance_router
from app.domains.credit.modules.ai.routes.copilot import router as copilot_router
from app.domains.credit.modules.ai.routes.deep_review import router as deep_review_router
from app.domains.credit.modules.ai.routes.documents import router as documents_router
from app.domains.credit.modules.ai.routes.extraction import router as extraction_router
from app.domains.credit.modules.ai.routes.memo_chapters import router as memo_chapters_router
from app.domains.credit.modules.ai.routes.pipeline_deals import router as pipeline_deals_router
from app.domains.credit.modules.ai.routes.portfolio import router as portfolio_router

router = APIRouter(prefix="/ai", tags=["ai"])
router.include_router(copilot_router)
router.include_router(documents_router)
router.include_router(compliance_router)
router.include_router(pipeline_deals_router)
router.include_router(extraction_router)
router.include_router(portfolio_router)
router.include_router(deep_review_router)
router.include_router(memo_chapters_router)
router.include_router(artifacts_router)
