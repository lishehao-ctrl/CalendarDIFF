from __future__ import annotations

from app.core.config import get_settings
from app.core.oauth_config import build_oauth_runtime_config, log_input_oauth_startup


def test_public_oauth_startup_logs_redirect_and_callback_routes(configure_test_environment: None, monkeypatch) -> None:
    del configure_test_environment
    get_settings.cache_clear()
    from services.public_api.main import app

    messages: list[str] = []

    def _capture(message: str, *args) -> None:
        messages.append(message % args if args else message)

    monkeypatch.setattr("app.core.oauth_config.logger.info", _capture)
    log_input_oauth_startup(app)

    runtime = build_oauth_runtime_config()

    assert any(runtime.gmail_redirect_uri in msg for msg in messages)
    assert any(f"oauth runtime registered_callback_routes={runtime.callback_route_path}" in msg for msg in messages)
    get_settings.cache_clear()
