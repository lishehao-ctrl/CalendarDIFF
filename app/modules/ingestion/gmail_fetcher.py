from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from app.db.models.ingestion import ConnectorResultStatus
from app.db.models.input import InputSource
from app.modules.common.source_term_window import (
    SourceTermWindow,
    message_internal_date_in_window,
    parse_source_term_window,
    source_timezone_name,
)
from app.modules.ingestion.connector_types import ConnectorFetchOutcome
from app.modules.input_control_plane.source_secrets import decode_source_secrets
from app.modules.sync.gmail_client import GmailAPIError, GmailClient, GmailHistoryExpiredError


def fetch_gmail_changes(
    *,
    source: Any,
    request_id: str,
) -> ConnectorFetchOutcome:
    input_source = cast(InputSource, source)
    secrets = decode_source_secrets(input_source)
    access_token = secrets.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.AUTH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="gmail_missing_access_token",
            error_message="missing access token for gmail source",
        )

    client = GmailClient()
    try:
        profile = client.get_profile(access_token=access_token)
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    source_config = getattr(input_source, "config", None)
    config_json = getattr(source_config, "config_json", None)
    config = config_json if isinstance(config_json, dict) else {}
    term_window = parse_source_term_window(input_source, required=False)
    timezone_name = source_timezone_name(input_source)
    now = datetime.now(timezone.utc)
    if term_window is not None and term_window.is_expired(now=now, timezone_name=timezone_name):
        latest_history_id = profile.history_id
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    source_cursor = getattr(input_source, "cursor", None)
    cursor_json = getattr(source_cursor, "cursor_json", None)
    cursor = cursor_json if isinstance(cursor_json, dict) else {}
    cursor_history_id = cursor.get("history_id") if isinstance(cursor.get("history_id"), str) else None

    if cursor_history_id is None:
        return _bootstrap_gmail_messages(
            client=client,
            access_token=access_token,
            source=input_source,
            request_id=request_id,
            profile=profile,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
        )

    try:
        history_result = client.list_history(
            access_token=access_token,
            start_history_id=cursor_history_id,
        )
    except GmailHistoryExpiredError:
        return _bootstrap_gmail_messages(
            client=client,
            access_token=access_token,
            source=input_source,
            request_id=request_id,
            profile=profile,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    latest_history_id = history_result.history_id or profile.history_id or cursor_history_id
    if not history_result.message_ids:
        return _no_change(cursor_patch={"history_id": latest_history_id})

    message_payloads: list[dict] = []
    for message_id in history_result.message_ids:
        try:
            metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
        except GmailAPIError as exc:
            if exc.status_code in {401, 403}:
                return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
            if exc.status_code == 429:
                return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
            return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

        if not matches_gmail_source_filters(
            metadata=metadata,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
        ):
            continue

        message_payloads.append(
            {
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "snippet": metadata.snippet,
                "body_text": metadata.body_text,
                "from_header": metadata.from_header,
                "internal_date": metadata.internal_date,
                "label_ids": metadata.label_ids,
                "history_id": latest_history_id,
                "account_email": profile.email_address,
                "request_id": request_id,
            }
        )

    cursor_patch = {"history_id": latest_history_id}
    if not message_payloads:
        return _no_change(cursor_patch=cursor_patch)

    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.CHANGED,
        cursor_patch=cursor_patch,
        parse_payload={"kind": "gmail", "messages": message_payloads},
        error_code=None,
        error_message=None,
    )


def matches_gmail_source_filters(
    *,
    metadata: Any,
    config: dict,
    term_window: SourceTermWindow | None = None,
    timezone_name: str | None = None,
) -> bool:
    metadata_label_ids_raw = getattr(metadata, "label_ids", [])
    metadata_label_ids = [value for value in metadata_label_ids_raw if isinstance(value, str)]
    metadata_from_header = str(getattr(metadata, "from_header", "") or "")
    metadata_subject = str(getattr(metadata, "subject", "") or "")
    metadata_internal_date = getattr(metadata, "internal_date", None)

    if term_window is not None and not message_internal_date_in_window(
        internal_date=metadata_internal_date,
        term_window=term_window,
        timezone_name=timezone_name,
    ):
        return False

    label_id = config.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        if label_id not in metadata_label_ids:
            return False

    required_label_ids = config.get("label_ids")
    if isinstance(required_label_ids, list):
        normalized_label_ids = [value for value in required_label_ids if isinstance(value, str) and value.strip()]
        if normalized_label_ids and not any(label in metadata_label_ids for label in normalized_label_ids):
            return False

    from_contains = config.get("from_contains")
    if isinstance(from_contains, str) and from_contains.strip():
        if from_contains.strip().lower() not in metadata_from_header.lower():
            return False

    subject_keywords = config.get("subject_keywords")
    if isinstance(subject_keywords, list):
        normalized_keywords = [value.strip().lower() for value in subject_keywords if isinstance(value, str) and value.strip()]
        if normalized_keywords:
            subject_text = metadata_subject.lower()
            if not any(keyword in subject_text for keyword in normalized_keywords):
                return False

    return True


def _bootstrap_gmail_messages(
    *,
    client: GmailClient,
    access_token: str,
    source: InputSource,
    request_id: str,
    profile: Any,
    config: dict,
    term_window: SourceTermWindow | None,
    timezone_name: str | None,
) -> ConnectorFetchOutcome:
    latest_history_id = profile.history_id if isinstance(profile.history_id, str) and profile.history_id else None
    if term_window is None:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    start_date, end_exclusive = term_window.gmail_query_bounds()
    query = f"after:{start_date} before:{end_exclusive}"
    try:
        message_ids = client.list_message_ids(
            access_token=access_token,
            query=query,
            label_ids=_bootstrap_label_ids(config),
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    if not message_ids:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    message_payloads: list[dict] = []
    for message_id in message_ids:
        try:
            metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
        except GmailAPIError as exc:
            if exc.status_code in {401, 403}:
                return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
            if exc.status_code == 429:
                return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
            return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)
        if not matches_gmail_source_filters(
            metadata=metadata,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
        ):
            continue
        message_payloads.append(
            {
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "snippet": metadata.snippet,
                "body_text": metadata.body_text,
                "from_header": metadata.from_header,
                "internal_date": metadata.internal_date,
                "label_ids": metadata.label_ids,
                "history_id": latest_history_id,
                "account_email": profile.email_address,
                "request_id": request_id,
            }
        )

    if not message_payloads:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.CHANGED,
        cursor_patch={"history_id": latest_history_id} if latest_history_id else {},
        parse_payload={"kind": "gmail", "messages": message_payloads},
        error_code=None,
        error_message=None,
    )


def _bootstrap_label_ids(config: dict) -> list[str] | None:
    out: list[str] = []
    label_id = config.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        out.append(label_id.strip())
    label_ids = config.get("label_ids")
    if isinstance(label_ids, list):
        for item in label_ids:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
    return out or None


def _failed(code: str, message: str, *, status: ConnectorResultStatus) -> ConnectorFetchOutcome:
    return ConnectorFetchOutcome(
        status=status,
        cursor_patch={},
        parse_payload=None,
        error_code=code,
        error_message=message,
    )


def _no_change(*, cursor_patch: dict | None = None) -> ConnectorFetchOutcome:
    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.NO_CHANGE,
        cursor_patch=cursor_patch or {},
        parse_payload=None,
        error_code=None,
        error_message=None,
    )


__all__ = ["fetch_gmail_changes", "matches_gmail_source_filters"]
