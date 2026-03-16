from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping
from urllib.parse import urlencode, urljoin, urlparse

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OAuthRuntimeConfig:
    public_base_url: str
    route_prefix: str
    oauth_session_route_path: str
    callback_route_path: str
    callback_requires_api_key: bool
    state_ttl_minutes: int
    token_encryption_key_source: str
    gmail_scope: str
    gmail_access_type: str
    gmail_prompt: str
    gmail_include_granted_scopes: bool

    @property
    def gmail_redirect_uri(self) -> str:
        return f"{self.public_base_url}{self.callback_route_for_provider('gmail')}"

    def callback_route_for_provider(self, provider: str) -> str:
        normalized_provider = provider.strip().lower()
        if not normalized_provider:
            raise RuntimeError("OAuth provider must not be empty")
        if "{provider}" not in self.callback_route_path:
            raise RuntimeError("OAuth callback route template must include '{provider}'")
        return self.callback_route_path.replace("{provider}", normalized_provider)


def build_oauth_runtime_config(*, settings: Settings | None = None) -> OAuthRuntimeConfig:
    current_settings = settings or get_settings()

    route_prefix = _normalize_route_prefix(current_settings.oauth_route_prefix)
    oauth_session_route_path = _join_route_path(route_prefix, current_settings.oauth_session_route_template)
    callback_route_path = _join_route_path(route_prefix, current_settings.oauth_callback_route_template)
    callback_requires_api_key = bool(current_settings.oauth_callback_require_api_key)

    if callback_requires_api_key:
        raise RuntimeError("OAuth callback route cannot require API key")

    if "{source_id}" not in oauth_session_route_path:
        raise RuntimeError("OAuth session route template must include '{source_id}'")

    token_source = (
        "OAUTH_TOKEN_ENCRYPTION_KEY"
        if _is_non_empty(current_settings.oauth_token_encryption_key)
        else "APP_SECRET_KEY"
    )

    return OAuthRuntimeConfig(
        public_base_url=_resolve_oauth_public_base_url(current_settings),
        route_prefix=route_prefix,
        oauth_session_route_path=oauth_session_route_path,
        callback_route_path=callback_route_path,
        callback_requires_api_key=callback_requires_api_key,
        state_ttl_minutes=max(1, int(current_settings.oauth_state_ttl_minutes)),
        token_encryption_key_source=token_source,
        gmail_scope=current_settings.gmail_oauth_scope.strip(),
        gmail_access_type=current_settings.gmail_oauth_access_type.strip(),
        gmail_prompt=current_settings.gmail_oauth_prompt.strip(),
        gmail_include_granted_scopes=bool(current_settings.gmail_oauth_include_granted_scopes),
    )


def resolve_oauth_token_encryption_key(*, settings: Settings | None = None) -> tuple[str, str]:
    current_settings = settings or get_settings()
    override = current_settings.oauth_token_encryption_key
    if isinstance(override, str) and override.strip():
        return override.strip(), "OAUTH_TOKEN_ENCRYPTION_KEY"
    return current_settings.app_secret_key, "APP_SECRET_KEY"


def resolve_frontend_app_base_url(*, settings: Settings | None = None) -> str:
    current_settings = settings or get_settings()
    if _is_non_empty(current_settings.frontend_app_base_url):
        assert isinstance(current_settings.frontend_app_base_url, str)
        return _normalize_public_base_url(current_settings.frontend_app_base_url)

    for item in current_settings.public_web_origins.split(","):
        if _is_non_empty(item):
            return _normalize_public_base_url(item)

    raise RuntimeError("Frontend app base URL is not configured")


def build_frontend_sources_return_url(
    *,
    oauth_provider: str,
    oauth_status: str,
    source_id: int | None = None,
    request_id: str | None = None,
    message: str | None = None,
    settings: Settings | None = None,
) -> str:
    return build_frontend_oauth_return_url(
        oauth_provider=oauth_provider,
        oauth_status=oauth_status,
        source_id=source_id,
        request_id=request_id,
        message=message,
        destination="sources",
        settings=settings,
    )


def build_frontend_oauth_return_url(
    *,
    oauth_provider: str,
    oauth_status: str,
    source_id: int | None = None,
    request_id: str | None = None,
    message: str | None = None,
    destination: str = "sources",
    settings: Settings | None = None,
) -> str:
    base_url = resolve_frontend_app_base_url(settings=settings)
    normalized_destination = destination.strip().lower() if isinstance(destination, str) else "sources"
    if normalized_destination not in {"sources", "onboarding"}:
        raise RuntimeError("OAuth frontend destination must be either 'sources' or 'onboarding'")
    destination_url = urljoin(f"{base_url}/", normalized_destination)
    query: dict[str, str] = {
        "oauth_provider": oauth_provider,
        "oauth_status": oauth_status,
    }
    if source_id is not None:
        query["source_id"] = str(source_id)
    if request_id:
        query["request_id"] = request_id
    if message:
        query["message"] = message
    return f"{destination_url}?{urlencode(query)}"


def log_input_oauth_startup(app: FastAPI) -> None:
    runtime = build_oauth_runtime_config()
    callback_routes = list(_iter_callback_routes(app=app, callback_route_path=runtime.callback_route_path))
    if not callback_routes:
        raise RuntimeError("OAuth callback route is not registered in input service app")
    _assert_callback_routes_do_not_require_public_api_key(callback_routes)

    parsed_redirect = urlparse(runtime.gmail_redirect_uri)
    logger.info(
        (
            "oauth runtime redirect_uri=%s://%s%s route_prefix=%s callback_route=%s "
            "token_key_source=%s callback_requires_api_key=%s scope=%s access_type=%s prompt=%s include_granted_scopes=%s"
        ),
        parsed_redirect.scheme,
        parsed_redirect.netloc,
        parsed_redirect.path,
        runtime.route_prefix or "/",
        runtime.callback_route_path,
        runtime.token_encryption_key_source,
        runtime.callback_requires_api_key,
        runtime.gmail_scope,
        runtime.gmail_access_type,
        runtime.gmail_prompt,
        runtime.gmail_include_granted_scopes,
    )
    logger.info(
        "oauth runtime registered_callback_routes=%s",
        ",".join(sorted(route.path for route in callback_routes)),
    )


def _iter_callback_routes(*, app: FastAPI, callback_route_path: str) -> Iterable[APIRoute]:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == callback_route_path:
            yield route


def _assert_callback_routes_do_not_require_public_api_key(routes: Iterable[APIRoute]) -> None:
    for route in routes:
        for dependency in route.dependant.dependencies:
            call = getattr(dependency, "call", None)
            if (
                getattr(call, "__module__", "") == "app.core.security"
                and getattr(call, "__name__", "") == "require_public_api_key"
            ):
                raise RuntimeError("OAuth callback route must not require API key")


def _resolve_oauth_public_base_url(settings: Settings) -> str:
    candidates = (
        settings.oauth_public_base_url,
        settings.public_api_base_url,
        settings.app_base_url,
        "http://localhost:8200",
    )
    for candidate in candidates:
        if _is_non_empty(candidate):
            assert isinstance(candidate, str)
            return _normalize_public_base_url(candidate)
    raise RuntimeError("OAuth public base URL is not configured")


def _normalize_public_base_url(raw_value: str) -> str:
    normalized = raw_value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("OAuth public base URL must include scheme and host")
    normalized_path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{normalized_path}"


def _normalize_route_prefix(raw_value: str) -> str:
    stripped = raw_value.strip()
    if not stripped or stripped == "/":
        return ""
    if not stripped.startswith("/"):
        stripped = f"/{stripped}"
    if stripped.endswith("/"):
        stripped = stripped.rstrip("/")
    return stripped


def _join_route_path(prefix: str, route_template: str) -> str:
    stripped_template = route_template.strip()
    if not stripped_template.startswith("/"):
        raise RuntimeError("OAuth route template must start with '/'")
    if prefix == "":
        return stripped_template
    if stripped_template == "/":
        return prefix
    return f"{prefix}{stripped_template}"


def _is_non_empty(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "OAuthRuntimeConfig",
    "build_frontend_oauth_return_url",
    "build_frontend_sources_return_url",
    "build_oauth_runtime_config",
    "log_input_oauth_startup",
    "resolve_frontend_app_base_url",
    "resolve_oauth_token_encryption_key",
]
