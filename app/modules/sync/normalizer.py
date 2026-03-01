from __future__ import annotations

from datetime import datetime

from app.modules.sync.types import CanonicalEventInput, RawICSEvent


def normalize_events(raw_events: list[RawICSEvent]) -> list[CanonicalEventInput]:
    del raw_events
    raise RuntimeError(
        "calendar normalizer removed from runtime; see app.modules.sync.archive.legacy_normalizer for reference"
    )


def build_fingerprint_uid(title: str, start_at_utc: datetime, end_at_utc: datetime) -> str:
    del title, start_at_utc, end_at_utc
    raise RuntimeError(
        "calendar normalizer removed from runtime; see app.modules.sync.archive.legacy_normalizer for reference"
    )


def infer_course_label(summary: str, description: str) -> str:
    del summary, description
    raise RuntimeError(
        "calendar normalizer removed from runtime; see app.modules.sync.archive.legacy_normalizer for reference"
    )


def is_deadline_like_event(summary: str, description: str) -> bool:
    del summary, description
    raise RuntimeError(
        "calendar normalizer removed from runtime; see app.modules.sync.archive.legacy_normalizer for reference"
    )
