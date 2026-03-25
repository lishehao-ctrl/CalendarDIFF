from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import (
    Change,
    ChangeIntakePhase,
    ChangeOrigin,
    ChangeReviewBucket,
    ChangeSourceRef,
    ChangeType,
    EventEntity,
    EventEntityLifecycle,
    IngestApplyLog,
    ReviewStatus,
)
from app.db.models.shared import CourseWorkItemLabelFamily, CourseWorkItemRawType, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_source(db_session, *, user: User, provider: str) -> InputSource:
    return create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email" if provider == "gmail" else "calendar",
            provider=provider,
            config={"label_id": "INBOX", "monitor_since": "2026-01-05"}
            if provider == "gmail"
            else {"monitor_since": "2026-01-05"},
            secrets={} if provider == "gmail" else {"url": "https://example.com/calendar.ics"},
        ),
    )


def _create_family(
    db_session,
    *,
    user_id: int,
    course_display: str,
    canonical_label: str,
) -> CourseWorkItemLabelFamily:
    parsed = parse_course_display(course_display)
    family = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_dept=parsed["course_dept"],
        course_number=parsed["course_number"],
        course_suffix=parsed["course_suffix"],
        course_quarter=parsed["course_quarter"],
        course_year2=parsed["course_year2"],
        normalized_course_identity=normalized_course_identity_key(
            course_dept=parsed["course_dept"],
            course_number=parsed["course_number"],
            course_suffix=parsed["course_suffix"],
            course_quarter=parsed["course_quarter"],
            course_year2=parsed["course_year2"],
        ),
        canonical_label=canonical_label,
        normalized_canonical_label=normalize_label_token(canonical_label),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(family)
    return family


def _seed_sync_request(
    db_session,
    *,
    source: InputSource,
    request_id: str,
    status: SyncRequestStatus,
    stage: SyncRequestStage | None = None,
    substage: str | None = None,
    progress: dict | None = None,
) -> SyncRequest:
    row = SyncRequest(
        request_id=request_id,
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=status,
        stage=stage,
        substage=substage,
        stage_updated_at=datetime.now(timezone.utc) if stage is not None else None,
        progress_json=progress,
        idempotency_key=f"idemp:{request_id}",
        metadata_json={"kind": "test"},
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_changes_summary_matches_filtered_pending_lists(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="consistency-changes@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    family = _create_family(
        db_session,
        user_id=user.id,
        course_display="CSE 150 WI26",
        canonical_label="Homework",
    )
    now = datetime.now(timezone.utc)
    baseline_change = Change(
        user_id=user.id,
        entity_uid="ent-baseline-consistency",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.CREATED,
        intake_phase=ChangeIntakePhase.BASELINE,
        review_bucket=ChangeReviewBucket.INITIAL_REVIEW,
        detected_at=now,
        after_semantic_json={
            "uid": "ent-baseline-consistency",
            "course_dept": "CSE",
            "course_number": 150,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": "Homework",
            "event_name": "Homework 1",
            "ordinal": 1,
            "due_date": "2026-03-22",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        review_status=ReviewStatus.PENDING,
    )
    replay_change = Change(
        user_id=user.id,
        entity_uid="ent-replay-consistency",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=now,
        after_semantic_json={
            "uid": "ent-replay-consistency",
            "course_dept": "CSE",
            "course_number": 150,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": "Homework",
            "event_name": "Homework 2",
            "ordinal": 2,
            "due_date": "2026-03-25",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        review_status=ReviewStatus.PENDING,
    )
    db_session.add_all([baseline_change, replay_change])
    db_session.flush()
    db_session.add(
        ChangeSourceRef(
            change_id=baseline_change.id,
            position=0,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="evt-baseline-consistency",
            confidence=0.95,
        )
    )
    db_session.add(
        ChangeSourceRef(
            change_id=replay_change.id,
            position=0,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="evt-replay-consistency",
            confidence=0.95,
        )
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    summary = client.get("/changes/summary", headers=headers)
    initial_review = client.get(
        "/changes?review_status=pending&review_bucket=initial_review&intake_phase=baseline",
        headers=headers,
    )
    replay = client.get(
        "/changes?review_status=pending&review_bucket=changes&intake_phase=replay",
        headers=headers,
    )

    assert summary.status_code == 200
    assert initial_review.status_code == 200
    assert replay.status_code == 200

    summary_payload = summary.json()
    initial_review_payload = initial_review.json()
    replay_payload = replay.json()

    assert summary_payload["baseline_review_pending"] == len(initial_review_payload) == 1
    assert summary_payload["changes_pending"] == len(replay_payload) == 1
    assert summary_payload["workspace_posture"]["initial_review"]["pending_count"] == len(initial_review_payload)
    assert summary_payload["recommended_lane"] == "initial_review"
    assert summary_payload["recommended_lane_reason_code"] == "baseline_review_pending"
    assert {row["review_bucket"] for row in initial_review_payload} == {"initial_review"}
    assert {row["intake_phase"] for row in initial_review_payload} == {"baseline"}
    assert {row["review_bucket"] for row in replay_payload} == {"changes"}
    assert {row["intake_phase"] for row in replay_payload} == {"replay"}


def test_source_runtime_projection_stays_consistent_across_source_observability_and_sync_request(
    input_client,
    db_session,
    authenticate_client,
) -> None:
    user = _create_user(db_session, email="consistency-sources@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    progress = {
        "phase": "connector_fetch",
        "label": "Fetching Gmail message metadata",
        "detail": "Hydrated 12 of 40 changed emails.",
        "current": 12,
        "total": 40,
        "percent": 30.0,
        "unit": "emails",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    sync_request = _seed_sync_request(
        db_session,
        source=source,
        request_id="consistency-sync-1",
        status=SyncRequestStatus.RUNNING,
        stage=SyncRequestStage.CONNECTOR_FETCH,
        substage="gmail_message_hydrate",
        progress=progress,
    )
    db_session.add(
        IngestApplyLog(
            request_id="older-bootstrap",
            applied_at=datetime.now(timezone.utc),
            status="applied",
            error_message=None,
        )
    )
    older = SyncRequest(
        request_id="older-bootstrap",
        source_id=source.id,
        trigger_type=IngestTriggerType.SCHEDULER,
        status=SyncRequestStatus.SUCCEEDED,
        stage=SyncRequestStage.COMPLETED,
        substage=None,
        stage_updated_at=datetime.now(timezone.utc),
        progress_json=None,
        idempotency_key="idemp:older-bootstrap",
        metadata_json={"kind": "bootstrap"},
    )
    db_session.add(older)
    older.created_at = datetime(2026, 3, 18, 0, 0, 0, tzinfo=timezone.utc)
    older.updated_at = datetime(2026, 3, 18, 0, 5, 0, tzinfo=timezone.utc)
    sync_request.created_at = datetime(2026, 3, 18, 1, 0, 0, tzinfo=timezone.utc)
    sync_request.updated_at = datetime(2026, 3, 18, 1, 5, 0, tzinfo=timezone.utc)
    db_session.commit()

    authenticate_client(input_client, user=user)
    headers = {"X-API-Key": "test-api-key"}
    sources_response = input_client.get("/sources", headers=headers)
    observability_response = input_client.get(f"/sources/{source.id}/observability", headers=headers)
    sync_response = input_client.get(f"/sync-requests/{sync_request.request_id}", headers=headers)
    history_response = input_client.get(f"/sources/{source.id}/sync-history?limit=1", headers=headers)
    summary_response = input_client.get("/changes/summary", headers=headers)

    assert sources_response.status_code == 200
    assert observability_response.status_code == 200
    assert sync_response.status_code == 200
    assert history_response.status_code == 200
    assert summary_response.status_code == 200

    source_payload = sources_response.json()[0]
    observability_payload = observability_response.json()
    sync_payload = sync_response.json()
    history_payload = history_response.json()["items"][0]
    summary_payload = summary_response.json()

    assert source_payload["active_request_id"] == sync_request.request_id
    assert observability_payload["active_request_id"] == sync_request.request_id
    assert observability_payload["active"]["request_id"] == sync_request.request_id
    assert history_payload["request_id"] == sync_request.request_id
    assert sync_payload["request_id"] == sync_request.request_id
    assert source_payload["sync_progress"] == observability_payload["active"]["progress"] == sync_payload["progress"] == history_payload["progress"]
    assert observability_payload["active"]["stage"] == sync_payload["stage"] == "connector_fetch"
    assert observability_payload["active"]["substage"] == sync_payload["substage"] == "gmail_message_hydrate"
    assert source_payload["operator_guidance"]["reason_code"] == observability_payload["operator_guidance"]["reason_code"]
    assert source_payload["source_product_phase"] == observability_payload["source_product_phase"]
    assert source_payload["source_recovery"]["impact_code"] == observability_payload["source_recovery"]["impact_code"]
    assert summary_payload["sources"]["active_count"] == 1
    assert summary_payload["sources"]["running_count"] == 1
    assert summary_payload["sources"]["recommended_action"] == source_payload["operator_guidance"]["recommended_action"]


def test_manual_mutation_stays_consistent_with_manual_list_and_summary(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="consistency-manual@example.com")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 120 WI26", canonical_label="Homework")
    authenticate_client(input_client, user=user)
    headers = {"X-API-Key": "test-api-key"}

    create_response = input_client.post(
        "/manual/events",
        headers=headers,
        json={
            "family_id": family.id,
            "event_name": "HW 3",
            "raw_type": "hw",
            "ordinal": 3,
            "due_date": "2026-03-18",
            "time_precision": "date_only",
            "reason": "manual add",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()

    list_response = input_client.get("/manual/events", headers=headers)
    summary_response = input_client.get("/changes/summary", headers=headers)
    assert list_response.status_code == 200
    assert summary_response.status_code == 200
    active_rows = list_response.json()
    summary_payload = summary_response.json()

    assert len(active_rows) == 1
    assert active_rows[0]["entity_uid"] == created["entity_uid"]
    assert active_rows[0]["lifecycle"] == "active"
    assert summary_payload["manual"]["active_event_count"] == 1

    delete_response = input_client.delete(
        f"/manual/events/{created['entity_uid']}?reason=cleanup",
        headers=headers,
    )
    assert delete_response.status_code == 200

    active_after_delete = input_client.get("/manual/events", headers=headers)
    removed_visible = input_client.get("/manual/events?include_removed=true", headers=headers)
    summary_after_delete = input_client.get("/changes/summary", headers=headers)

    assert active_after_delete.status_code == 200
    assert removed_visible.status_code == 200
    assert summary_after_delete.status_code == 200
    assert active_after_delete.json() == []
    assert removed_visible.json()[0]["entity_uid"] == created["entity_uid"]
    assert removed_visible.json()[0]["lifecycle"] == "removed"
    assert summary_after_delete.json()["manual"]["active_event_count"] == 0


def test_family_relink_stays_consistent_between_family_and_raw_type_reads(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="consistency-families@example.com")
    authenticate_client(input_client, user=user)
    headers = {"X-API-Key": "test-api-key"}

    first = input_client.post(
        "/families",
        headers=headers,
        json={
            "course_dept": "CSE",
            "course_number": 100,
            "course_suffix": None,
            "course_quarter": "WI",
            "course_year2": 26,
            "canonical_label": "Homework",
            "raw_types": ["hw"],
        },
    )
    second = input_client.post(
        "/families",
        headers=headers,
        json={
            "course_dept": "CSE",
            "course_number": 100,
            "course_suffix": None,
            "course_quarter": "WI",
            "course_year2": 26,
            "canonical_label": "Programming Assignment",
            "raw_types": ["pa"],
        },
    )
    assert first.status_code == 201
    assert second.status_code == 201

    raw_types_before = input_client.get(
        "/families/raw-types?course_dept=CSE&course_number=100&course_quarter=WI&course_year2=26",
        headers=headers,
    )
    families_before = input_client.get("/families?course_dept=CSE&course_number=100&course_quarter=WI&course_year2=26", headers=headers)
    courses_response = input_client.get("/families/courses", headers=headers)
    assert raw_types_before.status_code == 200
    assert families_before.status_code == 200
    assert courses_response.status_code == 200
    assert len(courses_response.json()["courses"]) == 1

    hw_row = next(row for row in raw_types_before.json() if row["raw_type"] == "hw")
    relink = input_client.post(
        "/families/raw-types/relink",
        headers=headers,
        json={"raw_type_id": hw_row["id"], "family_id": second.json()["id"]},
    )
    assert relink.status_code == 200

    raw_types_after = input_client.get(
        "/families/raw-types?course_dept=CSE&course_number=100&course_quarter=WI&course_year2=26",
        headers=headers,
    )
    families_after = input_client.get("/families?course_dept=CSE&course_number=100&course_quarter=WI&course_year2=26", headers=headers)
    assert raw_types_after.status_code == 200
    assert families_after.status_code == 200

    after_raw_rows = raw_types_after.json()
    after_families = {row["id"]: row for row in families_after.json()}
    hw_after = next(row for row in after_raw_rows if row["raw_type"] == "hw")

    assert hw_after["family_id"] == second.json()["id"]
    assert "hw" not in after_families[first.json()["id"]]["raw_types"]
    assert "hw" in after_families[second.json()["id"]]["raw_types"]
    assert "pa" in after_families[second.json()["id"]]["raw_types"]
