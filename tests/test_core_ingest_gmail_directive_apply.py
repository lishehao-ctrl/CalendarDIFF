from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select

from app.db.models.runtime import ConnectorResultStatus, IngestResult, IngestUnresolvedRecord
from app.db.models.input import IngestTriggerType, InputSource, InputSourceConfig, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import Change, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus, SourceEventObservation
from app.db.models.shared import CourseWorkItemLabelFamily, IntegrationOutbox, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key
from app.modules.runtime.apply.apply import apply_ingest_result_idempotent


def _create_user_source_and_family(db_session) -> tuple[User, InputSource, CourseWorkItemLabelFamily]:
    now = datetime.now(timezone.utc)
    user = User(
        email="directive-owner@example.com",
        notify_email="directive-owner@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key=f"directive-gmail-{user.id}",
        display_name="Directive Gmail",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    family = CourseWorkItemLabelFamily(
        user_id=user.id,
        course_dept="CSE",
        course_number=8,
        course_suffix="A",
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity=normalized_course_identity_key(
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
        ),
        canonical_label="Homework",
        normalized_canonical_label=normalize_label_token("Homework"),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(source)
    db_session.refresh(family)
    return user, source, family


def _seed_active_entity(
    db_session,
    *,
    user_id: int,
    family_id: int,
    entity_uid: str,
    ordinal: int,
    due_date: date,
) -> None:
    db_session.add(
        EventEntity(
            user_id=user_id,
            entity_uid=entity_uid,
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
            family_id=family_id,
            raw_type="Homework",
            event_name=f"HW{ordinal}",
            ordinal=ordinal,
            due_date=due_date,
            due_time=None,
            time_precision="date_only",
        )
    )


def _seed_ingest_result(
    db_session,
    *,
    source: InputSource,
    request_id: str,
    records: list[dict],
) -> None:
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


def _directive_record(*, message_id: str, external_event_id: str, selector: dict, mutation: dict) -> dict:
    return {
        "record_type": "gmail.directive.extracted",
        "payload": {
            "message_id": message_id,
            "source_facts": {
                "external_event_id": external_event_id,
                "source_title": "Directive Message",
                "source_summary": "Directive summary",
                "from_header": "staff@example.edu",
                "thread_id": "thr-1",
                "internal_date": "2026-03-01T09:00:00+00:00",
            },
            "segment_index": 0,
            "segment_anchor": "s0",
            "segment_snippet": "directive snippet",
            "directive": {
                "selector": selector,
                "mutation": mutation,
                "confidence": 0.91,
                "evidence": "directive evidence",
            },
        },
    }


def test_gmail_directive_move_weekday_with_ordinal_list_creates_due_changed(db_session) -> None:
    user, source, family = _create_user_source_and_family(db_session)
    _seed_active_entity(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-ord-1",
        ordinal=1,
        due_date=date(2026, 3, 9),  # Monday
    )
    _seed_active_entity(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-ord-2",
        ordinal=2,
        due_date=date(2026, 3, 9),
    )
    db_session.commit()

    records = [
        _directive_record(
            message_id="msg-dir-1",
            external_event_id="msg-dir-1#directive-seg-0",
            selector={
                "course_dept": "CSE",
                "course_number": 8,
                "course_suffix": "A",
                "course_quarter": "WI",
                "course_year2": 26,
                "family_hint": "Homework",
                "raw_type_hint": "Homework",
                "scope_mode": "ordinal_list",
                "ordinal_list": [1],
                "ordinal_range_start": None,
                "ordinal_range_end": None,
                "current_due_weekday": "monday",
                "applies_to_future_only": False,
            },
            mutation={"move_weekday": "friday", "set_due_date": None},
        )
    ]
    _seed_ingest_result(db_session, source=source, request_id="directive-apply-1", records=records)
    result = apply_ingest_result_idempotent(db_session, request_id="directive-apply-1")
    assert result["changes_created"] == 1

    changes = list(
        db_session.scalars(
            select(Change).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING).order_by(Change.id.asc())
        ).all()
    )
    assert len(changes) == 1
    row = changes[0]
    assert row.change_type == ChangeType.DUE_CHANGED
    assert row.entity_uid == "ent-ord-1"
    assert row.before_semantic_json["due_date"] == "2026-03-09"
    assert row.after_semantic_json["due_date"] == "2026-03-13"
    assert len(row.source_refs) == 1
    assert row.source_refs[0].external_event_id == "msg-dir-1#directive-seg-0"

    observation_count = int(
        db_session.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.source_id == source.id,
                SourceEventObservation.external_event_id == "msg-dir-1#directive-seg-0",
            )
        )
        or 0
    )
    assert observation_count == 0

    outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(IntegrationOutbox.event_type == "changes.pending.created")
        )
        or 0
    )
    assert outbox_count == 1


def test_gmail_directive_set_due_date_with_ordinal_range_creates_multiple_changes(db_session) -> None:
    user, source, family = _create_user_source_and_family(db_session)
    _seed_active_entity(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-range-1",
        ordinal=1,
        due_date=date(2026, 3, 10),
    )
    _seed_active_entity(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-range-2",
        ordinal=2,
        due_date=date(2026, 3, 11),
    )
    _seed_active_entity(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-range-3",
        ordinal=3,
        due_date=date(2026, 3, 12),
    )
    db_session.commit()

    records = [
        _directive_record(
            message_id="msg-dir-2",
            external_event_id="msg-dir-2#directive-seg-0",
            selector={
                "course_dept": "CSE",
                "course_number": 8,
                "course_suffix": "A",
                "course_quarter": "WI",
                "course_year2": 26,
                "family_hint": "Homework",
                "raw_type_hint": "Homework",
                "scope_mode": "ordinal_range",
                "ordinal_list": [],
                "ordinal_range_start": 2,
                "ordinal_range_end": 3,
                "current_due_weekday": None,
                "applies_to_future_only": False,
            },
            mutation={"move_weekday": None, "set_due_date": "2026-03-20"},
        )
    ]
    _seed_ingest_result(db_session, source=source, request_id="directive-apply-2", records=records)
    result = apply_ingest_result_idempotent(db_session, request_id="directive-apply-2")
    assert result["changes_created"] == 2

    rows = list(
        db_session.scalars(
            select(Change).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING).order_by(Change.entity_uid.asc())
        ).all()
    )
    assert len(rows) == 2
    assert {row.entity_uid for row in rows} == {"ent-range-2", "ent-range-3"}
    assert all(row.change_type == ChangeType.DUE_CHANGED for row in rows)
    assert all(row.after_semantic_json["due_date"] == "2026-03-20" for row in rows)


def test_gmail_directive_no_match_is_isolated_without_pending_changes(db_session) -> None:
    user, source, family = _create_user_source_and_family(db_session)
    _seed_active_entity(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-isolate-1",
        ordinal=1,
        due_date=date(2026, 3, 9),
    )
    db_session.commit()

    records = [
        _directive_record(
            message_id="msg-dir-3",
            external_event_id="msg-dir-3#directive-seg-0",
            selector={
                "course_dept": "CSE",
                "course_number": 8,
                "course_suffix": "A",
                "course_quarter": "WI",
                "course_year2": 26,
                "family_hint": "Homework",
                "raw_type_hint": "Homework",
                "scope_mode": "ordinal_list",
                "ordinal_list": [99],
                "ordinal_range_start": None,
                "ordinal_range_end": None,
                "current_due_weekday": None,
                "applies_to_future_only": False,
            },
            mutation={"move_weekday": "friday", "set_due_date": None},
        )
    ]
    _seed_ingest_result(db_session, source=source, request_id="directive-apply-3", records=records)
    result = apply_ingest_result_idempotent(db_session, request_id="directive-apply-3")
    assert result["changes_created"] == 0

    pending_count = int(
        db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING)) or 0
    )
    assert pending_count == 0

    unresolved = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.user_id == user.id,
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-dir-3#directive-seg-0",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    assert unresolved is not None
    assert unresolved.reason_code == "directive_no_match"


def test_gmail_directive_lab_change_is_isolated_as_product_scope_excluded(db_session) -> None:
    user, source, family = _create_user_source_and_family(db_session)
    _seed_active_entity(
        db_session,
        user_id=user.id,
        family_id=family.id,
        entity_uid="ent-scope-ignore",
        ordinal=1,
        due_date=date(2026, 3, 9),
    )
    db_session.commit()

    records = [
        _directive_record(
            message_id="msg-dir-lab",
            external_event_id="msg-dir-lab#directive-seg-0",
            selector={
                "course_dept": "CSE",
                "course_number": 8,
                "course_suffix": "A",
                "course_quarter": "WI",
                "course_year2": 26,
                "family_hint": "Lab",
                "raw_type_hint": "Lab",
                "scope_mode": "all_matching",
                "ordinal_list": [],
                "ordinal_range_start": None,
                "ordinal_range_end": None,
                "current_due_weekday": None,
                "applies_to_future_only": False,
            },
            mutation={"move_weekday": "friday", "set_due_date": None},
        )
    ]
    _seed_ingest_result(db_session, source=source, request_id="directive-apply-scope", records=records)
    result = apply_ingest_result_idempotent(db_session, request_id="directive-apply-scope")
    assert result["changes_created"] == 0

    pending_count = int(
        db_session.scalar(select(func.count(Change.id)).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING)) or 0
    )
    assert pending_count == 0

    unresolved = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.user_id == user.id,
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-dir-lab#directive-seg-0",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    assert unresolved is not None
    assert unresolved.reason_code == "directive_product_scope_excluded"

