from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import func, select

from app.core.security import encrypt_secret
from app.db.models.runtime import ConnectorResultStatus, IngestResult
from app.db.models.input import (
    IngestTriggerType,
    InputSource,
    InputSourceConfig,
    InputSourceCursor,
    InputSourceSecret,
    SourceKind,
    SyncRequest,
    SyncRequestStatus,
)
from app.db.models.review import (
    Change,
    ChangeOrigin,
    ChangeSourceRef,
    ChangeType,
    EventEntity,
    EventEntityLifecycle,
    ReviewStatus,
    SourceEventObservation,
)
from app.db.models.shared import CourseWorkItemLabelFamily, IntegrationOutbox, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key
from app.modules.runtime.apply.apply import apply_ingest_result_idempotent
from app.modules.sources.schemas import InputSourcePatchRequest
from app.modules.sources.source_monitoring_window_rebind import PENDING_MONITORING_WINDOW_UPDATE_KEY
from app.modules.sources.sources_service import update_input_source
from tests.support.payload_builders import build_course_parse, build_event_parts, build_gmail_payload, build_link_signals


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        notify_email=email,
        timezone_name="America/Los_Angeles",
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
    is_active: bool = True,
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
        is_active=is_active,
        poll_interval_seconds=900,
        next_poll_at=now if is_active else None,
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


def _seed_sync_request(
    db_session,
    *,
    source: InputSource,
    request_id: str,
    status: SyncRequestStatus,
) -> None:
    db_session.add(
        SyncRequest(
            request_id=request_id,
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=status,
            idempotency_key=f"idemp:{request_id}",
            metadata_json={"kind": "test"},
        )
    )
    db_session.flush()


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
    source_title: str = "HW1",
    course_dept: str = "CSE",
    course_number: int = 120,
    course_suffix: str | None = None,
    course_quarter: str = "WI",
    course_year2: int = 26,
    family_id: int,
    family_name: str,
    raw_type: str = "Homework",
    ordinal: int = 1,
    confidence: float = 0.9,
) -> dict:
    return {
        "source_facts": {
            "external_event_id": external_event_id,
            "source_title": source_title,
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
            "event_name": source_title,
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


def _seed_pending_change(
    db_session,
    *,
    user_id: int,
    entity_uid: str,
    before_due_date: str,
    after_due_date: str,
    source_refs: list[tuple[InputSource, str]],
) -> Change:
    change = Change(
        user_id=user_id,
        entity_uid=entity_uid,
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": entity_uid,
            "event_name": "HW1",
            "due_date": before_due_date,
            "time_precision": "date_only",
        },
        after_semantic_json={
            "uid": entity_uid,
            "event_name": "HW1",
            "due_date": after_due_date,
            "time_precision": "date_only",
            "confidence": 0.9,
        },
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(change)
    db_session.flush()
    for position, (source, external_event_id) in enumerate(source_refs):
        db_session.add(
            ChangeSourceRef(
                change_id=change.id,
                position=position,
                source_id=source.id,
                source_kind=source.source_kind,
                provider=source.provider,
                external_event_id=external_event_id,
                confidence=0.9,
            )
        )
    return change


def test_sources_api_runtime_state_matrix_is_consistent_and_source_specific(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="runtime-state-matrix@example.com")
    current_window = {"monitor_since": "2026-01-05"}

    active_idle = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="runtime-active-idle",
        display_name="Runtime Active Idle",
        config_json=current_window,
        cursor_json={},
    )
    active_queued = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="runtime-queued",
        source_key="runtime-active-queued",
        display_name="Runtime Active Queued",
        config_json=current_window,
    )
    active_running = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="runtime-running",
        source_key="runtime-active-running",
        display_name="Runtime Active Running",
        config_json=current_window,
    )
    active_rebind = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="runtime-rebind",
        source_key="runtime-active-rebind",
        display_name="Runtime Active Rebind",
        config_json={
            **current_window,
            PENDING_MONITORING_WINDOW_UPDATE_KEY: {
                "monitor_since": "2026-03-25",
                "requested_config": {"monitor_since": "2026-03-25"},
                "requested_at": "2026-03-14T10:00:00+00:00",
            },
        },
    )
    inactive_idle = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="runtime-inactive",
        source_key="runtime-inactive-idle",
        display_name="Runtime Inactive Idle",
        is_active=False,
        config_json=current_window,
    )

    _seed_sync_request(db_session, source=active_queued, request_id="runtime-queued-1", status=SyncRequestStatus.PENDING)
    _seed_sync_request(db_session, source=active_running, request_id="runtime-running-1", status=SyncRequestStatus.RUNNING)
    _seed_sync_request(db_session, source=active_rebind, request_id="runtime-rebind-1", status=SyncRequestStatus.RUNNING)
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.get("/sources?status=all", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    rows = {row["source_id"]: row for row in response.json()}
    assert rows[active_idle.id]["lifecycle_state"] == "active"
    assert rows[active_idle.id]["sync_state"] == "idle"
    assert rows[active_idle.id]["config_state"] == "stable"
    assert rows[active_idle.id]["runtime_state"] == "active"

    assert rows[active_queued.id]["lifecycle_state"] == "active"
    assert rows[active_queued.id]["sync_state"] == "queued"
    assert rows[active_queued.id]["config_state"] == "stable"
    assert rows[active_queued.id]["runtime_state"] == "queued"

    assert rows[active_running.id]["lifecycle_state"] == "active"
    assert rows[active_running.id]["sync_state"] == "running"
    assert rows[active_running.id]["config_state"] == "stable"
    assert rows[active_running.id]["runtime_state"] == "running"

    assert rows[active_rebind.id]["lifecycle_state"] == "active"
    assert rows[active_rebind.id]["sync_state"] == "running"
    assert rows[active_rebind.id]["config_state"] == "rebind_pending"
    assert rows[active_rebind.id]["runtime_state"] == "rebind_pending"
    assert rows[active_rebind.id]["config"][PENDING_MONITORING_WINDOW_UPDATE_KEY]["monitor_since"] == "2026-03-25"

    assert rows[inactive_idle.id]["lifecycle_state"] == "inactive"
    assert rows[inactive_idle.id]["sync_state"] == "idle"
    assert rows[inactive_idle.id]["config_state"] == "stable"
    assert rows[inactive_idle.id]["runtime_state"] == "inactive"

    assert rows[active_idle.id]["sync_state"] == "idle"


def test_idempotent_canonical_edit_sets_manual_support_true(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="canonical-idempotent-manual@example.com")
    family = _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=8,
        suffix="A",
        canonical_label="Homework",
    )
    _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="canonical-idempotent-source",
        display_name="Canonical Edit Source",
        config_json={"monitor_since": "2026-01-05"},
        secrets_payload={"url": "https://example.com/canonical.ics"},
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="canonical-idempotent-1",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=8,
            course_suffix="A",
            family_id=family.id,
            manual_support=False,
            raw_type="Homework",
            event_name="HW2",
            ordinal=2,
            due_date=date(2026, 3, 10),
            due_time=None,
            time_precision="date_only",
        )
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.post(
        "/changes/edits",
        headers=headers,
        json={
            "mode": "canonical",
            "target": {"entity_uid": "canonical-idempotent-1"},
            "patch": {"event_name": "HW2", "due_date": "2026-03-10"},
            "reason": "idempotent manual support set",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["applied"] is True
    assert payload["idempotent"] is True
    assert payload["canonical_edit_change_id"] is None

    db_session.expire_all()
    entity = db_session.scalar(
        select(EventEntity).where(EventEntity.user_id == user.id, EventEntity.entity_uid == "canonical-idempotent-1")
    )
    audit_change = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == "canonical-idempotent-1",
            Change.change_origin == ChangeOrigin.MANUAL_CANONICAL_EDIT,
        )
    )
    assert entity is not None
    assert entity.manual_support is True
    assert audit_change is None


def test_automatic_ingest_apply_does_not_set_manual_support(db_session) -> None:
    user = _create_user(db_session, email="ingest-manual-support-guard@example.com")
    source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="ingest-manual-support-guard",
        display_name="Ingest Manual Support Guard",
        config_json={"monitor_since": "2026-01-05"},
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
    entity = EventEntity(
        user_id=user.id,
        entity_uid="entity-auto-manual-support-1",
        lifecycle=EventEntityLifecycle.ACTIVE,
        course_dept="CSE",
        course_number=120,
        course_quarter="WI",
        course_year2=26,
        family_id=family.id,
        manual_support=False,
        raw_type="Homework",
        event_name="HW1",
        ordinal=1,
        due_date=date(2026, 3, 1),
        due_time=None,
        time_precision="date_only",
    )
    db_session.add(entity)
    db_session.flush()
    db_session.commit()

    record = {
        "record_type": "gmail.message.extracted",
        "payload": build_gmail_payload(
            message_id="msg-auto-manual-1",
            title="CSE 120 HW1 deadline",
            due_at=datetime(2026, 3, 5, 23, 59, tzinfo=timezone.utc),
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
    _seed_ingest_result(db_session, source=source, request_id="auto-manual-support-1", records=[record])
    result = apply_ingest_result_idempotent(db_session, request_id="auto-manual-support-1")

    db_session.expire_all()
    refreshed_entity = db_session.scalar(select(EventEntity).where(EventEntity.id == entity.id))
    pending_change = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == entity.entity_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
    )
    outbox_count = int(
        db_session.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "changes.pending.created",
                IntegrationOutbox.aggregate_type == "change_batch",
            )
        )
        or 0
    )

    assert result["changes_created"] == 1
    assert refreshed_entity is not None
    assert refreshed_entity.manual_support is False
    assert pending_change is not None
    assert pending_change.change_type == ChangeType.DUE_CHANGED
    assert outbox_count == 1


def test_gmail_rescope_preserves_manual_supported_entity_without_remaining_sources(db_session) -> None:
    user = _create_user(db_session, email="manual-gmail-rescope@example.com")
    source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="manual-gmail-rescope",
        display_name="Manual Gmail Rescope",
        config_json={"monitor_since": "2026-01-05"},
        secrets_payload={"access_token": "token"},
        cursor_json={"history_id": "222"},
    )
    family = _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=120,
        quarter="WI",
        year2=26,
    )
    entity = EventEntity(
        user_id=user.id,
        entity_uid="entity-manual-gmail-1",
        lifecycle=EventEntityLifecycle.ACTIVE,
        course_dept="CSE",
        course_number=120,
        course_quarter="WI",
        course_year2=26,
        family_id=family.id,
        manual_support=True,
        raw_type="Homework",
        event_name="HW1",
        ordinal=1,
        due_date=date(2026, 3, 5),
        due_time=None,
        time_precision="date_only",
    )
    db_session.add(entity)
    db_session.flush()
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="msg-manual-gmail-1",
            entity_uid=entity.entity_uid,
            event_payload=_runtime_observation_payload(
                entity_uid=entity.entity_uid,
                external_event_id="msg-manual-gmail-1",
                due_date="2026-03-08",
                family_id=family.id,
                family_name=family.canonical_label,
            ),
            event_hash="hash-manual-gmail-1",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-manual-gmail-1",
        )
    )
    db_session.commit()

    update_input_source(
        db_session,
        source=source,
        payload=InputSourcePatchRequest(
            config={"monitor_since": "2099-04-01"},
        ),
    )
    db_session.expire_all()

    refreshed_entity = db_session.scalar(select(EventEntity).where(EventEntity.id == entity.id))
    pending_removed = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == entity.entity_uid,
            Change.review_status == ReviewStatus.PENDING,
            Change.change_type == ChangeType.REMOVED,
        )
    )
    active_observation = db_session.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.entity_uid == entity.entity_uid,
            SourceEventObservation.is_active.is_(True),
        )
    )

    assert refreshed_entity is not None
    assert refreshed_entity.lifecycle == EventEntityLifecycle.ACTIVE
    assert refreshed_entity.manual_support is True
    assert pending_removed is None
    assert active_observation is None


def test_manual_supported_entity_rescope_with_remaining_matching_source_rejects_stale_pending_change(db_session) -> None:
    user = _create_user(db_session, email="manual-matching-rescope@example.com")
    calendar_source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="manual-match-calendar",
        display_name="Manual Match Calendar",
        config_json={"monitor_since": "2026-01-05"},
        secrets_payload={"url": "https://example.com/calendar.ics"},
        cursor_json={"etag": "etag-1"},
    )
    gmail_source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="manual-match-gmail",
        display_name="Manual Match Gmail",
        config_json={"monitor_since": "2026-01-05"},
        secrets_payload={"access_token": "token"},
        cursor_json={"history_id": "333"},
    )
    family = _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=120,
        quarter="WI",
        year2=26,
    )
    entity = EventEntity(
        user_id=user.id,
        entity_uid="entity-manual-match-1",
        lifecycle=EventEntityLifecycle.ACTIVE,
        course_dept="CSE",
        course_number=120,
        course_quarter="WI",
        course_year2=26,
        family_id=family.id,
        manual_support=True,
        raw_type="Homework",
        event_name="HW1",
        ordinal=1,
        due_date=date(2026, 3, 5),
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
            external_event_id="cal-manual-match-1",
            entity_uid=entity.entity_uid,
            event_payload=_runtime_observation_payload(
                entity_uid=entity.entity_uid,
                external_event_id="cal-manual-match-1",
                due_date="2026-03-10",
                family_id=family.id,
                family_name=family.canonical_label,
            ),
            event_hash="hash-cal-manual-match-1",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-cal-manual-match-1",
        )
    )
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=gmail_source.id,
            source_kind=gmail_source.source_kind,
            provider=gmail_source.provider,
            external_event_id="gmail-manual-match-1",
            entity_uid=entity.entity_uid,
            event_payload=_runtime_observation_payload(
                entity_uid=entity.entity_uid,
                external_event_id="gmail-manual-match-1",
                due_date="2026-03-05",
                family_id=family.id,
                family_name=family.canonical_label,
            ),
            event_hash="hash-gmail-manual-match-1",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-gmail-manual-match-1",
        )
    )
    stale_change = _seed_pending_change(
        db_session,
        user_id=user.id,
        entity_uid=entity.entity_uid,
        before_due_date="2026-03-05",
        after_due_date="2026-03-10",
        source_refs=[
            (calendar_source, "cal-manual-match-1"),
            (gmail_source, "gmail-manual-match-1"),
        ],
    )
    db_session.commit()

    update_input_source(
        db_session,
        source=calendar_source,
        payload=InputSourcePatchRequest(
            config={"monitor_since": "2099-04-01"},
        ),
    )
    db_session.expire_all()

    refreshed_entity = db_session.scalar(select(EventEntity).where(EventEntity.id == entity.id))
    pending_change = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == entity.entity_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
    )
    rejected_change = db_session.scalar(select(Change).where(Change.id == stale_change.id))

    assert refreshed_entity is not None
    assert refreshed_entity.lifecycle == EventEntityLifecycle.ACTIVE
    assert refreshed_entity.manual_support is True
    assert pending_change is None
    assert rejected_change is not None
    assert rejected_change.review_status == ReviewStatus.REJECTED
    assert rejected_change.review_note == "proposal_already_matches_approved_entity_state"


def test_manual_supported_entity_rescope_with_remaining_conflicting_source_keeps_normal_pending_change(db_session) -> None:
    user = _create_user(db_session, email="manual-conflict-rescope@example.com")
    calendar_source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="manual-conflict-calendar",
        display_name="Manual Conflict Calendar",
        config_json={"monitor_since": "2026-01-05"},
        secrets_payload={"url": "https://example.com/calendar.ics"},
        cursor_json={"etag": "etag-2"},
    )
    gmail_source = _create_source(
        db_session,
        user=user,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="manual-conflict-gmail",
        display_name="Manual Conflict Gmail",
        config_json={"monitor_since": "2026-01-05"},
        secrets_payload={"access_token": "token"},
        cursor_json={"history_id": "444"},
    )
    family = _create_family(
        db_session,
        user=user,
        dept="CSE",
        number=120,
        quarter="WI",
        year2=26,
    )
    entity = EventEntity(
        user_id=user.id,
        entity_uid="entity-manual-conflict-1",
        lifecycle=EventEntityLifecycle.ACTIVE,
        course_dept="CSE",
        course_number=120,
        course_quarter="WI",
        course_year2=26,
        family_id=family.id,
        manual_support=True,
        raw_type="Homework",
        event_name="HW1",
        ordinal=1,
        due_date=date(2026, 3, 5),
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
            external_event_id="cal-manual-conflict-1",
            entity_uid=entity.entity_uid,
            event_payload=_runtime_observation_payload(
                entity_uid=entity.entity_uid,
                external_event_id="cal-manual-conflict-1",
                due_date="2026-03-10",
                family_id=family.id,
                family_name=family.canonical_label,
            ),
            event_hash="hash-cal-manual-conflict-1",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-cal-manual-conflict-1",
        )
    )
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=gmail_source.id,
            source_kind=gmail_source.source_kind,
            provider=gmail_source.provider,
            external_event_id="gmail-manual-conflict-1",
            entity_uid=entity.entity_uid,
            event_payload=_runtime_observation_payload(
                entity_uid=entity.entity_uid,
                external_event_id="gmail-manual-conflict-1",
                due_date="2026-03-08",
                family_id=family.id,
                family_name=family.canonical_label,
            ),
            event_hash="hash-gmail-manual-conflict-1",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="req-gmail-manual-conflict-1",
        )
    )
    _seed_pending_change(
        db_session,
        user_id=user.id,
        entity_uid=entity.entity_uid,
        before_due_date="2026-03-05",
        after_due_date="2026-03-10",
        source_refs=[
            (calendar_source, "cal-manual-conflict-1"),
            (gmail_source, "gmail-manual-conflict-1"),
        ],
    )
    db_session.commit()

    update_input_source(
        db_session,
        source=calendar_source,
        payload=InputSourcePatchRequest(
            config={"monitor_since": "2099-04-01"},
        ),
    )
    db_session.expire_all()

    refreshed_entity = db_session.scalar(select(EventEntity).where(EventEntity.id == entity.id))
    pending_change = db_session.scalar(
        select(Change).where(
            Change.user_id == user.id,
            Change.entity_uid == entity.entity_uid,
            Change.review_status == ReviewStatus.PENDING,
        )
    )

    assert refreshed_entity is not None
    assert refreshed_entity.lifecycle == EventEntityLifecycle.ACTIVE
    assert refreshed_entity.manual_support is True
    assert pending_change is not None
    assert pending_change.change_type == ChangeType.DUE_CHANGED
    assert pending_change.after_semantic_json["due_date"] == "2026-03-08"
    assert [row.source_id for row in pending_change.source_refs] == [gmail_source.id]
