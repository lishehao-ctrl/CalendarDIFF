from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.agents import McpAccessToken
from app.db.models.shared import User
from app.db.schema_guard import ensure_schema_ready
from app.db.session import get_engine, get_session_factory
from app.modules.agents.approval_service import (
    ApprovalTicketError,
    cancel_approval_ticket,
    confirm_approval_ticket,
    create_approval_ticket,
    get_approval_ticket,
)
from app.modules.agents.proposal_service import (
    AgentProposalInvalidStateError,
    create_change_decision_proposal,
    create_family_relink_preview_proposal,
    create_source_recovery_proposal,
    get_agent_proposal,
)
from app.modules.agents.schemas import (
    AgentChangeContextResponse,
    AgentFamilyContextResponse,
    AgentProposalResponse,
    AgentSourceContextResponse,
    AgentWorkspaceContextResponse,
    ApprovalTicketResponse,
    serialize_approval_ticket,
    serialize_agent_proposal,
)
from app.modules.agents.service import (
    AgentContextNotFoundError,
    build_change_agent_context,
    build_family_agent_context,
    build_source_agent_context,
    build_workspace_agent_context,
)
from app.modules.changes.change_listing_service import list_changes
from app.modules.changes.schemas import ChangeItemResponse
from app.modules.sources.read_service import build_source_read_payload
from app.modules.sources.schemas import InputSourceResponse
from app.modules.sources.sources_service import list_input_sources
from app.modules.settings.mcp_tokens_service import verify_mcp_access_token

from pydantic import BaseModel, Field


INSTRUCTIONS = """
CalendarDIFF MCP server for operator-grade academic deadline review.

Use read-only tools first:
- get_workspace_context
- list_pending_changes
- list_sources
- get_change_context
- get_source_context

Only create proposals or approval tickets when the task clearly requires action.
Do not assume that every proposal is executable.
Use approval tickets for execution; do not skip directly to business writes.
"""


class PendingChangesResult(BaseModel):
    items: list[ChangeItemResponse] = Field(default_factory=list)


class SourcesListResult(BaseModel):
    items: list[InputSourceResponse] = Field(default_factory=list)


class MCPUserResolutionError(RuntimeError):
    pass


def _mcp_mode() -> str:
    return os.getenv("CALENDARDIFF_MCP_MODE", "local").strip().lower() or "local"


def _public_mode_enabled() -> bool:
    return _mcp_mode() == "public"


def _server_host() -> str:
    return os.getenv("CALENDARDIFF_MCP_HOST", "0.0.0.0" if _public_mode_enabled() else "127.0.0.1").strip() or (
        "0.0.0.0" if _public_mode_enabled() else "127.0.0.1"
    )


def _server_port() -> int:
    raw = os.getenv("CALENDARDIFF_MCP_PORT", "8766" if _public_mode_enabled() else "8000").strip()
    try:
        return int(raw)
    except Exception:
        return 8766 if _public_mode_enabled() else 8000


def _public_base_url() -> str:
    return os.getenv("CALENDARDIFF_MCP_PUBLIC_BASE_URL", "https://cal.shehao.app").strip().rstrip("/")


def _public_mcp_url() -> str:
    return os.getenv("CALENDARDIFF_MCP_PUBLIC_URL", f"{_public_base_url()}/mcp").strip().rstrip("/")


class CalendarDIFFTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        with _db_session() as db:
            verified = verify_mcp_access_token(db, plaintext_token=token)
            if verified is None:
                return None
            token_row, user = verified
            expires_at = int(token_row.expires_at.timestamp()) if token_row.expires_at is not None else None
            return AccessToken(
                token=token,
                client_id=f"user:{user.id}",
                scopes=list(token_row.scopes_json or ["calendardiff"]),
                expires_at=expires_at,
                resource=None,
            )


def _build_mcp_server() -> FastMCP:
    kwargs: dict[str, Any] = {
        "name": "CalendarDIFF MCP",
        "instructions": INSTRUCTIONS.strip(),
        "dependencies": ["sqlalchemy", "psycopg[binary]"],
        "host": _server_host(),
        "port": _server_port(),
    }
    if _public_mode_enabled():
        kwargs["token_verifier"] = CalendarDIFFTokenVerifier()
        kwargs["auth"] = AuthSettings(
            issuer_url=_public_base_url(),
            resource_server_url=_public_mcp_url(),
            required_scopes=["calendardiff"],
        )
    return FastMCP(**kwargs)


mcp = _build_mcp_server()


def _default_notify_email() -> str | None:
    value = os.getenv("CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL", "").strip()
    return value or None


def _resolved_notify_email(notify_email: str | None) -> str:
    resolved = (notify_email or _default_notify_email() or "").strip()
    if resolved:
        return resolved
    raise MCPUserResolutionError(
        "Missing user identity. Pass notify_email explicitly or set CALENDARDIFF_MCP_DEFAULT_NOTIFY_EMAIL."
    )


@contextmanager
def _db_session() -> Any:
    settings = get_settings()
    if settings.schema_guard_enabled:
        ensure_schema_ready(get_engine())
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def _user_id_from_context(ctx: Context | None) -> int | None:
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request
    except Exception:
        return None
    if request is None:
        return None
    auth_user = getattr(request, "user", None)
    access_token = getattr(auth_user, "access_token", None)
    client_id = getattr(access_token, "client_id", None)
    if not isinstance(client_id, str) or not client_id.startswith("user:"):
        return None
    try:
        return int(client_id.split(":", 1)[1])
    except Exception:
        return None


def _resolve_user(db: Session, *, notify_email: str | None, ctx: Context | None) -> User:
    user_id = _user_id_from_context(ctx)
    if user_id is not None:
        user = db.scalar(select(User).where(User.id == user_id).limit(1))
        if user is None:
            raise MCPUserResolutionError(f"No CalendarDIFF user found for MCP token user id '{user_id}'.")
        if user.onboarding_completed_at is None:
            raise MCPUserResolutionError(f"User id '{user_id}' has not completed onboarding yet.")
        return user
    resolved = _resolved_notify_email(notify_email)
    user = db.scalar(
        select(User)
        .where(or_(User.notify_email == resolved, User.email == resolved))
        .limit(1)
    )
    if user is None:
        raise MCPUserResolutionError(f"No CalendarDIFF user found for '{resolved}'.")
    if user.onboarding_completed_at is None:
        raise MCPUserResolutionError(f"User '{resolved}' has not completed onboarding yet.")
    return user


def _normalize_error(exc: Exception) -> RuntimeError:
    if isinstance(exc, (MCPUserResolutionError,)):
        return RuntimeError(str(exc))
    if isinstance(exc, AgentContextNotFoundError):
        return RuntimeError(exc.detail["message"])
    if isinstance(exc, AgentProposalInvalidStateError):
        return RuntimeError(exc.detail["message"])
    if isinstance(exc, ApprovalTicketError):
        return RuntimeError(exc.detail["message"])
    return RuntimeError(str(exc))


def _run_with_user(notify_email: str | None, fn, *, ctx: Context | None = None):
    try:
        with _db_session() as db:
            user = _resolve_user(db, notify_email=notify_email, ctx=ctx)
            return fn(db, user)
    except Exception as exc:  # pragma: no cover - exercised via tools/resources
        raise _normalize_error(exc) from exc


def get_workspace_context_impl(*, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(notify_email, lambda db, user: build_workspace_agent_context(db=db, user_id=user.id), ctx=ctx)


def list_pending_changes_impl(
    *,
    notify_email: str | None = None,
    limit: int = 10,
    review_bucket: str = "all",
    intake_phase: str = "all",
    ctx: Context | None = None,
) -> list[dict]:
    safe_limit = max(1, min(limit, 50))
    return _run_with_user(
        notify_email,
        lambda db, user: list_changes(
            db,
            user_id=user.id,
            review_status="pending",
            review_bucket=review_bucket,
            intake_phase=intake_phase,
            source_id=None,
            limit=safe_limit,
            offset=0,
        ),
        ctx=ctx,
    )


def list_sources_impl(*, notify_email: str | None = None, status: str = "active", ctx: Context | None = None) -> list[dict]:
    return _run_with_user(
        notify_email,
        lambda db, user: [build_source_read_payload(db, source=row) for row in list_input_sources(db, user_id=user.id, status=status)],
        ctx=ctx,
    )


def get_change_context_impl(*, change_id: int, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: build_change_agent_context(db=db, user_id=user.id, change_id=change_id),
        ctx=ctx,
    )


def get_source_context_impl(*, source_id: int, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: build_source_agent_context(db=db, user_id=user.id, source_id=source_id),
        ctx=ctx,
    )


def get_family_context_impl(*, family_id: int, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: build_family_agent_context(db=db, user_id=user.id, family_id=family_id),
        ctx=ctx,
    )


def create_change_decision_proposal_impl(*, change_id: int, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: serialize_agent_proposal(create_change_decision_proposal(db=db, user_id=user.id, change_id=change_id)),
        ctx=ctx,
    )


def create_source_recovery_proposal_impl(*, source_id: int, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: serialize_agent_proposal(create_source_recovery_proposal(db=db, user_id=user.id, source_id=source_id)),
        ctx=ctx,
    )


def create_family_relink_preview_proposal_impl(
    *,
    raw_type_id: int,
    family_id: int,
    notify_email: str | None = None,
    ctx: Context | None = None,
) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: serialize_agent_proposal(
            create_family_relink_preview_proposal(db=db, user_id=user.id, raw_type_id=raw_type_id, family_id=family_id)
        ),
        ctx=ctx,
    )


def get_proposal_impl(*, proposal_id: int, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    def _load(db: Session, user: User) -> dict:
        proposal = get_agent_proposal(db=db, user_id=user.id, proposal_id=proposal_id)
        if proposal is None:
            raise RuntimeError("Agent proposal not found.")
        return serialize_agent_proposal(proposal)

    return _run_with_user(notify_email, _load, ctx=ctx)


def create_approval_ticket_impl(*, proposal_id: int, notify_email: str | None = None, channel: str = "mcp", ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: serialize_approval_ticket(create_approval_ticket(db=db, user_id=user.id, proposal_id=proposal_id, channel=channel)),
        ctx=ctx,
    )


def get_approval_ticket_impl(*, ticket_id: str, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    def _load(db: Session, user: User) -> dict:
        ticket = get_approval_ticket(db=db, user_id=user.id, ticket_id=ticket_id)
        if ticket is None:
            raise RuntimeError("Approval ticket not found.")
        return serialize_approval_ticket(ticket)

    return _run_with_user(notify_email, _load, ctx=ctx)


def confirm_approval_ticket_impl(*, ticket_id: str, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: serialize_approval_ticket(confirm_approval_ticket(db=db, user_id=user.id, ticket_id=ticket_id)[0]),
        ctx=ctx,
    )


def cancel_approval_ticket_impl(*, ticket_id: str, notify_email: str | None = None, ctx: Context | None = None) -> dict:
    return _run_with_user(
        notify_email,
        lambda db, user: serialize_approval_ticket(cancel_approval_ticket(db=db, user_id=user.id, ticket_id=ticket_id)[0]),
        ctx=ctx,
    )


@mcp.tool(name="get_workspace_context", description="Get the aggregated CalendarDIFF workspace context for a user.", structured_output=True)
def get_workspace_context_tool(notify_email: str | None = None, ctx: Context | None = None) -> AgentWorkspaceContextResponse:
    return AgentWorkspaceContextResponse.model_validate(get_workspace_context_impl(notify_email=notify_email, ctx=ctx))


@mcp.tool(name="list_pending_changes", description="List pending changes for a user.", structured_output=True)
def list_pending_changes_tool(
    notify_email: str | None = None,
    limit: int = 10,
    review_bucket: str = "all",
    intake_phase: str = "all",
    ctx: Context | None = None,
) -> PendingChangesResult:
    return PendingChangesResult.model_validate(
        {
            "items": list_pending_changes_impl(
                notify_email=notify_email,
                limit=limit,
                review_bucket=review_bucket,
                intake_phase=intake_phase,
                ctx=ctx,
            )
        }
    )


@mcp.tool(name="list_sources", description="List sources with current read-model projections for a user.", structured_output=True)
def list_sources_tool(notify_email: str | None = None, status: str = "active", ctx: Context | None = None) -> SourcesListResult:
    return SourcesListResult.model_validate({"items": list_sources_impl(notify_email=notify_email, status=status, ctx=ctx)})


@mcp.tool(name="get_change_context", description="Get agent context for a specific change.", structured_output=True)
def get_change_context_tool(change_id: int, notify_email: str | None = None, ctx: Context | None = None) -> AgentChangeContextResponse:
    return AgentChangeContextResponse.model_validate(get_change_context_impl(change_id=change_id, notify_email=notify_email, ctx=ctx))


@mcp.tool(name="get_source_context", description="Get agent context for a specific source.", structured_output=True)
def get_source_context_tool(source_id: int, notify_email: str | None = None, ctx: Context | None = None) -> AgentSourceContextResponse:
    return AgentSourceContextResponse.model_validate(get_source_context_impl(source_id=source_id, notify_email=notify_email, ctx=ctx))


@mcp.tool(name="get_family_context", description="Get agent context for a specific family.", structured_output=True)
def get_family_context_tool(family_id: int, notify_email: str | None = None, ctx: Context | None = None) -> AgentFamilyContextResponse:
    return AgentFamilyContextResponse.model_validate(get_family_context_impl(family_id=family_id, notify_email=notify_email, ctx=ctx))


@mcp.tool(name="create_change_decision_proposal", description="Create a persisted change-decision proposal.", structured_output=True)
def create_change_decision_proposal_tool(change_id: int, notify_email: str | None = None, ctx: Context | None = None) -> AgentProposalResponse:
    return AgentProposalResponse.model_validate(
        create_change_decision_proposal_impl(change_id=change_id, notify_email=notify_email, ctx=ctx)
    )


@mcp.tool(name="create_source_recovery_proposal", description="Create a persisted source-recovery proposal.", structured_output=True)
def create_source_recovery_proposal_tool(source_id: int, notify_email: str | None = None, ctx: Context | None = None) -> AgentProposalResponse:
    return AgentProposalResponse.model_validate(
        create_source_recovery_proposal_impl(source_id=source_id, notify_email=notify_email, ctx=ctx)
    )


@mcp.tool(name="create_family_relink_preview_proposal", description="Create a persisted family relink preview proposal.", structured_output=True)
def create_family_relink_preview_proposal_tool(
    raw_type_id: int,
    family_id: int,
    notify_email: str | None = None,
    ctx: Context | None = None,
) -> AgentProposalResponse:
    return AgentProposalResponse.model_validate(
        create_family_relink_preview_proposal_impl(
            raw_type_id=raw_type_id,
            family_id=family_id,
            notify_email=notify_email,
            ctx=ctx,
        )
    )


@mcp.tool(name="get_proposal", description="Fetch a persisted agent proposal.", structured_output=True)
def get_proposal_tool(proposal_id: int, notify_email: str | None = None, ctx: Context | None = None) -> AgentProposalResponse:
    return AgentProposalResponse.model_validate(get_proposal_impl(proposal_id=proposal_id, notify_email=notify_email, ctx=ctx))


@mcp.tool(name="create_approval_ticket", description="Create an approval ticket from an executable proposal.", structured_output=True)
def create_approval_ticket_tool(
    proposal_id: int,
    notify_email: str | None = None,
    channel: str = "mcp",
    ctx: Context | None = None,
) -> ApprovalTicketResponse:
    return ApprovalTicketResponse.model_validate(
        create_approval_ticket_impl(proposal_id=proposal_id, notify_email=notify_email, channel=channel, ctx=ctx)
    )


@mcp.tool(name="get_approval_ticket", description="Fetch an approval ticket.", structured_output=True)
def get_approval_ticket_tool(ticket_id: str, notify_email: str | None = None, ctx: Context | None = None) -> ApprovalTicketResponse:
    return ApprovalTicketResponse.model_validate(get_approval_ticket_impl(ticket_id=ticket_id, notify_email=notify_email, ctx=ctx))


@mcp.tool(name="confirm_approval_ticket", description="Confirm and execute an approval ticket.", structured_output=True)
def confirm_approval_ticket_tool(ticket_id: str, notify_email: str | None = None, ctx: Context | None = None) -> ApprovalTicketResponse:
    return ApprovalTicketResponse.model_validate(
        confirm_approval_ticket_impl(ticket_id=ticket_id, notify_email=notify_email, ctx=ctx)
    )


@mcp.tool(name="cancel_approval_ticket", description="Cancel an open approval ticket.", structured_output=True)
def cancel_approval_ticket_tool(ticket_id: str, notify_email: str | None = None, ctx: Context | None = None) -> ApprovalTicketResponse:
    return ApprovalTicketResponse.model_validate(
        cancel_approval_ticket_impl(ticket_id=ticket_id, notify_email=notify_email, ctx=ctx)
    )


@mcp.resource(
    "calendardiff://workspace",
    name="workspace",
    description="Workspace context for the configured default CalendarDIFF user.",
)
def workspace_resource() -> dict:
    return get_workspace_context_impl(notify_email=None)


@mcp.resource(
    "calendardiff://pending-changes",
    name="pending-changes",
    description="Pending changes for the configured default CalendarDIFF user.",
)
def pending_changes_resource() -> list[dict]:
    return list_pending_changes_impl(notify_email=None, limit=10)


@mcp.resource(
    "calendardiff://sources",
    name="sources",
    description="Source list for the configured default CalendarDIFF user.",
)
def sources_resource() -> list[dict]:
    return list_sources_impl(notify_email=None, status="active")


def main() -> None:
    transport = os.getenv("CALENDARDIFF_MCP_TRANSPORT", "stdio").strip() or "stdio"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
