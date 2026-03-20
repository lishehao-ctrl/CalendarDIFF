from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from app.db.models.runtime import ConnectorResultStatus
from app.db.models.input import InputSource
from app.modules.common.source_term_window import calendar_component_in_window, parse_source_term_window, source_timezone_name
from app.modules.runtime.connectors.connector_types import ConnectorFetchOutcome
from app.modules.runtime.connectors.ics_delta import ICS_COMPONENT_FINGERPRINT_HASH_KEY, IcsDeltaParseError, build_ics_delta
from app.modules.runtime.connectors.job_claiming import extract_ics_component_fingerprints
from app.modules.sources.source_secrets import decode_source_secrets
from app.modules.runtime.connectors.clients.ics_client import ICSClient


def fetch_calendar_delta(*, source: Any, emit_progress: Callable[[dict], None] | None = None) -> ConnectorFetchOutcome:
    input_source = cast(InputSource, source)
    secrets = decode_source_secrets(cast(InputSource, source))
    url = secrets.get("url")
    if not isinstance(url, str) or not url:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.AUTH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="calendar_missing_url",
            error_message="missing calendar url in source secrets",
        )

    source_cursor = getattr(input_source, "cursor", None)
    cursor_json = getattr(source_cursor, "cursor_json", None)
    cursor = cursor_json if isinstance(cursor_json, dict) else {}
    if_none_match = cursor.get("etag") if isinstance(cursor.get("etag"), str) else None
    if_modified_since = cursor.get("last_modified") if isinstance(cursor.get("last_modified"), str) else None

    client = ICSClient()
    source_id = int(getattr(input_source, "id", 0))
    fetched = client.fetch(url, source_id, if_none_match=if_none_match, if_modified_since=if_modified_since)
    if fetched.not_modified:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.NO_CHANGE,
            cursor_patch={
                "etag": fetched.etag,
                "last_modified": fetched.last_modified,
                "ics_delta_components_total": 0,
                "ics_delta_changed_components": 0,
                "ics_delta_removed_components": 0,
                "ics_delta_invalid_components": 0,
            },
            parse_payload=None,
            error_code=None,
            error_message=None,
        )
    if fetched.content is None:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.FETCH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="calendar_empty_content",
            error_message="calendar fetch returned empty content",
        )

    previous_fingerprints = extract_ics_component_fingerprints(cursor)
    try:
        delta = build_ics_delta(content=fetched.content, previous_fingerprints=previous_fingerprints)
    except IcsDeltaParseError as exc:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.PARSE_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="calendar_delta_parse_failed",
            error_message=str(exc),
        )

    cursor_patch = {
        "etag": fetched.etag,
        "last_modified": fetched.last_modified,
        "ics_component_fingerprints": delta.next_fingerprints,
        "ics_delta_components_total": delta.total_components,
        "ics_delta_changed_components": delta.changed_components_count,
        "ics_delta_removed_components": delta.removed_components_count,
        "ics_delta_invalid_components": delta.invalid_components,
    }
    term_window = parse_source_term_window(input_source, required=False)
    if term_window is not None:
        timezone_name = source_timezone_name(input_source)
        filtered_changed_components = [
            component
            for component in delta.changed_components
            if calendar_component_in_window(
                component_ical_b64=component.get("component_ical_b64"),
                term_window=term_window,
                timezone_name=timezone_name,
            )
        ]
    else:
        filtered_changed_components = delta.changed_components

    if emit_progress is not None:
        emit_progress(
            {
                "phase": "calendar_delta_ready",
                "label": "Calendar delta fetched",
                "detail": (
                    f"{len(filtered_changed_components)} changed calendar events and "
                    f"{delta.removed_components_count} removals are ready for intake."
                ),
                "current": 0,
                "total": len(filtered_changed_components),
                "percent": 0 if filtered_changed_components else (100 if delta.removed_components_count > 0 else None),
                "unit": "events" if (filtered_changed_components or delta.removed_components_count) else None,
            }
        )

    if len(filtered_changed_components) + delta.removed_components_count == 0:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.NO_CHANGE,
            cursor_patch=cursor_patch,
            parse_payload=None,
            error_code=None,
            error_message=None,
        )

    parse_payload = {
        "kind": "calendar_delta",
        "changed_components": filtered_changed_components,
        "removed_component_keys": delta.removed_component_keys,
        "snapshot_meta": {
            "etag": fetched.etag,
            "last_modified": fetched.last_modified,
            "hash_key": ICS_COMPONENT_FINGERPRINT_HASH_KEY,
        },
    }
    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.CHANGED,
        cursor_patch=cursor_patch,
        parse_payload=parse_payload,
        error_code=None,
        error_message=None,
    )


__all__ = ["fetch_calendar_delta"]
