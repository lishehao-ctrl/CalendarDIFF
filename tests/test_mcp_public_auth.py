from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import anyio
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.server import RequestContext

from app.db.models.shared import User
from app.modules.settings.mcp_tokens_service import create_mcp_access_token
from services.mcp_server.main import CalendarDIFFTokenVerifier, get_workspace_context_impl, mcp


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        notify_email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@dataclass
class _FakeRequest:
    user: object


def test_calendar_diff_token_verifier_accepts_valid_token(db_session) -> None:
    user = _create_user(db_session, email="mcp-public-auth@example.com")
    _row, plaintext = create_mcp_access_token(db_session, user=user, label="QClaw", expires_in_days=30)

    access = anyio.run(CalendarDIFFTokenVerifier().verify_token, plaintext)
    assert access is not None
    assert access.client_id == f"user:{user.id}"
    assert "calendardiff" in access.scopes


def test_mcp_impl_prefers_authenticated_context_user_over_notify_email(db_session) -> None:
    owner = _create_user(db_session, email="owner@example.com")
    other = _create_user(db_session, email="other@example.com")
    _row, plaintext = create_mcp_access_token(db_session, user=owner, label="QClaw", expires_in_days=30)
    access = anyio.run(CalendarDIFFTokenVerifier().verify_token, plaintext)
    assert access is not None

    request = _FakeRequest(user=AuthenticatedUser(access))
    request_context = RequestContext(
        request_id="req-1",
        meta=None,
        session=None,
        lifespan_context=None,
        request=request,
    )
    ctx = Context(request_context=request_context, fastmcp=mcp)

    payload = get_workspace_context_impl(notify_email=other.notify_email, ctx=ctx)
    assert payload["summary"]["changes_pending"] == 0
    assert payload["summary"]["sources"]["active_count"] == 0
