from __future__ import annotations


def api_error_detail(
    *,
    code: str,
    message: str,
    message_code: str | None = None,
    message_params: dict | None = None,
    **extra: object,
) -> dict:
    payload = {
        "code": code,
        "message": message,
        "message_code": message_code or code,
        "message_params": message_params or {},
    }
    payload.update(extra)
    return payload


__all__ = ["api_error_detail"]
