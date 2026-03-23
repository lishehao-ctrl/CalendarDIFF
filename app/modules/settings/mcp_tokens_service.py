from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import McpAccessToken
from app.db.models.shared import User

DEFAULT_MCP_TOKEN_SCOPES = ["calendardiff"]


class McpAccessTokenNotFoundError(RuntimeError):
    pass


def list_mcp_access_tokens(db: Session, *, user_id: int) -> list[McpAccessToken]:
    return list(
        db.scalars(
            select(McpAccessToken)
            .where(McpAccessToken.user_id == user_id)
            .order_by(McpAccessToken.created_at.desc(), McpAccessToken.token_id.desc())
        ).all()
    )


def create_mcp_access_token(
    db: Session,
    *,
    user: User,
    label: str,
    expires_in_days: int | None,
) -> tuple[McpAccessToken, str]:
    token_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(24)
    plaintext = f"cdmcp_{token_id}_{secret}"
    row = McpAccessToken(
        token_id=token_id,
        user_id=user.id,
        label=label.strip()[:128],
        token_hash=_hash_token(plaintext),
        scopes_json=list(DEFAULT_MCP_TOKEN_SCOPES),
        expires_at=_expires_at(expires_in_days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, plaintext


def revoke_mcp_access_token(db: Session, *, user_id: int, token_id: str) -> McpAccessToken:
    row = db.scalar(
        select(McpAccessToken)
        .where(McpAccessToken.token_id == token_id, McpAccessToken.user_id == user_id)
        .limit(1)
    )
    if row is None:
        raise McpAccessTokenNotFoundError("MCP access token not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(row)
    return row


def verify_mcp_access_token(db: Session, *, plaintext_token: str) -> tuple[McpAccessToken, User] | None:
    token_id = _extract_token_id(plaintext_token)
    if token_id is None:
        return None
    row = db.scalar(select(McpAccessToken).where(McpAccessToken.token_id == token_id).limit(1))
    if row is None:
        return None
    if row.revoked_at is not None:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at <= now:
        return None
    if row.token_hash != _hash_token(plaintext_token):
        return None
    row.last_used_at = now
    db.commit()
    db.refresh(row)
    return row, row.user


def _extract_token_id(value: str) -> str | None:
    token = value.strip()
    if not token.startswith("cdmcp_"):
        return None
    parts = token.split("_", 2)
    if len(parts) != 3:
        return None
    token_id = parts[1].strip()
    return token_id or None


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expires_at(expires_in_days: int | None) -> datetime | None:
    if expires_in_days is None:
        return None
    days = max(1, min(expires_in_days, 365))
    return datetime.now(timezone.utc) + timedelta(days=days)


__all__ = [
    "DEFAULT_MCP_TOKEN_SCOPES",
    "McpAccessTokenNotFoundError",
    "create_mcp_access_token",
    "list_mcp_access_tokens",
    "revoke_mcp_access_token",
    "verify_mcp_access_token",
]
