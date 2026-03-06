from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.modules.notify.interface import ChangeDigestItem, Notifier, SendResult

_WRITE_LOCK = threading.Lock()


class JsonlFileNotifier(Notifier):
    def send_changes_digest(
        self,
        to_email: str,
        input_label: str,
        input_id: int,
        items: list[ChangeDigestItem],
    ) -> SendResult:
        settings = get_settings()
        output_path = Path(settings.notify_jsonl_path).expanduser()
        payload = {
            "sent_at": datetime.now(UTC).isoformat(),
            "to_email": to_email,
            "input_id": input_id,
            "input_label": input_label,
            "item_count": len(items),
            "item_event_uids": [item.event_uid for item in items],
            "run_id": None,
            "semester": None,
            "batch": None,
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
