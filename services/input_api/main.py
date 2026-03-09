from __future__ import annotations

from app.modules.health.router import router as health_router
from app.modules.input_control_plane.metrics_router import router as input_metrics_router
from app.service_app import create_service_app

app = create_service_app(
    title="CalendarDIFF Input Service",
    version="0.1.0",
    public_api=False,
    routers=[
        health_router,
        input_metrics_router,
    ],
)
