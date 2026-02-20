from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    settings = get_settings()
    if not x_api_key or x_api_key != settings.app_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


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
