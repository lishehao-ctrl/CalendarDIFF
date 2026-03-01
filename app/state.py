from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SchedulerStatus:
    running: bool = False
    instance_id: str | None = None
    last_tick_at: datetime | None = None
    last_tick_lock_acquired: bool | None = None
    last_run_started_at: datetime | None = None
    last_run_finished_at: datetime | None = None
    last_error: str | None = None
    last_skip_reason: str | None = None
    last_synced_sources: int = 0
    last_run_success_count: int = 0
    last_run_failed_count: int = 0
    last_run_notification_failed_count: int = 0
    cumulative_success_count: int = 0
    cumulative_failed_count: int = 0
    cumulative_notification_failed_count: int = 0
    cumulative_run_executed_count: int = 0
    cumulative_run_skipped_lock_count: int = 0
    next_expected_check_at: datetime | None = None
    next_expected_source_id: int | None = None
    lock_backend: str = "postgres_advisory"
    database_dialect: str = "postgresql"
    schema_guard_blocked: bool = False
    schema_guard_message: str | None = None
    last_retention_cleanup_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "running": self.running,
            "instance_id": self.instance_id,
            "last_tick_at": self.last_tick_at,
            "last_tick_lock_acquired": self.last_tick_lock_acquired,
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "last_error": self.last_error,
            "last_skip_reason": self.last_skip_reason,
            "last_synced_sources": self.last_synced_sources,
            "last_run_success_count": self.last_run_success_count,
            "last_run_failed_count": self.last_run_failed_count,
            "last_run_notification_failed_count": self.last_run_notification_failed_count,
            "cumulative_success_count": self.cumulative_success_count,
            "cumulative_failed_count": self.cumulative_failed_count,
            "cumulative_notification_failed_count": self.cumulative_notification_failed_count,
            "cumulative_run_executed_count": self.cumulative_run_executed_count,
            "cumulative_run_skipped_lock_count": self.cumulative_run_skipped_lock_count,
            "next_expected_check_at": self.next_expected_check_at,
            "next_expected_source_id": self.next_expected_source_id,
            "lock_backend": self.lock_backend,
            "database_dialect": self.database_dialect,
            "schema_guard_blocked": self.schema_guard_blocked,
            "schema_guard_message": self.schema_guard_message,
            "last_retention_cleanup_at": self.last_retention_cleanup_at,
        }
