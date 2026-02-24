from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

ALLOWED_LABEL_KEYS = {
    "email_id",
    "label",
    "confidence",
    "reasons",
    "course_hints",
    "event_type",
    "action_items",
    "raw_extract",
    "notes",
}
REQUIRED_LABEL_KEYS = ALLOWED_LABEL_KEYS
EVENT_TYPES = {
    "deadline",
    "exam",
    "schedule_change",
    "assignment",
    "grade",
    "action_required",
    "announcement",
    "other",
}


def extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def parse_json_object_loose(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    extracted = extract_first_json_object(raw_text)
    if extracted is None:
        raise ValueError("no JSON object found in model response")

    try:
        parsed_extracted = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise ValueError(f"failed parsing extracted JSON object: {exc}") from exc
    if not isinstance(parsed_extracted, dict):
        raise ValueError("extracted JSON payload is not an object")
    return parsed_extracted


def _normalize_confidence(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("confidence cannot be boolean")
    if isinstance(value, (int, float)):
        confidence = float(value)
    elif isinstance(value, str):
        confidence = float(value.strip())
    else:
        raise ValueError("confidence must be numeric")
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be in [0,1]")
    return confidence


def _normalize_string_list(name: str, value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{name} must contain strings only")
        text = item.strip()
        if text:
            items.append(text)
    return items


def validate_and_normalize(
    *,
    payload: dict[str, Any],
    email_id: str,
    validator: Draft202012Validator,
) -> dict[str, Any]:
    extra_keys = sorted(set(payload.keys()) - ALLOWED_LABEL_KEYS)
    if extra_keys:
        raise ValueError(f"unexpected top-level keys: {extra_keys}")

    missing = sorted(REQUIRED_LABEL_KEYS - set(payload.keys()))
    if missing:
        raise ValueError(f"missing required keys: {missing}")

    raw_email_id = payload.get("email_id")
    normalized_email_id = raw_email_id.strip() if isinstance(raw_email_id, str) and raw_email_id.strip() else email_id

    raw_label = payload.get("label")
    if not isinstance(raw_label, str):
        raise ValueError("label must be a string")
    label = raw_label.strip().upper()
    if label not in {"KEEP", "DROP"}:
        raise ValueError("label must be KEEP or DROP")

    confidence = _normalize_confidence(payload.get("confidence"))
    reasons = _normalize_string_list("reasons", payload.get("reasons"))
    course_hints = _normalize_string_list("course_hints", payload.get("course_hints"))

    event_type_raw = payload.get("event_type")
    if event_type_raw is None:
        event_type: str | None = None
    elif isinstance(event_type_raw, str):
        event_type_candidate = event_type_raw.strip()
        if not event_type_candidate:
            event_type = None
        elif event_type_candidate in EVENT_TYPES:
            event_type = event_type_candidate
        else:
            raise ValueError(f"invalid event_type: {event_type_candidate}")
    else:
        raise ValueError("event_type must be string or null")

    action_items_raw = payload.get("action_items")
    if not isinstance(action_items_raw, list):
        raise ValueError("action_items must be an array")
    action_items: list[dict[str, Any]] = []
    for idx, item in enumerate(action_items_raw):
        if not isinstance(item, dict):
            raise ValueError(f"action_items[{idx}] must be an object")
        action = item.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ValueError(f"action_items[{idx}].action must be a non-empty string")

        due_iso = item.get("due_iso")
        if due_iso is not None and not isinstance(due_iso, str):
            raise ValueError(f"action_items[{idx}].due_iso must be string or null")
        where = item.get("where")
        if where is not None and not isinstance(where, str):
            raise ValueError(f"action_items[{idx}].where must be string or null")

        action_items.append(
            {
                "action": action.strip(),
                "due_iso": due_iso.strip() if isinstance(due_iso, str) and due_iso.strip() else None,
                "where": where.strip() if isinstance(where, str) and where.strip() else None,
            }
        )

    raw_extract_raw = payload.get("raw_extract")
    if not isinstance(raw_extract_raw, dict):
        raise ValueError("raw_extract must be an object")
    raw_extract: dict[str, str | None] = {}
    for key in ("deadline_text", "time_text", "location_text"):
        value = raw_extract_raw.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"raw_extract.{key} must be string or null")
        raw_extract[key] = value.strip() if isinstance(value, str) and value.strip() else None

    notes_value = payload.get("notes")
    if notes_value is not None and not isinstance(notes_value, str):
        raise ValueError("notes must be string or null")
    notes = notes_value.strip() if isinstance(notes_value, str) and notes_value.strip() else None

    if label == "DROP":
        event_type = None
        action_items = []

    normalized = {
        "email_id": normalized_email_id,
        "label": label,
        "confidence": confidence,
        "reasons": reasons,
        "course_hints": course_hints,
        "event_type": event_type,
        "action_items": action_items,
        "raw_extract": raw_extract,
        "notes": notes,
    }
    validator.validate(normalized)
    return normalized


def _dedupe_errors(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for message in messages:
        key = message.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def collect_validation_errors(
    *,
    raw_text: str,
    email_id: str,
    validator: Draft202012Validator,
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    parsed: dict[str, Any] | None = None

    try:
        parsed = parse_json_object_loose(raw_text)
    except Exception as exc:
        errors.append(f"parse_error: {exc}")
        return None, _dedupe_errors(errors)

    try:
        normalized = validate_and_normalize(payload=parsed, email_id=email_id, validator=validator)
        return normalized, []
    except Exception as exc:
        errors.append(f"validation_error: {exc}")
        schema_messages = sorted({err.message for err in validator.iter_errors(parsed)})
        errors.extend(f"schema_error: {message}" for message in schema_messages)
        return None, _dedupe_errors(errors)


def build_repair_prompt(
    *,
    bad_output: str,
    schema: dict[str, Any],
    validation_errors: list[str],
    max_bad_output_chars: int = 8000,
) -> str:
    schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    error_lines = "\n".join(f"- {message}" for message in validation_errors) if validation_errors else "- unknown_validation_error"
    return (
        "You returned invalid JSON for the required contract.\n"
        "Fix it and return ONLY one corrected JSON object.\n"
        "No explanation, no markdown.\n\n"
        "Schema (JSON):\n"
        f"{schema_text}\n\n"
        "Validation errors:\n"
        f"{error_lines}\n\n"
        "Invalid output:\n"
        f"{bad_output[:max_bad_output_chars]}"
    )
