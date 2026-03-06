from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_NotificationContext = dict[str, str | int | None]
_NOTIFICATION_RUNTIME_CONTEXT: ContextVar[_NotificationContext | None] = ContextVar(
    "notification_runtime_context",
    default=None,
)


def get_notification_runtime_context() -> _NotificationContext:
    current = _NOTIFICATION_RUNTIME_CONTEXT.get()
    if current is None:
        return {"run_id": None, "semester": None, "batch": None}
    return {
        "run_id": current.get("run_id"),
        "semester": current.get("semester"),
        "batch": current.get("batch"),
    }


@contextmanager
def notification_runtime_context(
    *,
    run_id: str | None = None,
    semester: int | None = None,
    batch: int | None = None,
) -> Iterator[None]:
    token = _NOTIFICATION_RUNTIME_CONTEXT.set(
        {
            "run_id": run_id.strip() if isinstance(run_id, str) and run_id.strip() else None,
            "semester": int(semester) if isinstance(semester, int) else None,
            "batch": int(batch) if isinstance(batch, int) else None,
        }
    )
    try:
        yield
    finally:
        _NOTIFICATION_RUNTIME_CONTEXT.reset(token)


__all__ = ["get_notification_runtime_context", "notification_runtime_context"]
