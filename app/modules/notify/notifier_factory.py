from __future__ import annotations

from app.core.config import get_settings
from app.modules.notify.email import SMTPEmailNotifier
from app.modules.notify.interface import Notifier
from app.modules.notify.jsonl_notifier import JsonlFileNotifier


def build_notifier() -> Notifier:
    settings = get_settings()
    mode = (settings.notify_sink_mode or "").strip().lower()
    if mode in {"", "smtp"}:
        return SMTPEmailNotifier()
    if mode == "jsonl":
        return JsonlFileNotifier()
    raise RuntimeError(f"unsupported NOTIFY_SINK_MODE: {settings.notify_sink_mode}")


__all__ = ["build_notifier"]
