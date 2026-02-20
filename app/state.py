from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SchedulerStatus:
    running: bool = False
    last_run_started_at: datetime | None = None
    last_run_finished_at: datetime | None = None
    last_error: str | None = None
    last_skip_reason: str | None = None
    last_synced_sources: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "running": self.running,
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "last_error": self.last_error,
            "last_skip_reason": self.last_skip_reason,
            "last_synced_sources": self.last_synced_sources,
        }
