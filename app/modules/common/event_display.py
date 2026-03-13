from __future__ import annotations

from dataclasses import asdict, dataclass

from pydantic import BaseModel

from app.modules.common.course_identity import course_display_name


class EventDisplayInvariantError(RuntimeError):
    pass


@dataclass(frozen=True)
class EventDisplay:
    course_display: str
    family_name: str
    ordinal: int | None
    display_label: str


class EventDisplayResponse(BaseModel):
    course_display: str
    family_name: str
    ordinal: int | None
    display_label: str


class UserFacingEventResponse(BaseModel):
    uid: str | None = None
    event_display: EventDisplayResponse
    due_date: str | None = None
    due_time: str | None = None
    time_precision: str


def build_display_label(*, course_display: str, family_name: str, ordinal: int | None) -> str:
    if ordinal is None:
        return f"{course_display} · {family_name}"
    return f"{course_display} · {family_name} {ordinal}"


def event_display_from_payload(
    payload: dict | BaseModel | None,
    *,
    strict: bool = True,
    family_name_override: str | None = None,
) -> EventDisplay | None:
    normalized_payload = _payload_as_dict(payload)
    if not isinstance(normalized_payload, dict):
        if strict:
            raise EventDisplayInvariantError("user-facing event payload is missing")
        return None
    derived_course_display = course_display_name(semantic_event=normalized_payload)
    family_name = family_name_override if isinstance(family_name_override, str) and family_name_override.strip() else normalized_payload.get("family_name")
    ordinal = normalized_payload.get("ordinal")
    if not isinstance(family_name, str) or not family_name.strip():
        if strict:
            raise EventDisplayInvariantError("user-facing event payload missing family_name")
        return None
    if not derived_course_display:
        if strict:
            raise EventDisplayInvariantError("user-facing event payload missing course identity")
        return None
    normalized_ordinal = ordinal if isinstance(ordinal, int) and ordinal > 0 else None
    return EventDisplay(
        course_display=derived_course_display,
        family_name=family_name.strip(),
        ordinal=normalized_ordinal,
        display_label=build_display_label(
            course_display=derived_course_display,
            family_name=family_name.strip(),
            ordinal=normalized_ordinal,
        ),
    )


def event_display_dict(
    payload: dict | BaseModel | None,
    *,
    strict: bool = True,
    family_name_override: str | None = None,
) -> dict | None:
    display = event_display_from_payload(payload, strict=strict, family_name_override=family_name_override)
    return asdict(display) if display is not None else None


def user_facing_event_view(
    payload: dict | BaseModel | None,
    *,
    strict: bool = True,
    family_name_override: str | None = None,
) -> dict | None:
    normalized_payload = _payload_as_dict(payload)
    if not isinstance(normalized_payload, dict):
        return None
    display = event_display_dict(normalized_payload, strict=strict, family_name_override=family_name_override)
    if display is None:
        return None
    return {
        "uid": normalized_payload.get("uid"),
        "event_display": display,
        "due_date": normalized_payload.get("due_date"),
        "due_time": normalized_payload.get("due_time"),
        "time_precision": normalized_payload.get("time_precision") or "datetime",
    }


def _payload_as_dict(payload: dict | BaseModel | None) -> dict | None:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return payload
    return None


__all__ = [
    "EventDisplay",
    "EventDisplayInvariantError",
    "EventDisplayResponse",
    "UserFacingEventResponse",
    "build_display_label",
    "event_display_dict",
    "event_display_from_payload",
    "user_facing_event_view",
]
