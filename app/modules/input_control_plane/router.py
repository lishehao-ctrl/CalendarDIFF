from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require_public_api_key
from app.modules.input_control_plane.oauth_router import public_router
from app.modules.input_control_plane.oauth_router import router as oauth_router
from app.modules.input_control_plane.sources_router import router as sources_router
from app.modules.input_control_plane.sync_requests_router import router as sync_requests_router
from app.modules.input_control_plane.webhooks_router import router as webhooks_router

router = APIRouter(tags=["input-control-plane"], dependencies=[Depends(require_public_api_key)])

router.include_router(sources_router)
router.include_router(sync_requests_router)
router.include_router(oauth_router)
router.include_router(webhooks_router)

__all__ = ["public_router", "router"]
