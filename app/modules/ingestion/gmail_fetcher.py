from __future__ import annotations

from app.db.models import ConnectorResultStatus, InputSource
from app.modules.ingestion.connector_types import ConnectorFetchOutcome
from app.modules.input_control_plane.source_secrets import decode_source_secrets
from app.modules.sync.gmail_client import GmailAPIError, GmailClient, GmailHistoryExpiredError, GmailMessageMetadata


def fetch_gmail_changes(
    *,
    source: InputSource,
    request_id: str,
) -> ConnectorFetchOutcome:
    secrets = decode_source_secrets(source)
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

    cursor = source.cursor.cursor_json if source.cursor is not None and isinstance(source.cursor.cursor_json, dict) else {}
    cursor_history_id = cursor.get("history_id") if isinstance(cursor.get("history_id"), str) else None

    if cursor_history_id is None:
        if profile.history_id:
            return _no_change(cursor_patch={"history_id": profile.history_id})
        return _no_change()

    try:
        history_result = client.list_history(
            access_token=access_token,
            start_history_id=cursor_history_id,
        )
    except GmailHistoryExpiredError:
        if profile.history_id:
            return _no_change(cursor_patch={"history_id": profile.history_id})
        return _no_change()
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    latest_history_id = history_result.history_id or profile.history_id or cursor_history_id
    if not history_result.message_ids:
        return _no_change(cursor_patch={"history_id": latest_history_id})

    config = source.config.config_json if source.config is not None and isinstance(source.config.config_json, dict) else {}
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

        if not matches_gmail_source_filters(metadata=metadata, config=config):
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


def matches_gmail_source_filters(*, metadata: GmailMessageMetadata, config: dict) -> bool:
    label_id = config.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        if label_id not in metadata.label_ids:
            return False

    label_ids = config.get("label_ids")
    if isinstance(label_ids, list):
        normalized_label_ids = [value for value in label_ids if isinstance(value, str) and value.strip()]
        if normalized_label_ids and not any(label in metadata.label_ids for label in normalized_label_ids):
            return False

    from_contains = config.get("from_contains")
    if isinstance(from_contains, str) and from_contains.strip():
        if from_contains.strip().lower() not in metadata.from_header.lower():
            return False

    subject_keywords = config.get("subject_keywords")
    if isinstance(subject_keywords, list):
        normalized_keywords = [value.strip().lower() for value in subject_keywords if isinstance(value, str) and value.strip()]
        if normalized_keywords:
            subject_text = metadata.subject.lower()
            if not any(keyword in subject_text for keyword in normalized_keywords):
                return False

    return True


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
