from __future__ import annotations

from fastapi.routing import APIRoute

from app.core.security import require_public_api_key


def test_oauth_callback_route_does_not_require_api_key(input_client) -> None:
    response = input_client.get("/oauth/callbacks/gmail")
    assert response.status_code == 200
    assert response.json() == {
        "source_id": None,
        "provider": "gmail",
        "request_id": None,
        "status": "error",
        "sync_request_status": None,
        "message": "oauth callback missing code/state",
    }

    callback_route = next(
        route
        for route in input_client.app.routes
        if isinstance(route, APIRoute) and route.path == "/oauth/callbacks/{provider}" and "GET" in route.methods
    )
    dependency_calls = [dependency.call for dependency in callback_route.dependant.dependencies]
    assert require_public_api_key not in dependency_calls
