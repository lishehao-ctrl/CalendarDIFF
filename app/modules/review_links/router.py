from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_public_api_key
from app.modules.review_links.alerts_router import router as alerts_router
from app.modules.review_links.candidates_router import router as candidates_router
from app.modules.review_links.links_router import router as links_router
from app.modules.review_links.summary_router import router as summary_router

router = APIRouter(
    tags=["review-items"],
    dependencies=[Depends(require_public_api_key)],
)

router.include_router(summary_router)
router.include_router(candidates_router)
router.include_router(links_router)
router.include_router(alerts_router)

__all__ = ["router"]
