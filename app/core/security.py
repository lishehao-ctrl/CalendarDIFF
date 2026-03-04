from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Callable

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException, status

from app.core.config import get_settings

InternalServiceName = str
ALL_INTERNAL_SERVICES: frozenset[InternalServiceName] = frozenset(
    {"input", "ingest", "review", "notification", "llm", "ops"}
)


def require_public_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    settings = get_settings()
    if not x_api_key or x_api_key != settings.app_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def require_internal_service_token(
    allowed_callers: set[InternalServiceName] | frozenset[InternalServiceName] | None = None,
) -> Callable[..., None]:
    allowed = set(allowed_callers or ALL_INTERNAL_SERVICES)
    unknown_callers = sorted(name for name in allowed if name not in ALL_INTERNAL_SERVICES)
    if unknown_callers:
        raise RuntimeError(f"unknown internal caller(s): {unknown_callers}")

    def _dependency(
        x_service_name: Annotated[str | None, Header(alias="X-Service-Name")] = None,
        x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
    ) -> None:
        if not x_service_name or not x_service_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing internal service credentials")

        caller = x_service_name.strip().lower()
        if caller not in ALL_INTERNAL_SERVICES:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal service name")
        if caller not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Internal caller is not allowed")

        expected_tokens = _get_internal_service_tokens()
        expected_token = expected_tokens.get(caller)
        if not expected_token or x_service_token != expected_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal service token")

    return _dependency


def _get_internal_service_tokens() -> dict[InternalServiceName, str]:
    settings = get_settings()
    return {
        "input": settings.internal_service_token_input,
        "ingest": settings.internal_service_token_ingest,
        "review": settings.internal_service_token_review,
        "notification": settings.internal_service_token_notification,
        "llm": settings.internal_service_token_llm,
        "ops": settings.internal_service_token_ops,
    }


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    settings = get_settings()
    try:
        return Fernet(settings.app_secret_key.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - configuration guard
        raise RuntimeError("APP_SECRET_KEY must be a valid Fernet key") from exc


def encrypt_secret(value: str) -> str:
    token = get_fernet().encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(value: str) -> str:
    try:
        decrypted = get_fernet().decrypt(value.encode("utf-8"))
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt stored secret") from exc
    return decrypted.decode("utf-8")
