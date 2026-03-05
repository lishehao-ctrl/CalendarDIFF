from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.security import encrypt_secret
from app.db.models.ingestion import ConnectorResultStatus, IngestResult
from app.db.models.input import IngestTriggerType, InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import Change, EventLinkCandidate, EventLinkCandidateStatus, Input, InputType, ReviewStatus
from app.db.models.shared import User
from app.modules.core_ingest.apply_service import apply_ingest_result_idempotent
from tests.support.payload_builders import (
    build_course_parse,
    build_event_parts,
    build_gmail_payload,
    build_link_signals,
)


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


def test_apply_gmail_records_create_candidates_and_pending_change(db_session) -> None:
    source = _create_gmail_source(db_session)
    records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": build_gmail_payload(
                message_id="gmail-msg-1",
                title="HW deadline extended",
                due_at=datetime(2026, 3, 3, 23, 59, tzinfo=timezone.utc),
                time_anchor_confidence=0.93,
                course_parse=build_course_parse(
                    dept="CSE",
                    number=100,
                    suffix=None,
                    quarter=None,
                    year2=None,
                    confidence=0.9,
                    evidence="CSE 100",
                ),
                event_parts=build_event_parts(
                    type="deadline",
                    index=1,
                    qualifier="hw",
                    confidence=0.93,
                    evidence="HW deadline",
                ),
                link_signals=build_link_signals(
                    keywords=[],
                    exam_sequence=None,
                    location_text="Gradescope",
                ),
            ),
        },
        {
            "record_type": "gmail.message.extracted",
            "payload": build_gmail_payload(
                message_id="gmail-msg-2",
                title="Campus announcement",
                due_at=None,
                time_anchor_confidence=0.71,
                course_parse=build_course_parse(
                    dept=None,
                    number=None,
                    suffix=None,
                    quarter=None,
                    year2=None,
                    confidence=0.0,
                    evidence="",
                ),
                event_parts=build_event_parts(
                    type="other",
                    index=None,
                    qualifier=None,
                    confidence=0.71,
                    evidence="announcement",
                ),
                link_signals=build_link_signals(),
            ),
        },
    ]
    _create_gmail_request_and_result(
        db_session,
        source=source,
        request_id="gmail-req-1",
        records=records,
    )

    applied = apply_ingest_result_idempotent(db_session, request_id="gmail-req-1")
    assert applied["changes_created"] == 0
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

    canonical_input_id = _canonical_input_id(db_session, user_id=source.user_id)
    pending_count = db_session.scalar(
        select(func.count(Change.id)).where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
    )
    assert int(pending_count or 0) == 0

    candidate = db_session.scalar(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == source.user_id,
            EventLinkCandidate.source_id == source.id,
            EventLinkCandidate.external_event_id == "gmail-msg-1",
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    )
    assert candidate is not None
    assert isinstance(candidate.score_breakdown_json, dict)
    assert candidate.score_breakdown_json.get("rule_reason") == "no_rule_match"


def test_apply_gmail_records_with_subject_alias_still_processes(db_session) -> None:
    source = _create_gmail_source(db_session)
    records = [
        {
            "record_type": "gmail.message.extracted",
            "payload": build_gmail_payload(
                message_id="gmail-msg-alias",
                title="Re: Update cSe_8A hw1 deadline moved",
                due_at=datetime(2026, 3, 11, 21, 0, tzinfo=timezone.utc),
                time_anchor_confidence=0.88,
                course_parse=build_course_parse(
                    dept="CSE",
                    number=8,
                    suffix="A",
                    quarter=None,
                    year2=None,
                    confidence=0.88,
                    evidence="cSe_8A",
                ),
                event_parts=build_event_parts(
                    type="deadline",
                    index=1,
                    qualifier="hw1",
                    confidence=0.88,
                    evidence="hw1 deadline moved",
                ),
                link_signals=build_link_signals(),
            ),
        }
    ]
    _create_gmail_request_and_result(
        db_session,
        source=source,
        request_id="gmail-req-alias",
        records=records,
    )

    applied = apply_ingest_result_idempotent(db_session, request_id="gmail-req-alias")
    assert applied["changes_created"] == 0

    candidate = db_session.scalar(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == source.user_id,
            EventLinkCandidate.source_id == source.id,
            EventLinkCandidate.external_event_id == "gmail-msg-alias",
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    )
    assert candidate is not None
    assert isinstance(candidate.score_breakdown_json, dict)
