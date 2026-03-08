from __future__ import annotations

from app.core.oauth_config import log_input_oauth_startup
from app.modules.auth.router import router as auth_router
from app.modules.health.router import router as health_router
from app.modules.input_control_plane.router import public_router as input_public_router
from app.modules.input_control_plane.router import router as input_control_plane_router
from app.modules.onboarding.router import router as onboarding_router
from app.modules.review_changes.router import router as review_changes_router
from app.modules.review_links.router import router as review_links_router
from app.modules.users.router import router as users_router
from app.service_app import create_service_app

app = create_service_app(
    title="CalendarDIFF Public Service",
    version="0.1.0",
    public_api=True,
    routers=[
        health_router,
        auth_router,
        users_router,
        onboarding_router,
        input_public_router,
        input_control_plane_router,
        review_changes_router,
        review_links_router,
    ],
    startup_hooks=[log_input_oauth_startup],
)
