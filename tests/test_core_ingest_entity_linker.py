from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.db.models import (
    Change,
    ConnectorResultStatus,
    EventEntity,
    EventEntityLink,
    EventLinkBlock,
    EventLinkCandidate,
    EventLinkCandidateStatus,
    EventLinkOrigin,
    IngestResult,
    IngestTriggerType,
    Input,
    InputSource,
    InputSourceConfig,
    InputSourceCursor,
    InputSourceSecret,
    InputType,
    ReviewStatus,
    SourceEventObservation,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.core_ingest.service import apply_ingest_result_idempotent
from app.modules.review_changes.service import decide_review_change


def _create_sources(db_session: Session) -> tuple[InputSource, InputSource]:
    now = datetime.now(timezone.utc)
    user = User(
        email="linker-owner@example.com",
        notify_email="linker-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    calendar_source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="linker-calendar",
        display_name="Linker Calendar",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    gmail_source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="linker-gmail",
        display_name="Linker Gmail",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add_all([calendar_source, gmail_source])
    db_session.flush()

    db_session.add(InputSourceConfig(source_id=calendar_source.id, schema_version=1, config_json={}))
    db_session.add(
        InputSourceSecret(
            source_id=calendar_source.id,
            encrypted_payload=encrypt_secret(json.dumps({"url": "https://example.com/linker.ics"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=calendar_source.id, version=1, cursor_json={}))

    db_session.add(InputSourceConfig(source_id=gmail_source.id, schema_version=1, config_json={"label_id": "INBOX"}))
    db_session.add(
        InputSourceSecret(
            source_id=gmail_source.id,
            encrypted_payload=encrypt_secret(json.dumps({"access_token": "token", "account_email": "user@example.edu"})),
        )
    )
    db_session.add(InputSourceCursor(source_id=gmail_source.id, version=1, cursor_json={"history_id": "101"}))

    db_session.commit()
    db_session.refresh(calendar_source)
    db_session.refresh(gmail_source)
    return calendar_source, gmail_source


def _seed_result(db_session: Session, *, source: InputSource, request_id: str, records: list[dict]) -> None:
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


def _canonical_input_id(db_session: Session, *, user_id: int) -> int:
    row = db_session.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == f"canonical:user:{user_id}",
        )
    )
    assert row is not None
    return row.id


def test_gmail_weak_course_links_to_ics_entity_without_overwrite(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 8, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-cal-1",
        records=[
            {
                "record_type": "calendar.event.extracted",
                "payload": {
                    "uid": "ics-cse151a-exam1",
                    "title": "CSE 151A exam 1",
                    "start_at": due_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "course_label": "CSE 151A WI26",
                    "source_canonical": {
                        "external_event_id": "ics-cse151a-exam1",
                        "source_title": "CSE 151A exam 1",
                        "source_dtstart_utc": due_at.isoformat(),
                        "source_dtend_utc": end_at.isoformat(),
                        "organizer": "Prof Alice <alice@ucsd.edu>",
                    },
                    "enrichment": {
                        "course_parse": {
                            "dept": "CSE",
                            "number": 151,
                            "suffix": "A",
                            "quarter": "WI",
                            "year2": 26,
                            "confidence": 0.95,
                            "evidence": "CSE 151A WI26",
                        }
                    },
                    "raw_confidence": 0.95,
                },
            }
        ],
    )
    first_apply = apply_ingest_result_idempotent(db_session, request_id="linker-cal-1")
    assert first_apply["changes_created"] == 1

    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    decide_review_change(
        db_session,
        user_id=calendar_source.user_id,
        change_id=pending.id,
        decision="approve",
        note="approve seed",
    )

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-gmail-1",
        records=[
            {
                "record_type": "gmail.message.extracted",
                "payload": {
                    "message_id": "gmail-cse151-exam1",
                "subject": "CSE151 exam 1",
                "event_type": "exam",
                "due_at": due_at.isoformat(),
                "confidence": 0.9,
                "from_header": "Prof Alice <alice@ucsd.edu>",
                "raw_extract": {"course_hint": "CSE151"},
                "source_canonical": {
                    "external_event_id": "gmail-cse151-exam1",
                    "source_title": "CSE151 exam 1",
                    "source_dtstart_utc": due_at.isoformat(),
                    "source_dtend_utc": end_at.isoformat(),
                    "time_anchor_confidence": 0.9,
                    "from_header": "Prof Alice <alice@ucsd.edu>",
                },
                "enrichment": {
                    "course_parse": {
                        "dept": "CSE",
                            "number": 151,
                            "suffix": None,
                            "quarter": None,
                            "year2": None,
                            "confidence": 0.85,
                            "evidence": "CSE151",
                        }
                    },
                },
            }
        ],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="linker-gmail-1")
    assert second_apply["changes_created"] == 0

    pending_count = db_session.scalar(
        select(func.count(Change.id)).where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
    )
    assert int(pending_count or 0) == 0

    gmail_obs = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == gmail_source.id,
            SourceEventObservation.external_event_id == "gmail-cse151-exam1",
        )
    )
    assert gmail_obs is not None
    assert gmail_obs.merge_key == pending.event_uid
    link_row = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151-exam1",
        )
    )
    assert link_row is not None
    assert link_row.entity_uid == pending.event_uid
    assert link_row.link_origin == EventLinkOrigin.AUTO

    entity = db_session.scalar(
        select(EventEntity).where(
            EventEntity.user_id == calendar_source.user_id,
            EventEntity.entity_uid == pending.event_uid,
        )
    )
    assert entity is not None
    course_best = entity.course_best_json if isinstance(entity.course_best_json, dict) else {}
    assert course_best.get("display_name") == "CSE 151A WI26"
    aliases = entity.course_aliases_json if isinstance(entity.course_aliases_json, list) else []
    assert any("CSE 151" in alias for alias in aliases)


def test_prefix_match_without_extra_evidence_does_not_auto_link(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 9, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-prefix-cal-1",
        records=[
            {
                "record_type": "calendar.event.extracted",
                "payload": {
                    "uid": "ics-cse151a-lecture",
                    "title": "CSE 151A lecture",
                    "start_at": due_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "course_label": "CSE 151A WI26",
                    "source_canonical": {
                        "external_event_id": "ics-cse151a-lecture",
                        "source_title": "CSE 151A lecture",
                        "source_dtstart_utc": due_at.isoformat(),
                        "source_dtend_utc": end_at.isoformat(),
                    },
                    "enrichment": {
                        "course_parse": {
                            "dept": "CSE",
                            "number": 151,
                            "suffix": "A",
                            "quarter": "WI",
                            "year2": 26,
                            "confidence": 0.92,
                            "evidence": "CSE 151A WI26",
                        }
                    },
                    "raw_confidence": 0.92,
                },
            }
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-prefix-cal-1")
    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    decide_review_change(
        db_session,
        user_id=calendar_source.user_id,
        change_id=pending.id,
        decision="approve",
        note="approve seed",
    )

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-prefix-gmail-1",
        records=[
            {
                "record_type": "gmail.message.extracted",
                "payload": {
                    "message_id": "gmail-cse151-prefix-1",
                    "subject": "CSE151 update",
                    "event_type": "assignment",
                    "due_at": (due_at + timedelta(minutes=20)).isoformat(),
                    "confidence": 0.9,
                    "source_canonical": {
                        "external_event_id": "gmail-cse151-prefix-1",
                        "source_title": "CSE151 update",
                        "source_dtstart_utc": (due_at + timedelta(minutes=20)).isoformat(),
                        "source_dtend_utc": (end_at + timedelta(minutes=20)).isoformat(),
                        "time_anchor_confidence": 0.9,
                    },
                    "enrichment": {
                        "course_parse": {
                            "dept": "CSE",
                            "number": 151,
                            "suffix": None,
                            "quarter": None,
                            "year2": None,
                            "confidence": 0.9,
                            "evidence": "CSE151",
                        }
                    },
                },
            }
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-prefix-gmail-1")

    link_row = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151-prefix-1",
        )
    )
    assert link_row is None
    candidate_count = db_session.scalar(
        select(func.count(EventLinkCandidate.id)).where(
            EventLinkCandidate.user_id == calendar_source.user_id,
            EventLinkCandidate.source_id == gmail_source.id,
            EventLinkCandidate.external_event_id == "gmail-cse151-prefix-1",
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    )
    assert int(candidate_count or 0) == 0


def test_candidate_band_creates_silent_link_candidate(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 10, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-candidate-cal-1",
        records=[
            {
                "record_type": "calendar.event.extracted",
                "payload": {
                    "uid": "ics-cse151a-exam2",
                    "title": "CSE 151A exam 2",
                    "start_at": due_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "course_label": "CSE 151A WI26",
                    "source_canonical": {
                        "external_event_id": "ics-cse151a-exam2",
                        "source_title": "CSE 151A exam 2",
                        "source_dtstart_utc": due_at.isoformat(),
                        "source_dtend_utc": end_at.isoformat(),
                        "location": "Center Hall 101",
                    },
                    "enrichment": {
                        "course_parse": {
                            "dept": "CSE",
                            "number": 151,
                            "suffix": "A",
                            "quarter": "WI",
                            "year2": 26,
                            "confidence": 0.95,
                            "evidence": "CSE 151A WI26",
                        }
                    },
                    "raw_confidence": 0.95,
                },
            }
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-candidate-cal-1")
    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    decide_review_change(
        db_session,
        user_id=calendar_source.user_id,
        change_id=pending.id,
        decision="approve",
        note="approve seed",
    )

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-candidate-gmail-1",
        records=[
            {
                "record_type": "gmail.message.extracted",
                "payload": {
                    "message_id": "gmail-cse151-candidate-1",
                    "subject": "CSE151 exam 2 reminder",
                    "event_type": "exam",
                    "due_at": (due_at + timedelta(minutes=10)).isoformat(),
                    "confidence": 0.87,
                    "raw_extract": {"location_text": "Center Hall 101"},
                    "source_canonical": {
                        "external_event_id": "gmail-cse151-candidate-1",
                        "source_title": "CSE151 exam 2 reminder",
                        "source_dtstart_utc": (due_at + timedelta(minutes=10)).isoformat(),
                        "source_dtend_utc": (end_at + timedelta(minutes=10)).isoformat(),
                        "time_anchor_confidence": 0.87,
                    },
                    "enrichment": {
                        "course_parse": {
                            "dept": "CSE",
                            "number": 151,
                            "suffix": None,
                            "quarter": None,
                            "year2": None,
                            "confidence": 0.85,
                            "evidence": "CSE151",
                        }
                    },
                },
            }
        ],
    )
    result = apply_ingest_result_idempotent(db_session, request_id="linker-candidate-gmail-1")
    assert result["changes_created"] == 0

    candidate = db_session.scalar(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == calendar_source.user_id,
            EventLinkCandidate.source_id == gmail_source.id,
            EventLinkCandidate.external_event_id == "gmail-cse151-candidate-1",
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    )
    assert candidate is not None
    assert candidate.proposed_entity_uid == pending.event_uid
    link_row = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151-candidate-1",
        )
    )
    assert link_row is None

    gmail_obs = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == gmail_source.id,
            SourceEventObservation.external_event_id == "gmail-cse151-candidate-1",
        )
    )
    assert gmail_obs is None or gmail_obs.is_active is False


def test_blocked_pair_skips_candidate_creation(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 11, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-block-cal-1",
        records=[
            {
                "record_type": "calendar.event.extracted",
                "payload": {
                    "uid": "ics-cse151a-exam3",
                    "title": "CSE 151A exam 3",
                    "start_at": due_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "course_label": "CSE 151A WI26",
                    "source_canonical": {
                        "external_event_id": "ics-cse151a-exam3",
                        "source_title": "CSE 151A exam 3",
                        "source_dtstart_utc": due_at.isoformat(),
                        "source_dtend_utc": end_at.isoformat(),
                        "location": "WLH 2001",
                    },
                    "enrichment": {
                        "course_parse": {
                            "dept": "CSE",
                            "number": 151,
                            "suffix": "A",
                            "quarter": "WI",
                            "year2": 26,
                            "confidence": 0.95,
                            "evidence": "CSE 151A WI26",
                        }
                    },
                    "raw_confidence": 0.95,
                },
            }
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-block-cal-1")
    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    pending = db_session.scalar(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.desc())
        .limit(1)
    )
    assert pending is not None
    decide_review_change(
        db_session,
        user_id=calendar_source.user_id,
        change_id=pending.id,
        decision="approve",
        note="approve seed",
    )

    db_session.add(
        EventLinkBlock(
            user_id=calendar_source.user_id,
            source_id=gmail_source.id,
            external_event_id="gmail-cse151-blocked-1",
            blocked_entity_uid=pending.event_uid,
            created_by_user_id=calendar_source.user_id,
            note="manual reject",
        )
    )
    db_session.commit()

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-block-gmail-1",
        records=[
            {
                "record_type": "gmail.message.extracted",
                "payload": {
                    "message_id": "gmail-cse151-blocked-1",
                    "subject": "CSE151 exam 3 reminder",
                    "event_type": "exam",
                    "due_at": (due_at + timedelta(minutes=10)).isoformat(),
                    "confidence": 0.87,
                    "raw_extract": {"location_text": "WLH 2001"},
                    "source_canonical": {
                        "external_event_id": "gmail-cse151-blocked-1",
                        "source_title": "CSE151 exam 3 reminder",
                        "source_dtstart_utc": (due_at + timedelta(minutes=10)).isoformat(),
                        "source_dtend_utc": (end_at + timedelta(minutes=10)).isoformat(),
                        "time_anchor_confidence": 0.87,
                    },
                    "enrichment": {
                        "course_parse": {
                            "dept": "CSE",
                            "number": 151,
                            "suffix": None,
                            "quarter": None,
                            "year2": None,
                            "confidence": 0.85,
                            "evidence": "CSE151",
                        }
                    },
                },
            }
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-block-gmail-1")

    candidate_count = db_session.scalar(
        select(func.count(EventLinkCandidate.id)).where(
            EventLinkCandidate.user_id == calendar_source.user_id,
            EventLinkCandidate.source_id == gmail_source.id,
            EventLinkCandidate.external_event_id == "gmail-cse151-blocked-1",
        )
    )
    assert int(candidate_count or 0) == 0
