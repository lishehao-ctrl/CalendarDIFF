from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.modules.notify.interface import ChangeDigestItem, Notifier, SendResult
from app.modules.notify.runtime_context import get_notification_runtime_context

_WRITE_LOCK = threading.Lock()


class JsonlFileNotifier(Notifier):
    def send_changes_digest(
        self,
        to_email: str,
        review_label: str,
        user_id: int,
        items: list[ChangeDigestItem],
        timezone_name: str | None = None,
    ) -> SendResult:
        settings = get_settings()
        del timezone_name
        output_path = Path(settings.notify_jsonl_path).expanduser()
        context = get_notification_runtime_context()
        payload = {
            "sent_at": datetime.now(UTC).isoformat(),
            "to_email": to_email,
            "user_id": user_id,
            "review_label": review_label,
            "item_count": len(items),
            "item_entity_uids": [item.entity_uid for item in items],
            "item_display_labels": [
                item.after_display.display_label
                if item.after_display is not None
                else item.before_display.display_label
                if item.before_display is not None
                else item.entity_uid
                for item in items
            ],
            "run_id": context.get("run_id"),
            "semester": context.get("semester"),
            "batch": context.get("batch"),
        }
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=True)
            with _WRITE_LOCK:
                with output_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except Exception as exc:
            return SendResult(success=False, error=f"jsonl notifier write failed: {exc}")
        return SendResult(success=True)


__all__ = ["JsonlFileNotifier"]
