from __future__ import annotations

from typing import Iterable, NoReturn

from fastapi import HTTPException, status


def normalize_status_filter(
    status_filter: str | None,
    *,
    default_value: str,
    allowed_values: Iterable[str],
    error_detail: str,
) -> str:
    normalized_status = status_filter.strip().lower() if isinstance(status_filter, str) else default_value
    if normalized_status not in set(allowed_values):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail,
        )
    return normalized_status


def raise_not_found(exc: Exception) -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def raise_unprocessable(exc: Exception) -> NoReturn:
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


__all__ = [
    "normalize_status_filter",
    "raise_not_found",
    "raise_unprocessable",
]
