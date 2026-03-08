from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from icalendar import Calendar
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.db.models.input import InputSource
from app.db.models.review import Change, Input, InputType, SourceEventObservation
from app.modules.review_changes.change_decision_service import ReviewChangeNotFoundError

PREVIEW_MAX_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


class EvidencePathError(RuntimeError):
    pass


class ReviewChangeEvidenceNotFoundError(RuntimeError):
    pass


class ReviewChangeEvidenceReadError(RuntimeError):
    pass


def preview_review_change_evidence(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> dict:
    row, resolved = resolve_change_evidence_file(db, user_id=user_id, change_id=change_id, side=side)
    try:
        content_bytes = resolved.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to read evidence preview error=%s", sanitize_log_message(str(exc)))
        raise ReviewChangeEvidenceReadError("Failed to prepare evidence preview") from exc

    truncated = len(content_bytes) > PREVIEW_MAX_BYTES
    preview_text = build_evidence_preview_text(content_bytes)
    events = build_evidence_preview_events(content_bytes)
    provider, structured_kind, structured_items = build_structured_preview(
        db=db,
        change=row,
        side=side,
        events=events,
    )
    return {
        "side": side,
        "content_type": "text/calendar",
        "truncated": truncated,
        "filename": f"change-{row.id}-{side}.ics",
        "provider": provider,
        "structured_kind": structured_kind,
        "structured_items": structured_items,
        "event_count": len(events),
        "events": events,
        "preview_text": preview_text,
    }


def extract_snapshot_evidence_key(raw_evidence_key: object) -> dict[str, Any] | None:
    if not isinstance(raw_evidence_key, dict):
        return None
    return raw_evidence_key


def extract_snapshot_evidence_path(raw_evidence_key: object) -> str | None:
    key = extract_snapshot_evidence_key(raw_evidence_key)
    if key is None:
        return None
    path_value = key.get("path")
    if isinstance(path_value, str) and path_value:
        return path_value
    return None


def resolve_change_evidence_file(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    side: Literal["before", "after"],
) -> tuple[Change, Path]:
    row = db.scalar(
        select(Change)
        .join(Input, Input.id == Change.input_id)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot), joinedload(Change.input))
        .where(Change.id == change_id, Input.user_id == user_id)
    )
    if row is None:
        raise ReviewChangeNotFoundError("Review change not found")

    snapshot = row.before_snapshot if side == "before" else row.after_snapshot
    evidence_path = extract_snapshot_evidence_path(snapshot.raw_evidence_key if snapshot is not None else None)
    if evidence_path is None:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found")

    try:
        resolved = resolve_evidence_file_path(evidence_path)
    except EvidencePathError as exc:
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found") from exc
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to resolve evidence path error=%s", sanitize_log_message(str(exc)))
        raise ReviewChangeEvidenceReadError("Failed to prepare evidence file") from exc

    if not resolved.exists() or not resolved.is_file():
        raise ReviewChangeEvidenceNotFoundError("Evidence file not found")
    return row, resolved


def build_evidence_preview_text(content_bytes: bytes) -> str:
    preview_bytes = content_bytes[:PREVIEW_MAX_BYTES]
    return preview_bytes.decode("utf-8", errors="replace")


def build_evidence_preview_events(content_bytes: bytes) -> list[dict[str, str | None]]:
    try:
        calendar = Calendar.from_ical(content_bytes)
    except Exception:
        return []

    events: list[dict[str, str | None]] = []
    for component in calendar.walk():
        if getattr(component, "name", "") != "VEVENT":
            continue
        events.append(
            {
                "uid": _normalize_text(component.get("UID")),
                "summary": _normalize_text(component.get("SUMMARY")),
                "dtstart": _normalize_ical_value(component.get("DTSTART")),
                "dtend": _normalize_ical_value(component.get("DTEND")),
                "location": _normalize_text(component.get("LOCATION")),
                "description": _normalize_text(component.get("DESCRIPTION")),
                "url": _normalize_text(component.get("URL")),
            }
        )
    return events


def build_structured_preview(
    *,
    db: Session,
    change: Change,
    side: Literal["before", "after"],
    events: list[dict[str, str | None]],
) -> tuple[str | None, Literal["ics_event", "gmail_event", "generic"], list[dict[str, str | None]]]:
    provider = _resolve_preview_provider(db=db, change=change, side=side)
    if provider == "gmail":
        gmail_items = _build_gmail_structured_items(db=db, change=change, side=side, events=events)
        if gmail_items:
            return provider, "gmail_event", gmail_items

    if events:
        return provider, "ics_event", _build_ics_structured_items(change=change, side=side, events=events)

    generic_items = _build_generic_structured_items(change=change, side=side)
    return provider, "generic", generic_items


def _build_ics_structured_items(
    *,
    change: Change,
    side: Literal["before", "after"],
    events: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    event_json = _event_json_for_side(change=change, side=side)
    course_label = _coerce_text(event_json.get("course_label")) if event_json else None
    items: list[dict[str, str | None]] = []
    for event in events:
        items.append(
            {
                "uid": event.get("uid"),
                "title": event.get("summary"),
                "course_label": course_label,
                "start_at": event.get("dtstart"),
                "end_at": event.get("dtend"),
                "location": event.get("location"),
                "description": event.get("description"),
                "url": event.get("url"),
                "sender": None,
                "snippet": None,
                "internal_date": None,
                "thread_id": None,
            }
        )
    return items


def _build_gmail_structured_items(
    *,
    db: Session,
    change: Change,
    side: Literal["before", "after"],
    events: list[dict[str, str | None]],
) -> list[dict[str, str | None]]:
    observation_payload = _lookup_primary_observation_payload(db=db, change=change)
    source_canonical = (
        observation_payload.get("source_canonical")
        if isinstance(observation_payload, dict) and isinstance(observation_payload.get("source_canonical"), dict)
        else {}
    )
    event_json = _event_json_for_side(change=change, side=side) or {}
    first_event = events[0] if events else {}

    title = _first_non_empty_str(
        event_json.get("title"),
        source_canonical.get("source_title"),
        first_event.get("summary"),
    )
    start_at = _first_non_empty_str(
        event_json.get("start_at_utc"),
        source_canonical.get("source_dtstart_utc"),
        first_event.get("dtstart"),
    )
    end_at = _first_non_empty_str(
        event_json.get("end_at_utc"),
        source_canonical.get("source_dtend_utc"),
        first_event.get("dtend"),
    )
    item = {
        "uid": _first_non_empty_str(event_json.get("uid"), source_canonical.get("external_event_id"), first_event.get("uid")),
        "title": title,
        "course_label": _first_non_empty_str(event_json.get("course_label"), observation_payload.get("course_label") if isinstance(observation_payload, dict) else None),
        "start_at": start_at,
        "end_at": end_at,
        "location": _coerce_text(source_canonical.get("location")),
        "description": None,
        "url": None,
        "sender": _coerce_text(source_canonical.get("from_header")),
        "snippet": _coerce_text(source_canonical.get("source_summary")),
        "internal_date": _coerce_text(source_canonical.get("internal_date")),
        "thread_id": _coerce_text(source_canonical.get("thread_id")),
    }
    if not any(item.values()):
        return []
    return [item]


def _build_generic_structured_items(
    *,
    change: Change,
    side: Literal["before", "after"],
) -> list[dict[str, str | None]]:
    event_json = _event_json_for_side(change=change, side=side)
    if not isinstance(event_json, dict):
        return []
    item = {
        "uid": _coerce_text(event_json.get("uid")),
        "title": _coerce_text(event_json.get("title")),
        "course_label": _coerce_text(event_json.get("course_label")),
        "start_at": _coerce_text(event_json.get("start_at_utc")),
        "end_at": _coerce_text(event_json.get("end_at_utc")),
        "location": None,
        "description": None,
        "url": None,
        "sender": None,
        "snippet": None,
        "internal_date": None,
        "thread_id": None,
    }
    if not any(item.values()):
        return []
    return [item]


def _resolve_preview_provider(db: Session, *, change: Change, side: Literal["before", "after"]) -> str | None:
    primary_source = _extract_primary_proposal_source(change.proposal_sources_json)
    if side == "after" and primary_source is not None:
        provider = _provider_from_source_ref(db=db, source_ref=primary_source)
        if provider:
            return provider

    proposal_providers = {
        provider
        for provider in (_provider_from_source_ref(db=db, source_ref=source_ref) for source_ref in _parse_source_refs(change.proposal_sources_json))
        if provider
    }
    if len(proposal_providers) == 1:
        return next(iter(proposal_providers))

    if change.input is not None and isinstance(change.input.type, InputType):
        if change.input.type == InputType.EMAIL:
            return "gmail"
        if change.input.type == InputType.ICS:
            return "ics"
    return None


def _parse_source_refs(raw_sources: object) -> list[dict[str, object]]:
    if not isinstance(raw_sources, list):
        return []
    return [item for item in raw_sources if isinstance(item, dict)]


def _extract_primary_proposal_source(raw_sources: object) -> dict[str, object] | None:
    for item in _parse_source_refs(raw_sources):
        if isinstance(item.get("source_id"), int):
            return item
    return None


def _provider_from_source_ref(*, db: Session, source_ref: dict[str, object]) -> str | None:
    provider = _normalize_provider(source_ref.get("provider"))
    if provider:
        return provider
    source_id = source_ref.get("source_id")
    if not isinstance(source_id, int):
        return None
    source = db.get(InputSource, source_id)
    if source is None:
        return None
    return _normalize_provider(source.provider)


def _lookup_primary_observation_payload(db: Session, *, change: Change) -> dict[str, Any]:
    primary_source = _extract_primary_proposal_source(change.proposal_sources_json)
    if primary_source is None:
        return {}

    source_id = primary_source.get("source_id")
    if not isinstance(source_id, int):
        return {}

    stmt = (
        select(SourceEventObservation.event_payload)
        .where(SourceEventObservation.source_id == source_id)
        .order_by(SourceEventObservation.observed_at.desc())
    )
    if isinstance(change.proposal_merge_key, str) and change.proposal_merge_key.strip():
        stmt = stmt.where(SourceEventObservation.merge_key == change.proposal_merge_key.strip())
    external_event_id = primary_source.get("external_event_id")
    if isinstance(external_event_id, str) and external_event_id.strip():
        stmt = stmt.where(SourceEventObservation.external_event_id == external_event_id.strip())

    payload = db.execute(stmt.limit(1)).scalar_one_or_none()
    return payload if isinstance(payload, dict) else {}


def _event_json_for_side(*, change: Change, side: Literal["before", "after"]) -> dict[str, Any] | None:
    payload = change.before_json if side == "before" else change.after_json
    return payload if isinstance(payload, dict) else None


def _normalize_provider(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_ical_value(value: object) -> str | None:
    if value is None:
        return None
    candidate = value.dt if hasattr(value, "dt") else value
    text = str(candidate).strip()
    return text or None


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _first_non_empty_str(*values: object) -> str | None:
    for value in values:
        text = _coerce_text(value)
        if text:
            return text
    return None


def resolve_evidence_file_path(raw_path: str) -> Path:
    normalized = raw_path.strip() if isinstance(raw_path, str) else ""
    if not normalized:
        raise EvidencePathError("evidence path is empty")

    settings = get_settings()
    configured_base = Path(settings.evidence_dir).expanduser()
    if configured_base.is_absolute():
        base_dir = configured_base.resolve()
    else:
        base_dir = (Path.cwd() / configured_base).resolve()

    path_obj = Path(normalized).expanduser()
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
    else:
        configured_parts = configured_base.parts
        if configured_parts and path_obj.parts[: len(configured_parts)] == configured_parts:
            resolved = (Path.cwd() / path_obj).resolve()
        else:
            resolved = (base_dir / path_obj).resolve()

    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise EvidencePathError("evidence path escapes configured evidence_dir") from exc
    return resolved


__all__ = [
    "EvidencePathError",
    "ReviewChangeEvidenceNotFoundError",
    "ReviewChangeEvidenceReadError",
    "build_evidence_preview_events",
    "build_evidence_preview_text",
    "extract_snapshot_evidence_key",
    "extract_snapshot_evidence_path",
    "preview_review_change_evidence",
    "resolve_change_evidence_file",
    "resolve_evidence_file_path",
]
