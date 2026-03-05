from __future__ import annotations

import json

from app.core.security import decrypt_secret
from app.db.models.input import InputSource


def decode_source_secrets(source: InputSource) -> dict:
    if source.secrets is None:
        return {}
    try:
        raw = decrypt_secret(source.secrets.encrypted_payload)
        parsed = json.loads(raw)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


__all__ = ["decode_source_secrets"]
