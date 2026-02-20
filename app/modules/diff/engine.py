from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.db.models import ChangeType
from app.modules.sync.types import CanonicalEventInput


@dataclass(frozen=True)
class EventState:
    uid: str
    course_label: str
    title: str
    start_at_utc: datetime
    end_at_utc: datetime


@dataclass(frozen=True)
class ChangePayload:
    event_uid: str
    change_type: ChangeType
    before_json: dict | None
    after_json: dict | None
    delta_seconds: int | None
    course_label: str
    title: str


@dataclass(frozen=True)
class DiffResult:
    created_events: list[CanonicalEventInput]
    updated_events: list[CanonicalEventInput]
    removed_uids: list[str]
    changes: list[ChangePayload]


def compute_diff(
    canonical_events: dict[str, EventState],
    snapshot_events: dict[str, CanonicalEventInput],
    debounced_removed_uids: set[str],
) -> DiffResult:
    canonical_uids = set(canonical_events.keys())
    snapshot_uids = set(snapshot_events.keys())

    created_uids = snapshot_uids - canonical_uids
    candidate_removed_uids = canonical_uids - snapshot_uids
    removed_uids = sorted(candidate_removed_uids & debounced_removed_uids)

    created_events: list[CanonicalEventInput] = []
    updated_events: list[CanonicalEventInput] = []
    changes: list[ChangePayload] = []

    for uid in sorted(created_uids):
        event = snapshot_events[uid]
        created_events.append(event)
        changes.append(
            ChangePayload(
                event_uid=uid,
                change_type=ChangeType.CREATED,
                before_json=None,
                after_json=_event_to_json(event),
                delta_seconds=None,
                course_label=event.course_label,
                title=event.title,
            )
        )

    for uid in sorted(snapshot_uids & canonical_uids):
        before = canonical_events[uid]
        after = snapshot_events[uid]

        fields_changed: list[str] = []
        due_changed = (before.start_at_utc != after.start_at_utc) or (before.end_at_utc != after.end_at_utc)
        if due_changed:
            fields_changed.extend(["start_at_utc", "end_at_utc"])

        title_changed = before.title != after.title
        if title_changed:
            fields_changed.append("title")

        course_changed = before.course_label != after.course_label
        if course_changed:
            fields_changed.append("course_label")

        if not fields_changed:
            continue

        updated_events.append(after)

        if due_changed:
            change_type = ChangeType.DUE_CHANGED
            delta_seconds = int((after.start_at_utc - before.start_at_utc).total_seconds())
        elif title_changed:
            change_type = ChangeType.TITLE_CHANGED
            delta_seconds = None
        else:
            change_type = ChangeType.COURSE_CHANGED
            delta_seconds = None

        before_json: dict[str, object] = {}
        after_json: dict[str, object] = {}
        for field in sorted(set(fields_changed)):
            before_value = getattr(before, field)
            after_value = getattr(after, field)
            before_json[field] = _json_value(before_value)
            after_json[field] = _json_value(after_value)

        changes.append(
            ChangePayload(
                event_uid=uid,
                change_type=change_type,
                before_json=before_json,
                after_json=after_json,
                delta_seconds=delta_seconds,
                course_label=after.course_label,
                title=after.title,
            )
        )

    for uid in removed_uids:
        before = canonical_events[uid]
        changes.append(
            ChangePayload(
                event_uid=uid,
                change_type=ChangeType.REMOVED,
                before_json=_event_state_to_json(before),
                after_json=None,
                delta_seconds=None,
                course_label=before.course_label,
                title=before.title,
            )
        )

    return DiffResult(
        created_events=created_events,
        updated_events=updated_events,
        removed_uids=removed_uids,
        changes=changes,
    )


def _event_to_json(event: CanonicalEventInput) -> dict[str, object]:
    return {
        "uid": event.uid,
        "course_label": event.course_label,
        "title": event.title,
        "start_at_utc": event.start_at_utc.isoformat(),
        "end_at_utc": event.end_at_utc.isoformat(),
    }


def _event_state_to_json(event: EventState) -> dict[str, object]:
    return {
        "uid": event.uid,
        "course_label": event.course_label,
        "title": event.title,
        "start_at_utc": event.start_at_utc.isoformat(),
        "end_at_utc": event.end_at_utc.isoformat(),
    }


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
