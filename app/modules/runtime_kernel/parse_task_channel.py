from __future__ import annotations

from app.core.config import get_settings


def parse_queue_stream_key() -> str:
    settings = get_settings()
    return settings.llm_queue_stream_key.strip() or "llm:parse:stream"


def parse_queue_group() -> str:
    settings = get_settings()
    return settings.llm_queue_group.strip() or "llm-parse-workers"


__all__ = [
    "parse_queue_group",
    "parse_queue_stream_key",
]
