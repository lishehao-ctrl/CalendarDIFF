from __future__ import annotations

from dataclasses import dataclass

from app.db.models.runtime import ConnectorResultStatus


@dataclass(frozen=True)
class ConnectorFetchOutcome:
    status: ConnectorResultStatus
    cursor_patch: dict
    parse_payload: dict | None
    error_code: str | None
    error_message: str | None
    continuation_payload: dict | None = None
    continuation_delay_seconds: int | None = None


@dataclass(frozen=True)
class ConnectorFailureDecision:
    retryable: bool
    normalized_code: str
    normalized_message: str


__all__ = [
    "ConnectorFailureDecision",
    "ConnectorFetchOutcome",
]
