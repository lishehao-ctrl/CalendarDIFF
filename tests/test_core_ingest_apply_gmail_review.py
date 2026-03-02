from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.security import encrypt_secret
from app.db.models import (
    Change,
    ConnectorResultStatus,
    EmailActionItem,
    EmailMessage,
    EmailRoute,
    EmailRuleLabel,
    Event,
    IngestResult,
    IngestTriggerType,
    Input,
    InputSource,
    InputSourceConfig,
    InputSourceCursor,
    InputSourceSecret,
    InputType,
    ReviewStatus,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.core_ingest.service import apply_ingest_result_idempotent
from app.modules.review_changes.service import decide_review_change


def _create_gmail_source(db_session) -> InputSource:
    now = datetime.now(timezone.utc)
    user = User(
        email="gmail-owner@example.com",
        notify_email="gmail-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-review-source",
        display_name="Gmail Review Source",
        is_active=True,
        poll_interval_seconds=900,
        last_polled_at=None,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()

    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={"label_id": "INBOX"}))
    db_session.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(
                json.dumps(
                    {
                        "access_token": "test-access-token",
                        "account_email": "student@example.edu",
                    }
                )
            ),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={"history_id": "100"}))
    db_session.commit()
    db_session.refresh(source)
    return source


def _create_gmail_request_and_result(db_session, *, source: InputSource, request_id: str, records: list[dict]) -> None:
    db_session.add(
        SyncRequest(
            request_id=request_id,
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.RUNNING,
            idempotency_key=f"idemp:{request_id}",
            metadata_json={"kind": "test"},
        )
    )
    db_session.add(
        IngestResult(
            request_id=request_id,
            source_id=source.id,
            provider=source.provider,
            status=ConnectorResultStatus.CHANGED,
            cursor_patch={},
            records=records,
            fetched_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
    )
    db_session.commit()


def _canonical_input_id(db_session, *, user_id: int) -> int:
    row = db_session.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == f"canonical:user:{user_id}",
        )
    )
    assert row is not None
    return row.id


def test_apply_gmail_records_write_audit_tables_and_pending_change(db_session) -> None:
    source = _create_gmail_source(db_session)
    records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": {
                "message_id": "gmail-msg-1",
                "subject": "HW deadline extended",
                "event_type": "deadline",
                "due_at": "2026-03-03T23:59:00+00:00",
                "confidence": 0.93,
                "raw_extract": {"course_hint": "CSE 100", "location_text": "Gradescope"},
            },
        },
        {
            "record_type": "gmail.message.extracted",
            "payload": {
                "message_id": "gmail-msg-2",
                "subject": "Campus announcement",
                "event_type": "announcement",
                "due_at": None,
                "confidence": 0.71,
                "raw_extract": {},
            },
        },
    ]
    _create_gmail_request_and_result(
        db_session,
        source=source,
        request_id="gmail-req-1",
        records=records,
    )

    applied = apply_ingest_result_idempotent(db_session, request_id="gmail-req-1")
    assert applied["changes_created"] == 1
    assert applied["idempotent_replay"] is False
    assert (
        db_session.scalar(
            select(func.count(Input.id)).where(
                Input.user_id == source.user_id,
                Input.identity_key.like("source:%"),
            )
        )
        == 0
    )

    assert db_session.scalar(select(func.count(EmailMessage.email_id))) == 2
    assert db_session.scalar(select(func.count(EmailRuleLabel.email_id))) == 2
    assert db_session.scalar(select(func.count(EmailRoute.email_id))) == 2
    assert db_session.scalar(select(func.count(EmailActionItem.id))) == 1

    route_1 = db_session.scalar(select(EmailRoute).where(EmailRoute.email_id == "gmail-msg-1"))
    route_2 = db_session.scalar(select(EmailRoute).where(EmailRoute.email_id == "gmail-msg-2"))
    assert route_1 is not None and route_1.route == "archive"
    assert route_2 is not None and route_2.route == "archive"

    canonical_input_id = _canonical_input_id(db_session, user_id=source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    assert pending.proposal_sources_json is not None

    decide_review_change(
        db_session,
        user_id=source.user_id,
        change_id=pending.id,
        decision="approve",
        note="approve gmail proposal",
    )
    assert db_session.scalar(select(func.count(Event.id)).where(Event.input_id == canonical_input_id)) == 1


def test_apply_gmail_records_extract_course_hint_from_subject_alias(db_session) -> None:
    source = _create_gmail_source(db_session)
    records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": {
                "message_id": "gmail-msg-alias",
                "subject": "Re: Update cSe_8A hw1 deadline moved",
                "event_type": "deadline",
                "due_at": "2026-03-11T21:00:00+00:00",
                "confidence": 0.88,
                "raw_extract": {},
            },
        }
    ]
    _create_gmail_request_and_result(
        db_session,
        source=source,
        request_id="gmail-req-alias",
        records=records,
    )

    applied = apply_ingest_result_idempotent(db_session, request_id="gmail-req-alias")
    assert applied["changes_created"] == 1

    canonical_input_id = _canonical_input_id(db_session, user_id=source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    assert isinstance(pending.after_json, dict)
    assert pending.after_json["course_label"] == "CSE8A"
