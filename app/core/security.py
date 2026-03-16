from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.core.oauth_config import resolve_oauth_token_encryption_key



def require_public_api_key(x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None) -> None:
    settings = get_settings()
    if not x_api_key or x_api_key != settings.app_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    settings = get_settings()
    key, source = resolve_oauth_token_encryption_key(settings=settings)
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - configuration guard
        raise RuntimeError(f"{source} must be a valid Fernet key") from exc



def encrypt_secret(value: str) -> str:
    token = get_fernet().encrypt(value.encode("utf-8"))
    return token.decode("utf-8")



def decrypt_secret(value: str) -> str:
    try:
        decrypted = get_fernet().decrypt(value.encode("utf-8"))
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt stored secret") from exc
    return decrypted.decode("utf-8")
