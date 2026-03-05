from __future__ import annotations

from fastapi.routing import APIRoute

from app.core.config import get_settings
from app.core.oauth_config import build_oauth_runtime_config


def test_input_oauth_routes_follow_runtime_config(configure_test_environment: None) -> None:
    del configure_test_environment
    get_settings.cache_clear()
    from services.input_api.main import app

    runtime = build_oauth_runtime_config()
    route_map = {route.path: route for route in app.routes if isinstance(route, APIRoute)}

    assert runtime.oauth_session_route_path in route_map
    assert runtime.callback_route_path in route_map
    assert route_map[runtime.callback_route_path].include_in_schema is False
    get_settings.cache_clear()
