from __future__ import annotations

import re
from datetime import date, datetime, timezone
from collections.abc import Callable
from typing import Any, cast

from app.db.models.ingestion import ConnectorResultStatus
from app.db.models.input import InputSource
from app.db.models.review import EventEntity, EventEntityLifecycle
from app.db.models.shared import CourseWorkItemLabelFamily
from app.modules.common.course_identity import normalized_course_identity_key
from app.modules.common.source_term_window import (
    SourceTermWindow,
    message_internal_date_in_window,
    parse_source_term_window,
    source_timezone_name,
)
from app.modules.ingestion.connector_types import ConnectorFetchOutcome
from app.modules.ingestion.source_orchestrator import route_gmail_message
from app.modules.input_control_plane.source_secrets import decode_source_secrets
from app.modules.sync.gmail_client import GmailAPIError, GmailClient, GmailHistoryExpiredError
from sqlalchemy import select
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import UnmappedInstanceError


_DEFAULT_GMAIL_LABEL_IDS = ("INBOX",)
_TERM_KEY_ACADEMIC_SCOPE_RE = re.compile(r"^\s*(?P<quarter>WI|SP|SU|FA)(?P<year2>\d{2})(?:\b|[^A-Za-z0-9].*)?$", re.IGNORECASE)


def fetch_gmail_changes(
    *,
    source: Any,
    request_id: str,
    emit_progress: Callable[[dict], None] | None = None,
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
    known_course_tokens = _known_course_tokens_for_source(input_source)
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
            known_course_tokens=known_course_tokens,
            emit_progress=emit_progress,
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
            known_course_tokens=known_course_tokens,
            emit_progress=emit_progress,
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
    total_messages = len(history_result.message_ids)
    _emit_progress(
        emit_progress,
        phase="gmail_history_fetch",
        label="Scanning Gmail delta",
        detail=f"Found {total_messages} changed emails to inspect in the active term window.",
        current=0,
        total=total_messages,
        unit="emails",
    )
    for index, message_id in enumerate(history_result.message_ids, start=1):
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
            known_course_tokens=known_course_tokens,
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
        if index == total_messages or index % 25 == 0:
            _emit_progress(
                emit_progress,
                phase="gmail_history_fetch",
                label="Scanning Gmail delta",
                detail=f"Inspected {index} of {total_messages} changed emails.",
                current=index,
                total=total_messages,
                unit="emails",
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
    known_course_tokens: set[str] | None = None,
) -> bool:
    metadata_label_ids_raw = getattr(metadata, "label_ids", [])
    metadata_label_ids = [value for value in metadata_label_ids_raw if isinstance(value, str)]
    metadata_from_header = str(getattr(metadata, "from_header", "") or "")
    metadata_subject = str(getattr(metadata, "subject", "") or "")
    metadata_snippet = str(getattr(metadata, "snippet", "") or "")
    metadata_body_text = str(getattr(metadata, "body_text", "") or "")
    metadata_internal_date = getattr(metadata, "internal_date", None)

    if term_window is not None and not message_internal_date_in_window(
        internal_date=metadata_internal_date,
        term_window=term_window,
        timezone_name=timezone_name,
    ):
        return False

    effective_label_ids = _effective_gmail_label_ids(config)
    if effective_label_ids and not any(label in metadata_label_ids for label in effective_label_ids):
        return False

    from_contains = config.get("from_contains")
    explicit_sender_signal = False
    if isinstance(from_contains, str) and from_contains.strip():
        if from_contains.strip().lower() not in metadata_from_header.lower():
            return False
        explicit_sender_signal = True

    subject_keywords = config.get("subject_keywords")
    explicit_subject_signal = False
    if isinstance(subject_keywords, list):
        normalized_keywords = [value.strip().lower() for value in subject_keywords if isinstance(value, str) and value.strip()]
        if normalized_keywords:
            subject_text = metadata_subject.lower()
            if not any(keyword in subject_text for keyword in normalized_keywords):
                return False
            explicit_subject_signal = True

    decision = route_gmail_message(
        from_header=metadata_from_header,
        subject=metadata_subject,
        snippet=metadata_snippet,
        body_text=metadata_body_text,
        explicit_sender_signal=explicit_sender_signal,
        explicit_subject_signal=explicit_subject_signal,
        known_course_tokens=known_course_tokens,
    )
    return decision.route == "parse"


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
    known_course_tokens: set[str],
    emit_progress: Callable[[dict], None] | None,
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
    total_messages = len(message_ids)
    _emit_progress(
        emit_progress,
        phase="gmail_bootstrap_fetch",
        label="Scanning Gmail bootstrap window",
        detail=f"Found {total_messages} emails in the current bootstrap window.",
        current=0,
        total=total_messages,
        unit="emails",
    )
    for index, message_id in enumerate(message_ids, start=1):
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
            known_course_tokens=known_course_tokens,
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
        if index == total_messages or index % 25 == 0:
            _emit_progress(
                emit_progress,
                phase="gmail_bootstrap_fetch",
                label="Scanning Gmail bootstrap window",
                detail=f"Inspected {index} of {total_messages} emails in the bootstrap window.",
                current=index,
                total=total_messages,
                unit="emails",
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


def _emit_progress(
    emit_progress: Callable[[dict], None] | None,
    *,
    phase: str,
    label: str,
    detail: str,
    current: int,
    total: int,
    unit: str,
) -> None:
    if emit_progress is None:
        return
    percent = round((current / total) * 100, 1) if total > 0 else None
    emit_progress(
        {
            "phase": phase,
            "label": label,
            "detail": detail,
            "current": current,
            "total": total,
            "percent": percent,
            "unit": unit,
        }
    )


def _bootstrap_label_ids(config: dict) -> list[str] | None:
    effective_label_ids = _effective_gmail_label_ids(config)
    return effective_label_ids or None


def _effective_gmail_label_ids(config: dict) -> list[str]:
    out: list[str] = []
    label_id = config.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        out.append(label_id.strip())
    label_ids = config.get("label_ids")
    if isinstance(label_ids, list):
        for item in label_ids:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
    if out:
        return list(dict.fromkeys(out))
    return list(_DEFAULT_GMAIL_LABEL_IDS)


def _known_course_tokens_for_source(source: InputSource) -> set[str]:
    try:
        session = object_session(source)
    except UnmappedInstanceError:
        return set()
    if session is None or not isinstance(getattr(source, "user_id", None), int):
        return set()
    term_window = parse_source_term_window(source, required=False)
    academic_scope = _parse_academic_scope_from_term_key(term_window.term_key if term_window is not None else None)

    tokens: set[str] = set()
    current_term_stems: set[tuple[str, int, str | None]] = set()
    entity_rows = session.execute(
        select(
            EventEntity.course_dept,
            EventEntity.course_number,
            EventEntity.course_suffix,
            EventEntity.course_quarter,
            EventEntity.course_year2,
            EventEntity.due_date,
        ).where(
            EventEntity.user_id == source.user_id,
            EventEntity.lifecycle == EventEntityLifecycle.ACTIVE,
        )
    ).all()
    for course_dept, course_number, course_suffix, course_quarter, course_year2, due_date in entity_rows:
        if not _entity_matches_source_term(
            term_window=term_window,
            academic_scope=academic_scope,
            due_date=due_date,
            course_quarter=course_quarter,
            course_year2=course_year2,
        ):
            continue
        stem = _course_stem(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix)
        if stem is None:
            continue
        current_term_stems.add(stem)
        tokens.update(_course_identity_tokens(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix))

    family_rows = session.execute(
        select(
            CourseWorkItemLabelFamily.course_dept,
            CourseWorkItemLabelFamily.course_number,
            CourseWorkItemLabelFamily.course_suffix,
            CourseWorkItemLabelFamily.course_quarter,
            CourseWorkItemLabelFamily.course_year2,
        ).where(CourseWorkItemLabelFamily.user_id == source.user_id)
    ).all()
    for course_dept, course_number, course_suffix, course_quarter, course_year2 in family_rows:
        stem = _course_stem(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix)
        if stem is None:
            continue
        if stem in current_term_stems or _course_mapping_matches_academic_scope(
            academic_scope=academic_scope,
            course_quarter=course_quarter,
            course_year2=course_year2,
        ):
            tokens.update(_course_identity_tokens(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix))
    return tokens


def _parse_academic_scope_from_term_key(term_key: object) -> tuple[str, int] | None:
    if not isinstance(term_key, str) or not term_key.strip():
        return None
    match = _TERM_KEY_ACADEMIC_SCOPE_RE.match(term_key.strip())
    if match is None:
        return None
    return (match.group("quarter").upper(), int(match.group("year2")))


def _entity_matches_source_term(
    *,
    term_window: SourceTermWindow | None,
    academic_scope: tuple[str, int] | None,
    due_date: object,
    course_quarter: object,
    course_year2: object,
) -> bool:
    if term_window is not None and isinstance(due_date, date):
        if term_window.term_from <= due_date <= term_window.term_to:
            return True
    return _course_mapping_matches_academic_scope(
        academic_scope=academic_scope,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )


def _course_mapping_matches_academic_scope(
    *,
    academic_scope: tuple[str, int] | None,
    course_quarter: object,
    course_year2: object,
) -> bool:
    if academic_scope is None:
        return False
    return (
        isinstance(course_quarter, str)
        and course_quarter.strip().upper() == academic_scope[0]
        and isinstance(course_year2, int)
        and course_year2 == academic_scope[1]
    )


def _course_stem(*, course_dept: object, course_number: object, course_suffix: object) -> tuple[str, int, str | None] | None:
    if not isinstance(course_dept, str) or not course_dept.strip() or not isinstance(course_number, int):
        return None
    normalized = normalized_course_identity_key(
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix if isinstance(course_suffix, str) else None,
        course_quarter=None,
        course_year2=None,
    )
    if not normalized:
        return None
    parts = normalized.split("|")
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return None
    suffix = parts[2].upper() if parts[2] else None
    return (parts[0].upper(), int(parts[1]), suffix)


def _course_identity_tokens(*, course_dept: object, course_number: object, course_suffix: object) -> set[str]:
    stem = _course_stem(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix)
    if stem is None:
        return set()
    dept, number, suffix = stem
    suffix_text = suffix or ""
    return {
        f"{dept} {number}{suffix_text}".lower(),
        f"{dept}{number}{suffix_text}".lower(),
    }


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
