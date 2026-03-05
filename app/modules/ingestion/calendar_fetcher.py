from __future__ import annotations

from app.db.models.ingestion import ConnectorResultStatus
from app.db.models.input import InputSource
from app.modules.ingestion.connector_types import ConnectorFetchOutcome
from app.modules.ingestion.ics_delta import ICS_COMPONENT_FINGERPRINT_HASH_VERSION, IcsDeltaParseError, build_ics_delta
from app.modules.ingestion.job_claiming import extract_ics_component_fingerprints
from app.modules.input_control_plane.source_secrets import decode_source_secrets
from app.modules.sync.ics_client import ICSClient


def fetch_calendar_delta(*, source: InputSource) -> ConnectorFetchOutcome:
    secrets = decode_source_secrets(source)
    url = secrets.get("url")
    if not isinstance(url, str) or not url:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.AUTH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="calendar_missing_url",
            error_message="missing calendar url in source secrets",
        )

    cursor = source.cursor.cursor_json if source.cursor is not None and isinstance(source.cursor.cursor_json, dict) else {}
    if_none_match = cursor.get("etag") if isinstance(cursor.get("etag"), str) else None
    if_modified_since = cursor.get("last_modified") if isinstance(cursor.get("last_modified"), str) else None

    client = ICSClient()
    fetched = client.fetch(url, source.id, if_none_match=if_none_match, if_modified_since=if_modified_since)
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
        "ics_component_fingerprints_v1": delta.next_fingerprints,
        "ics_delta_components_total": delta.total_components,
        "ics_delta_changed_components": delta.changed_components_count,
        "ics_delta_removed_components": delta.removed_components_count,
        "ics_delta_invalid_components": delta.invalid_components,
    }
    if delta.changed_components_count + delta.removed_components_count == 0:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.NO_CHANGE,
            cursor_patch=cursor_patch,
            parse_payload=None,
            error_code=None,
            error_message=None,
        )

    parse_payload = {
        "kind": "calendar_delta_v1",
        "changed_components": delta.changed_components,
        "removed_component_keys": delta.removed_component_keys,
        "snapshot_meta": {
            "etag": fetched.etag,
            "last_modified": fetched.last_modified,
            "hash_version": ICS_COMPONENT_FINGERPRINT_HASH_VERSION,
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
