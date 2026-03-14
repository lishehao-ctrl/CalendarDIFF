from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from app.core.security import encrypt_secret
from app.db.models.ingestion import ConnectorResultStatus, IngestResult, IngestUnresolvedRecord
from app.db.models.input import IngestTriggerType, InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind, SyncRequest, SyncRequestStatus
from app.db.models.review import (
    Change,
    ChangeOrigin,
    ChangeSourceRef,
    ChangeType,
    EventEntity,
    EventEntityLifecycle,
    EventEntityLink,
    EventLinkOrigin,
    ReviewStatus,
    SourceEventObservation,
)
from app.db.models.shared import CourseWorkItemLabelFamily, IntegrationOutbox, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key
from app.modules.core_ingest.apply import apply_ingest_result_idempotent
from app.modules.ingestion.calendar_fetcher import fetch_calendar_delta
from app.modules.ingestion.gmail_fetcher import fetch_gmail_changes
from app.modules.input_control_plane.schemas import InputSourcePatchRequest
from app.modules.input_control_plane.sources_service import update_input_source
from tests.support.payload_builders import build_course_parse, build_event_parts, build_gmail_payload, build_link_signals


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        notify_email=email,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    return user


def _create_source(
    db_session,
    *,
    user: User,
    source_kind: SourceKind,
    provider: str,
    source_key: str,
    display_name: str,
    config_json: dict | None = None,
    secrets_payload: dict | None = None,
    cursor_json: dict | None = None,
) -> InputSource:
    now = datetime.now(timezone.utc)
    source = InputSource(
        user_id=user.id,
        source_kind=source_kind,
        provider=provider,
        source_key=source_key,
        display_name=display_name,
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json=config_json or {}))
    if secrets_payload is not None:
        db_session.add(
            InputSourceSecret(
                source_id=source.id,
                encrypted_payload=encrypt_secret(json.dumps(secrets_payload)),
            )
        )
    if cursor_json is not None:
        db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json=cursor_json))
    return source


def _create_family(
    db_session,
    *,
    user: User,
    dept: str,
    number: int,
    suffix: str | None = None,
    quarter: str | None = None,
    year2: int | None = None,
    canonical_label: str = "Homework",
) -> CourseWorkItemLabelFamily:
    family = CourseWorkItemLabelFamily(
        user_id=user.id,
        course_dept=dept,
        course_number=number,
        course_suffix=suffix,
        course_quarter=quarter,
        course_year2=year2,
        normalized_course_identity=normalized_course_identity_key(
            course_dept=dept,
            course_number=number,
            course_suffix=suffix,
            course_quarter=quarter,
            course_year2=year2,
        ),
        canonical_label=canonical_label,
        normalized_canonical_label=normalize_label_token(canonical_label),
    )
    db_session.add(family)
    db_session.flush()
    return family


def _seed_manual_link(
    db_session,
    *,
    user_id: int,
    source_id: int,
    external_event_id: str,
    entity_uid: str,
) -> None:
    db_session.add(
        EventEntityLink(
            user_id=user_id,
            source_id=source_id,
            source_kind=SourceKind.EMAIL,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            link_origin=EventLinkOrigin.MANUAL_CANDIDATE,
            link_score=1.0,
            signals_json={"seed": "term_edgecase_exploration"},
        )
    )


def _seed_ingest_result(db_session, *, source: InputSource, request_id: str, records: list[dict]) -> None:
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


def _runtime_observation_payload(
    *,
    entity_uid: str,
    external_event_id: str,
    due_date: str,
    confidence: float = 0.9,
    course_dept: str = "CSE",
    course_number: int = 120,
    course_suffix: str | None = None,
    course_quarter: str = "WI",
    course_year2: int = 26,
    family_id: int = 101,
    family_name: str = "Homework",
    raw_type: str = "Homework",
    event_name: str | None = None,
    ordinal: int = 1,
) -> dict:
    resolved_event_name = event_name or entity_uid
    return {
        "source_facts": {
            "external_event_id": external_event_id,
            "source_title": resolved_event_name,
            "source_dtstart_utc": f"{due_date}T23:59:00+00:00",
        },
        "semantic_event": {
            "uid": entity_uid,
            "course_dept": course_dept,
            "course_number": course_number,
            "course_suffix": course_suffix,
            "course_quarter": course_quarter,
            "course_year2": course_year2,
            "family_id": family_id,
            "family_name": family_name,
            "raw_type": raw_type,
            "event_name": resolved_event_name,
            "ordinal": ordinal,
            "due_date": due_date,
            "time_precision": "date_only",
            "confidence": confidence,
        },
        "link_signals": {},
        "kind_resolution": {
            "status": "resolved",
            "family_id": family_id,
            "canonical_label": family_name,
            "raw_type": raw_type,
        },
    }


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


def test_gmail_fetcher_boundary_midnight_uses_source_timezone(monkeypatch) -> None:
    source = SimpleNamespace(
        config=SimpleNamespace(
            config_json={
                "label_id": "COURSE",
                "term_key": "WI26",
                "term_from": "2026-01-05",
                "term_to": "2026-03-20",
            }
        ),
        cursor=SimpleNamespace(cursor_json={}),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )

    class _FakeGmailClient:
        def get_profile(self, *, access_token: str):
            assert access_token == "token"
            return SimpleNamespace(email_address="student@example.edu", history_id="200")

        def list_message_ids(self, *, access_token: str, query: str | None = None, label_ids=None):
            assert access_token == "token"
            assert query == "after:2025/12/06 before:2026/04/20"
            assert label_ids == ["COURSE"]
            return ["before-bootstrap", "at-bootstrap", "at-monitor-end", "after-monitor-end"]

        def get_message_metadata(self, *, access_token: str, message_id: str):
            assert access_token == "token"
            internal_date = {
                "before-bootstrap": "2025-12-06T07:59:59+00:00",
                "at-bootstrap": "2025-12-06T08:00:00+00:00",
                "at-monitor-end": "2026-04-20T06:59:59+00:00",
                "after-monitor-end": "2026-04-20T07:00:00+00:00",
            }[message_id]
            return SimpleNamespace(
                message_id=message_id,
                thread_id=f"thread-{message_id}",
                snippet=f"snippet-{message_id}",
                body_text=f"body-{message_id}",
                from_header="professor@school.edu",
                subject="Homework reminder",
                internal_date=internal_date,
                label_ids=["COURSE"],
            )

    monkeypatch.setattr("app.modules.ingestion.gmail_fetcher.decode_source_secrets", lambda _source: {"access_token": "token"})
    monkeypatch.setattr("app.modules.ingestion.gmail_fetcher.GmailClient", _FakeGmailClient)

    outcome = fetch_gmail_changes(source=source, request_id="req-boundary")

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.parse_payload is not None
    assert [row["message_id"] for row in outcome.parse_payload["messages"]] == ["at-bootstrap", "at-monitor-end"]


def test_calendar_fetcher_recurrence_filters_out_of_term_instances_and_keeps_removed_keys(monkeypatch) -> None:
    source = SimpleNamespace(
        id=100,
        config=SimpleNamespace(
            config_json={
                "term_key": "WI26",
                "term_from": "2026-01-05",
                "term_to": "2026-03-20",
            }
        ),
        cursor=SimpleNamespace(
            cursor_json={
                "ics_component_fingerprints": {
                    "series#20260310T100000Z": "fp-removed",
                }
            }
        ),
        user=SimpleNamespace(timezone_name="America/Los_Angeles"),
    )

    class _FakeFetched:
        not_modified = False
        etag = "etag-1"
        last_modified = "Mon, 01 Jan 2026 00:00:00 GMT"

        def __init__(self, content: bytes):
            self.content = content

    class _FakeIcsClient:
        def fetch(self, url: str, source_id: int, if_none_match=None, if_modified_since=None):
            assert url == "https://example.com/calendar.ics"
            assert source_id == 100
            del if_none_match, if_modified_since
            content = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:series
RECURRENCE-ID:20260315T100000Z
DTSTART:20260315T100000Z
DTEND:20260315T110000Z
SUMMARY:In term recurrence
END:VEVENT
BEGIN:VEVENT
UID:series
RECURRENCE-ID:20260405T100000Z
DTSTART:20260425T100000Z
DTEND:20260425T110000Z
SUMMARY:Out of term recurrence
END:VEVENT
END:VCALENDAR
"""
            return _FakeFetched(content)

    monkeypatch.setattr("app.modules.ingestion.calendar_fetcher.decode_source_secrets", lambda _source: {"url": "https://example.com/calendar.ics"})
    monkeypatch.setattr("app.modules.ingestion.calendar_fetcher.ICSClient", _FakeIcsClient)

    outcome = fetch_calendar_delta(source=source)

    assert outcome.status == ConnectorResultStatus.CHANGED
    assert outcome.parse_payload is not None
    assert [row["external_event_id"] for row in outcome.parse_payload["changed_components"]] == ["series#2026-03-15T10:00:00+00:00"]
    assert outcome.parse_payload["removed_component_keys"] == ["series#20260310T100000Z"]


def test_gmail_semantic_due_date_controls_term_gate_when_message_timestamp_disagrees(db_session) -> None:
    user = _create_user(db_session, email="gmail-semantic-gate@example.com")
    source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-semantic-gate-source",
        display_name="Semantic Gate Gmail",
        config_json={"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
        secrets_payload={"access_token": "token"},
        cursor_json={"history_id": "300"},
    )
    _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=120,
        quarter="WI",
        year2=26,
    )
    _seed_manual_link(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="msg-semantic-in",
        entity_uid="entity-semantic-in",
    )
    db_session.commit()

    out_of_term_record = {
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id="msg-semantic-out",
            title="CSE 120 HW9 deadline",
            due_at=datetime(2026, 5, 2, 23, 59, tzinfo=timezone.utc),
            internal_date="2026-03-10T18:00:00+00:00",
            course_parse=build_course_parse(
                dept="CSE",
                number=120,
                quarter="WI",
                year2=26,
                confidence=0.95,
                evidence="CSE 120",
            ),
            event_parts=build_event_parts(type="deadline", index=9, confidence=0.9, evidence="HW9"),
            link_signals=build_link_signals(),
        ),
    }
    _seed_ingest_result(db_session, source=source, request_id="gmail-semantic-out-1", records=[out_of_term_record])
    out_of_term_result = apply_ingest_result_idempotent(db_session, request_id="gmail-semantic-out-1")

    unresolved_out_of_term = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-semantic-out",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    assert out_of_term_result["changes_created"] == 0
    assert unresolved_out_of_term is not None
    assert unresolved_out_of_term.reason_code == "term_out_of_scope"

    in_term_record = {
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id="msg-semantic-in",
            title="CSE 120 HW1 deadline",
            due_at=datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc),
            internal_date="2026-04-02T18:00:00+00:00",
            course_parse=build_course_parse(
                dept="CSE",
                number=120,
                quarter="WI",
                year2=26,
                confidence=0.95,
                evidence="CSE 120",
            ),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.9, evidence="HW1"),
            link_signals=build_link_signals(),
        ),
    }
    _seed_ingest_result(db_session, source=source, request_id="gmail-semantic-in-1", records=[in_term_record])
    in_term_result = apply_ingest_result_idempotent(db_session, request_id="gmail-semantic-in-1")

    unresolved_in_term = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-semantic-in",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    pending_changes = list(
        db_session.scalars(
            select(Change).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING).order_by(Change.id.asc())
        ).all()
    )
    outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )

    assert in_term_result["changes_created"] == 1
    assert unresolved_in_term is None
    assert len(pending_changes) == 1
    assert pending_changes[0].entity_uid == "entity-semantic-in"
    assert outbox_count == 1


def test_repeated_identical_gmail_replay_does_not_duplicate_pending_change_or_outbox(db_session) -> None:
    user = _create_user(db_session, email="gmail-replay@example.com")
    source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="gmail-replay-source",
        display_name="Replay Gmail",
        config_json={"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
        secrets_payload={"access_token": "token"},
        cursor_json={"history_id": "200"},
    )
    _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=120,
        quarter="WI",
        year2=26,
    )
    _seed_manual_link(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="msg-replay-1",
        entity_uid="entity-replay-1",
    )
    db_session.commit()

    due_at = datetime(2026, 3, 4, 23, 59, tzinfo=timezone.utc)
    record = {
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id="msg-replay-1",
            title="CSE 120 HW1 deadline",
            due_at=due_at,
            internal_date="2026-03-01T18:00:00+00:00",
            course_parse=build_course_parse(
                dept="CSE",
                number=120,
                quarter="WI",
                year2=26,
                confidence=0.95,
                evidence="CSE 120",
            ),
            event_parts=build_event_parts(type="deadline", index=1, confidence=0.9, evidence="HW1"),
            link_signals=build_link_signals(),
        ),
    }

    _seed_ingest_result(db_session, source=source, request_id="gmail-replay-1", records=[record])
    first_apply = apply_ingest_result_idempotent(db_session, request_id="gmail-replay-1")
    assert first_apply["changes_created"] == 1

    _seed_ingest_result(db_session, source=source, request_id="gmail-replay-2", records=[record])
    second_apply = apply_ingest_result_idempotent(db_session, request_id="gmail-replay-2")
    assert second_apply["changes_created"] == 0

    pending_changes = list(
        db_session.scalars(
            select(Change).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING)
        ).all()
    )
    outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )
    observation_count = int(
        db_session.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.source_id == source.id,
                SourceEventObservation.external_event_id == "msg-replay-1",
                SourceEventObservation.is_active.is_(True),
            )
        )
        or 0
    )

    assert len(pending_changes) == 1
    assert outbox_count == 1
    assert observation_count == 1
    assert pending_changes[0].entity_uid == "entity-replay-1"


def test_calendar_rescope_rebuild_keeps_remaining_gmail_support(db_session) -> None:
    user = _create_user(db_session, email="shared-support@example.com")
    calendar_source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="canvas_ics",
        display_name="Canvas ICS",
        config_json={"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
        secrets_payload={"url": "https://example.com/calendar.ics"},
        cursor_json={"etag": "abc"},
    )
    gmail_source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="shared-gmail",
        display_name="Shared Gmail",
        config_json={"label_id": "INBOX", "term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
        secrets_payload={"access_token": "token"},
        cursor_json={"history_id": "111"},
    )
    family = _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=120,
        quarter="WI",
        year2=26,
    )
    db_session.flush()

    entity = EventEntity(
        user_id=user.id,
        entity_uid="entity-shared-1",
        lifecycle=EventEntityLifecycle.ACTIVE,
        course_dept="CSE",
        course_number=120,
        course_quarter="WI",
        course_year2=26,
        family_id=family.id,
        raw_type="Homework",
        event_name="HW1",
        ordinal=1,
        due_date=date(2026, 3, 1),
        due_time=None,
        time_precision="date_only",
    )
    db_session.add(entity)
    db_session.flush()

    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=calendar_source.id,
            source_kind=calendar_source.source_kind,
            provider=calendar_source.provider,
            external_event_id="cal-shared-1",
            entity_uid=entity.entity_uid,
            event_payload=_runtime_observation_payload(
                entity_uid=entity.entity_uid,
                external_event_id="cal-shared-1",
                due_date="2026-03-05",
                family_id=family.id,
                family_name=family.canonical_label,
                event_name="HW1",
            ),
            event_hash="hash-cal-shared",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-cal-shared",
        )
    )
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=gmail_source.id,
            source_kind=gmail_source.source_kind,
            provider=gmail_source.provider,
            external_event_id="gmail-shared-1",
            entity_uid=entity.entity_uid,
            event_payload=_runtime_observation_payload(
                entity_uid=entity.entity_uid,
                external_event_id="gmail-shared-1",
                due_date="2026-03-05",
                family_id=family.id,
                family_name=family.canonical_label,
                event_name="HW1",
            ),
            event_hash="hash-gmail-shared",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-gmail-shared",
        )
    )
    change = Change(
        user_id=user.id,
        entity_uid=entity.entity_uid,
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": entity.entity_uid,
            "event_name": "HW1",
            "due_date": "2026-03-01",
            "time_precision": "date_only",
        },
        after_semantic_json={
            "uid": entity.entity_uid,
            "event_name": "HW1",
            "due_date": "2026-03-05",
            "time_precision": "date_only",
            "confidence": 0.9,
        },
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(change)
    db_session.flush()
    db_session.add(
        ChangeSourceRef(
            change_id=change.id,
            position=0,
            source_id=calendar_source.id,
            source_kind=calendar_source.source_kind,
            provider=calendar_source.provider,
            external_event_id="cal-shared-1",
            confidence=0.9,
        )
    )
    db_session.add(
        ChangeSourceRef(
            change_id=change.id,
            position=1,
            source_id=gmail_source.id,
            source_kind=gmail_source.source_kind,
            provider=gmail_source.provider,
            external_event_id="gmail-shared-1",
            confidence=0.9,
        )
    )
    db_session.commit()

    update_input_source(
        db_session,
        source=calendar_source,
        payload=InputSourcePatchRequest(
            config={"term_key": "SP99", "term_from": "2099-04-01", "term_to": "2099-06-01"},
        ),
    )
    db_session.expire_all()

    refreshed_change = db_session.scalar(select(Change).where(Change.id == change.id))
    assert refreshed_change is not None
    assert refreshed_change.review_status == ReviewStatus.PENDING
    assert [row.source_id for row in refreshed_change.source_refs] == [gmail_source.id]
    assert db_session.scalar(
        select(SourceEventObservation).where(SourceEventObservation.source_id == calendar_source.id)
    ) is None
    gmail_observation = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == gmail_source.id,
            SourceEventObservation.entity_uid == entity.entity_uid,
            SourceEventObservation.is_active.is_(True),
        )
    )
    assert gmail_observation is not None
    refreshed_entity = db_session.scalar(select(EventEntity).where(EventEntity.entity_uid == entity.entity_uid))
    assert refreshed_entity is not None
    assert refreshed_entity.lifecycle == EventEntityLifecycle.ACTIVE


def test_gmail_directive_partial_apply_isolates_out_of_scope_matches(db_session) -> None:
    user = _create_user(db_session, email="directive-partial@example.com")
    source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="directive-gmail",
        display_name="Directive Gmail",
        config_json={"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
    )
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
    db_session.flush()
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent-in",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            raw_type="Homework",
            event_name="HW1",
            ordinal=1,
            due_date=date(2026, 3, 10),
            due_time=None,
            time_precision="date_only",
        )
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent-out",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            raw_type="Homework",
            event_name="HW2",
            ordinal=2,
            due_date=date(2026, 5, 5),
            due_time=None,
            time_precision="date_only",
        )
    )
    db_session.commit()

    records = [
        _directive_record(
            message_id="msg-dir-mixed",
            external_event_id="msg-dir-mixed#directive-seg-0",
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
                "ordinal_range_start": 1,
                "ordinal_range_end": 2,
                "current_due_weekday": None,
                "applies_to_future_only": False,
            },
            mutation={"move_weekday": None, "set_due_date": "2026-03-14"},
        )
    ]
    _seed_ingest_result(db_session, source=source, request_id="directive-partial-1", records=records)
    result = apply_ingest_result_idempotent(db_session, request_id="directive-partial-1")

    unresolved = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-dir-mixed#directive-seg-0#directive:term_out_of_scope",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    pending_changes = list(
        db_session.scalars(
            select(Change).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING).order_by(Change.id.asc())
        ).all()
    )
    outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )

    assert result["changes_created"] == 1
    assert len(pending_changes) == 1
    assert pending_changes[0].entity_uid == "ent-in"
    assert unresolved is not None
    assert unresolved.reason_code == "directive_term_out_of_scope_partial"
    assert outbox_count == 1


def test_gmail_directive_partial_apply_isolates_noop_matches(db_session) -> None:
    user = _create_user(db_session, email="directive-partial-noop@example.com")
    source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="directive-gmail-noop",
        display_name="Directive Gmail Noop",
        config_json={"term_key": "WI26", "term_from": "2026-01-05", "term_to": "2026-03-20"},
    )
    family = _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=8,
        suffix="A",
        quarter="WI",
        year2=26,
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent-change",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            raw_type="Homework",
            event_name="HW1",
            ordinal=1,
            due_date=date(2026, 3, 10),
            due_time=None,
            time_precision="date_only",
        )
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent-noop",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            raw_type="Homework",
            event_name="HW2",
            ordinal=2,
            due_date=date(2026, 3, 14),
            due_time=None,
            time_precision="date_only",
        )
    )
    db_session.commit()

    records = [
        _directive_record(
            message_id="msg-dir-noop",
            external_event_id="msg-dir-noop#directive-seg-0",
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
                "ordinal_range_start": 1,
                "ordinal_range_end": 2,
                "current_due_weekday": None,
                "applies_to_future_only": False,
            },
            mutation={"move_weekday": None, "set_due_date": "2026-03-14"},
        )
    ]
    _seed_ingest_result(db_session, source=source, request_id="directive-partial-noop-1", records=records)
    result = apply_ingest_result_idempotent(db_session, request_id="directive-partial-noop-1")

    unresolved = db_session.scalar(
        select(IngestUnresolvedRecord).where(
            IngestUnresolvedRecord.source_id == source.id,
            IngestUnresolvedRecord.external_event_id == "msg-dir-noop#directive-seg-0",
            IngestUnresolvedRecord.is_active.is_(True),
        )
    )
    pending_changes = list(
        db_session.scalars(
            select(Change).where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING).order_by(Change.id.asc())
        ).all()
    )
    outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "review.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )

    assert result["changes_created"] == 1
    assert len(pending_changes) == 1
    assert pending_changes[0].entity_uid == "ent-change"
    assert unresolved is not None
    assert unresolved.reason_code == "directive_unsupported_or_no_effect"
    assert outbox_count == 1
