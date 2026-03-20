from __future__ import annotations

from app.modules.auth.bootstrap import bootstrap_env_admin_user
from app.core.oauth_config import log_input_oauth_startup
from app.modules.auth.router import router as auth_router
from app.modules.families.router import router as families_router
from app.modules.health.router import router as health_router
from app.modules.sources.router import public_router as sources_public_router
from app.modules.sources.router import router as sources_router
from app.modules.manual.router import router as manual_router
from app.modules.onboarding.router import router as onboarding_router
from app.modules.settings.router import router as settings_router
from app.modules.changes.router import router as changes_router
from app.modules.runtime.monolith_workers import (
    run_ingest_worker,
    run_llm_worker,
    run_notification_worker,
    run_review_apply_worker,
)
from app.service_app import create_service_app

app = create_service_app(
    title="CalendarDIFF API",
    version="0.1.0",
    public_api=True,
    routers=[
        health_router,
        auth_router,
        settings_router,
        manual_router,
        onboarding_router,
        sources_public_router,
        sources_router,
        families_router,
        changes_router,
    ],
    worker_tasks=[
        run_ingest_worker,
        run_llm_worker,
        run_review_apply_worker,
        run_notification_worker,
    ],
    startup_hooks=[log_input_oauth_startup, bootstrap_env_admin_user],
)
