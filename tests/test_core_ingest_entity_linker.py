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
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
    User,
)
from app.modules.core_ingest.apply_service import apply_ingest_result_idempotent
from app.modules.review_changes.change_decision_service import decide_review_change
from tests.support.payload_builders import (
    build_calendar_payload,
    build_course_parse,
    build_event_parts,
    build_gmail_payload,
    build_link_signals,
)


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


def _approve_all_pending_changes(db_session: Session, *, user_id: int, canonical_input_id: int) -> list[Change]:
    pending_rows = db_session.scalars(
        select(Change)
        .where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.asc())
    ).all()
    assert pending_rows
    for row in pending_rows:
        decide_review_change(
            db_session,
            user_id=user_id,
            change_id=row.id,
            decision="approve",
            note="approve seed",
        )
    return pending_rows


def _calendar_exam_record(
    *,
    external_event_id: str,
    title: str,
    start_at: datetime,
    end_at: datetime,
    dept: str,
    number: int,
    suffix: str | None,
    index: int,
    location: str | None = None,
) -> dict:
    return {
        "record_type": "calendar.event.extracted",
        "payload": build_calendar_payload(
            external_event_id=external_event_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            location=location,
            course_parse=build_course_parse(
                dept=dept,
                number=number,
                suffix=suffix,
                quarter="WI",
                year2=26,
                confidence=0.95,
                evidence=f"{dept} {number}{suffix or ''} WI26",
            ),
            event_parts=build_event_parts(
                type="exam",
                index=index,
                confidence=0.95,
                evidence=f"exam {index}",
            ),
            link_signals=build_link_signals(
                keywords=["exam"],
                exam_sequence=index,
                location_text=location,
            ),
        ),
    }


def _gmail_exam_record(
    *,
    message_id: str,
    title: str,
    due_at: datetime,
    dept: str,
    number: int,
    suffix: str | None,
    index: int | None,
    time_anchor_confidence: float = 0.9,
) -> dict:
    return {
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id=message_id,
            title=title,
            due_at=due_at,
            time_anchor_confidence=time_anchor_confidence,
            from_header="Prof Alice <alice@ucsd.edu>",
            course_parse=build_course_parse(
                dept=dept,
                number=number,
                suffix=suffix,
                confidence=0.9,
                evidence=f"{dept}{number}{suffix or ''}",
            ),
            event_parts=build_event_parts(
                type="exam",
                index=index,
                confidence=0.9,
                evidence=f"exam {index}" if index is not None else "exam",
            ),
            link_signals=build_link_signals(
                keywords=["exam"],
                exam_sequence=index,
                instructor_hint="Prof Alice",
            ),
        ),
    }


def test_gmail_weak_course_links_to_ics_entity_without_overwrite(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 8, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-cal-1",
        records=[
            _calendar_exam_record(
                external_event_id="ics-cse151-exam1",
                title="CSE 151 exam 1",
                start_at=due_at,
                end_at=end_at,
                dept="CSE",
                number=151,
                suffix=None,
                index=1,
            )
        ],
    )
    first_apply = apply_ingest_result_idempotent(db_session, request_id="linker-cal-1")
    assert first_apply["changes_created"] == 1

    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    pending_rows = _approve_all_pending_changes(
        db_session,
        user_id=calendar_source.user_id,
        canonical_input_id=canonical_input_id,
    )
    seed_change = pending_rows[-1]

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-gmail-1",
        records=[
            _gmail_exam_record(
                message_id="gmail-cse151-exam1",
                title="CSE151 exam 1",
                due_at=due_at,
                dept="CSE",
                number=151,
                suffix=None,
                index=1,
            )
        ],
    )
    second_apply = apply_ingest_result_idempotent(db_session, request_id="linker-gmail-1")
    assert second_apply["changes_created"] == 0

    pending_count = db_session.scalar(
        select(func.count(Change.id)).where(Change.input_id == canonical_input_id, Change.review_status == ReviewStatus.PENDING)
    )
    assert int(pending_count or 0) == 0

    link_row = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151-exam1",
        )
    )
    assert link_row is not None
    assert link_row.entity_uid == seed_change.event_uid
    assert link_row.link_origin == EventLinkOrigin.AUTO

    entity = db_session.scalar(
        select(EventEntity).where(
            EventEntity.user_id == calendar_source.user_id,
            EventEntity.entity_uid == seed_change.event_uid,
        )
    )
    assert entity is not None
    course_best = entity.course_best_json if isinstance(entity.course_best_json, dict) else {}
    assert str(course_best.get("display_name") or "").startswith("CSE 151")


def test_non_ambiguous_prefix_course_auto_links_without_score_threshold(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 9, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-prefix-cal-1",
        records=[
            _calendar_exam_record(
                external_event_id="ics-cse151a-exam1",
                title="CSE 151A exam 1",
                start_at=due_at,
                end_at=end_at,
                dept="CSE",
                number=151,
                suffix="A",
                index=1,
            )
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-prefix-cal-1")
    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    _approve_all_pending_changes(
        db_session,
        user_id=calendar_source.user_id,
        canonical_input_id=canonical_input_id,
    )

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-prefix-gmail-1",
        records=[
            _gmail_exam_record(
                message_id="gmail-cse151-prefix-1",
                title="CSE151 exam 1 update",
                due_at=due_at,
                dept="CSE",
                number=151,
                suffix=None,
                index=1,
            )
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

    candidate = db_session.scalar(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == calendar_source.user_id,
            EventLinkCandidate.source_id == gmail_source.id,
            EventLinkCandidate.external_event_id == "gmail-cse151-prefix-1",
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    )
    assert candidate is not None
    assert isinstance(candidate.score_breakdown_json, dict)
    assert candidate.score_breakdown_json.get("rule_reason") == "suffix_required_missing"


def test_variant_ambiguous_course_without_suffix_stays_candidate(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 10, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-candidate-cal-1",
        records=[
            _calendar_exam_record(
                external_event_id="ics-cse151a-exam2",
                title="CSE 151A exam 2",
                start_at=due_at,
                end_at=end_at,
                dept="CSE",
                number=151,
                suffix="A",
                index=2,
                location="Center Hall 101",
            ),
            _calendar_exam_record(
                external_event_id="ics-cse151b-exam2",
                title="CSE 151B exam 2",
                start_at=due_at + timedelta(minutes=5),
                end_at=end_at + timedelta(minutes=5),
                dept="CSE",
                number=151,
                suffix="B",
                index=2,
                location="Center Hall 201",
            ),
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-candidate-cal-1")
    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    _approve_all_pending_changes(
        db_session,
        user_id=calendar_source.user_id,
        canonical_input_id=canonical_input_id,
    )

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-candidate-gmail-1",
        records=[
            _gmail_exam_record(
                message_id="gmail-cse151-candidate-1",
                title="CSE151 exam 2 reminder",
                due_at=due_at + timedelta(minutes=10),
                dept="CSE",
                number=151,
                suffix=None,
                index=2,
            )
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
    assert candidate.proposed_entity_uid is not None
    assert isinstance(candidate.score_breakdown_json, dict)
    assert candidate.score_breakdown_json.get("rule_reason") == "suffix_required_missing"
    assert sorted(candidate.score_breakdown_json.get("candidate_suffixes") or []) == ["a", "b"]

    link_row = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151-candidate-1",
        )
    )
    assert link_row is None


def test_variant_ambiguous_requires_exact_suffix_for_auto_link(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 12, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-ambiguous-cal-1",
        records=[
            _calendar_exam_record(
                external_event_id="ics-cse151a-variant",
                title="CSE 151A exam 1",
                start_at=due_at,
                end_at=end_at,
                dept="CSE",
                number=151,
                suffix="A",
                index=1,
            ),
            _calendar_exam_record(
                external_event_id="ics-cse151b-variant",
                title="CSE 151B exam 1",
                start_at=due_at + timedelta(minutes=1),
                end_at=end_at + timedelta(minutes=1),
                dept="CSE",
                number=151,
                suffix="B",
                index=1,
            ),
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-ambiguous-cal-1")
    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    _approve_all_pending_changes(
        db_session,
        user_id=calendar_source.user_id,
        canonical_input_id=canonical_input_id,
    )

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-ambiguous-gmail-mismatch",
        records=[
            _gmail_exam_record(
                message_id="gmail-cse151c-mismatch",
                title="CSE151C exam 1 reminder",
                due_at=due_at + timedelta(minutes=1),
                dept="CSE",
                number=151,
                suffix="C",
                index=1,
            )
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-ambiguous-gmail-mismatch")

    mismatch_link = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151c-mismatch",
        )
    )
    assert mismatch_link is None

    mismatch_candidate = db_session.scalar(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == calendar_source.user_id,
            EventLinkCandidate.source_id == gmail_source.id,
            EventLinkCandidate.external_event_id == "gmail-cse151c-mismatch",
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    )
    assert mismatch_candidate is not None
    assert isinstance(mismatch_candidate.score_breakdown_json, dict)
    assert mismatch_candidate.score_breakdown_json.get("rule_reason") == "suffix_mismatch"

    _seed_result(
        db_session,
        source=gmail_source,
        request_id="linker-ambiguous-gmail-exact",
        records=[
            _gmail_exam_record(
                message_id="gmail-cse151b-exact",
                title="CSE151B exam 1 reminder",
                due_at=due_at + timedelta(minutes=1),
                dept="CSE",
                number=151,
                suffix="B",
                index=1,
            )
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-ambiguous-gmail-exact")

    exact_link = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151b-exact",
        )
    )
    assert exact_link is not None

    target_entity = db_session.scalar(
        select(EventEntity).where(
            EventEntity.user_id == calendar_source.user_id,
            EventEntity.entity_uid == exact_link.entity_uid,
        )
    )
    assert target_entity is not None
    target_best = target_entity.course_best_json if isinstance(target_entity.course_best_json, dict) else {}
    assert str(target_best.get("display_name") or "").startswith("CSE 151B")


def test_blocked_pair_skips_candidate_creation(db_session: Session) -> None:
    calendar_source, gmail_source = _create_sources(db_session)
    due_at = datetime(2026, 3, 11, 20, 0, tzinfo=timezone.utc)
    end_at = due_at + timedelta(hours=1)

    _seed_result(
        db_session,
        source=calendar_source,
        request_id="linker-block-cal-1",
        records=[
            _calendar_exam_record(
                external_event_id="ics-cse151-exam3",
                title="CSE 151 exam 3",
                start_at=due_at,
                end_at=end_at,
                dept="CSE",
                number=151,
                suffix=None,
                index=3,
                location="WLH 2001",
            )
        ],
    )
    apply_ingest_result_idempotent(db_session, request_id="linker-block-cal-1")
    canonical_input_id = _canonical_input_id(db_session, user_id=calendar_source.user_id)
    pending_rows = _approve_all_pending_changes(
        db_session,
        user_id=calendar_source.user_id,
        canonical_input_id=canonical_input_id,
    )
    seed_change = pending_rows[-1]

    db_session.add(
        EventLinkBlock(
            user_id=calendar_source.user_id,
            source_id=gmail_source.id,
            external_event_id="gmail-cse151-blocked-1",
            blocked_entity_uid=seed_change.event_uid,
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
            _gmail_exam_record(
                message_id="gmail-cse151-blocked-1",
                title="CSE151 exam 3 reminder",
                due_at=due_at + timedelta(minutes=10),
                dept="CSE",
                number=151,
                suffix=None,
                index=3,
            )
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

    blocked_link = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == calendar_source.user_id,
            EventEntityLink.source_id == gmail_source.id,
            EventEntityLink.external_event_id == "gmail-cse151-blocked-1",
        )
    )
    assert blocked_link is None
