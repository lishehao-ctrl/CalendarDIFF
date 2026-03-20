from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import (
    Change,
    ChangeIntakePhase,
    ChangeOrigin,
    ChangeReviewBucket,
    ChangeType,
    EventEntity,
    EventEntityLifecycle,
    ReviewStatus,
)
from app.db.models.shared import (
    CourseRawTypeSuggestion,
    CourseRawTypeSuggestionStatus,
    CourseWorkItemLabelFamily,
    CourseWorkItemRawType,
    User,
)


def _create_user_with_source(db_session, *, email: str) -> tuple[User, InputSource]:
    user = User(
        email=email,
        notify_email=email,
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key=f"src-{user.id}",
        display_name="Inbox",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def test_review_items_summary_counts_pending_only_for_current_user(client, db_session, auth_headers) -> None:
    user, _source = _create_user_with_source(db_session, email="owner@example.com")
    other_user, _other_source = _create_user_with_source(db_session, email="other@example.com")

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Change(
                user_id=user.id,
                entity_uid="ent-owner-pending",
                change_origin=ChangeOrigin.INGEST_PROPOSAL,
                change_type=ChangeType.CREATED,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-owner-pending",
                    "course_dept": "CSE",
                    "course_number": 100,
                    "family_name": "Homework",
                    "event_name": "Homework 1",
                    "ordinal": 1,
                    "due_date": "2026-03-15",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.PENDING,
            ),
            Change(
                user_id=user.id,
                entity_uid="ent-owner-approved",
                change_origin=ChangeOrigin.MANUAL_CANONICAL_EDIT,
                change_type=ChangeType.DUE_CHANGED,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-owner-approved",
                    "course_dept": "CSE",
                    "course_number": 100,
                    "family_name": "Homework",
                    "event_name": "Homework 2",
                    "ordinal": 2,
                    "due_date": "2026-03-20",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.APPROVED,
                reviewed_at=now,
            ),
            Change(
                user_id=other_user.id,
                entity_uid="ent-other-pending",
                change_origin=ChangeOrigin.INGEST_PROPOSAL,
                change_type=ChangeType.CREATED,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-other-pending",
                    "course_dept": "CSE",
                    "course_number": 120,
                    "family_name": "Quiz",
                    "event_name": "Quiz 1",
                    "ordinal": 1,
                    "due_date": "2026-03-16",
                    "due_time": "10:00:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.PENDING,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/changes/summary", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["changes_pending"] == 1
    assert "link_candidates_pending" not in payload
    assert payload["recommended_lane"] == "changes"
    assert payload["recommended_lane_reason_code"] == "changes_pending"
    assert payload["families"]["attention_count"] == 0
    assert payload["manual"]["active_event_count"] == 0
    assert payload["sources"]["active_count"] == 1
    assert isinstance(payload["generated_at"], str)


def test_changes_summary_includes_family_and_manual_posture(client, db_session, auth_headers) -> None:
    user, source = _create_user_with_source(db_session, email="owner2@example.com")

    family = CourseWorkItemLabelFamily(
        user_id=user.id,
        course_dept="CSE",
        course_number=120,
        course_suffix=None,
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity="cse:120:wi:26",
        canonical_label="Homework",
        normalized_canonical_label="homework",
    )
    db_session.add(family)
    db_session.flush()
    raw_type = CourseWorkItemRawType(
        family_id=family.id,
        raw_type="HW",
        normalized_raw_type="hw",
    )
    db_session.add(raw_type)
    db_session.flush()
    db_session.add(
        CourseRawTypeSuggestion(
            source_raw_type_id=raw_type.id,
            suggested_raw_type_id=None,
            source_observation_id=None,
            status=CourseRawTypeSuggestionStatus.PENDING,
            confidence=0.82,
            evidence="similar naming drift",
        )
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="manual-entity-1",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=120,
            course_suffix=None,
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            manual_support=True,
            raw_type="Manual",
            event_name="Manual override",
            ordinal=1,
            due_date=date(2026, 3, 21),
            due_time=None,
            time_precision="date_only",
        )
    )
    db_session.commit()

    response = client.get("/changes/summary", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["changes_pending"] == 0
    assert payload["recommended_lane"] == "families"
    assert payload["recommended_lane_reason_code"] == "family_governance_pending"
    assert payload["families"]["pending_raw_type_suggestions"] == 1
    assert payload["families"]["attention_count"] == 1
    assert payload["manual"]["active_event_count"] == 1
    assert payload["sources"]["active_count"] == 1
    assert payload["sources"]["blocking_count"] == 0


def test_changes_summary_prefers_sources_when_runtime_is_blocking(client, db_session, auth_headers) -> None:
    user, source = _create_user_with_source(db_session, email="owner3@example.com")
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.add(
        SyncRequest(
            request_id="sync-blocking-1",
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.RUNNING,
            stage=SyncRequestStage.PROVIDER_REDUCE,
            substage="calendar_reduce_wait",
            stage_updated_at=stale_at,
            progress_json={
                "phase": "provider_reduce",
                "label": "Reducing provider result",
                "detail": "Reducer has not reported fresh progress.",
                "updated_at": stale_at.isoformat(),
                "current": 1,
                "total": 2,
                "percent": 50.0,
                "unit": "events",
            },
            idempotency_key="blocking-1",
            trace_id="blocking-1",
            metadata_json={},
        )
    )
    db_session.commit()

    response = client.get("/changes/summary", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended_lane"] == "sources"
    assert payload["recommended_lane_reason_code"] == "runtime_attention_required"
    assert payload["sources"]["blocking_count"] == 1
    assert payload["sources"]["recommended_action"] == "wait_for_runtime"


def test_changes_summary_prefers_initial_review_before_changes(client, db_session, auth_headers) -> None:
    user, _source = _create_user_with_source(db_session, email="owner4@example.com")
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Change(
                user_id=user.id,
                entity_uid="ent-baseline-1",
                change_origin=ChangeOrigin.INGEST_PROPOSAL,
                change_type=ChangeType.CREATED,
                intake_phase=ChangeIntakePhase.BASELINE,
                review_bucket=ChangeReviewBucket.INITIAL_REVIEW,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-baseline-1",
                    "course_dept": "CSE",
                    "course_number": 140,
                    "family_name": "Homework",
                    "event_name": "Homework 1",
                    "ordinal": 1,
                    "due_date": "2026-03-22",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.PENDING,
            ),
            Change(
                user_id=user.id,
                entity_uid="ent-replay-1",
                change_origin=ChangeOrigin.INGEST_PROPOSAL,
                change_type=ChangeType.DUE_CHANGED,
                intake_phase=ChangeIntakePhase.REPLAY,
                review_bucket=ChangeReviewBucket.CHANGES,
                detected_at=now,
                after_semantic_json={
                    "uid": "ent-replay-1",
                    "course_dept": "CSE",
                    "course_number": 140,
                    "family_name": "Homework",
                    "event_name": "Homework 2",
                    "ordinal": 2,
                    "due_date": "2026-03-25",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                },
                review_status=ReviewStatus.PENDING,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/changes/summary", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["baseline_review_pending"] == 1
    assert payload["changes_pending"] == 1
    assert payload["recommended_lane"] == "initial_review"
    assert payload["recommended_lane_reason_code"] == "baseline_review_pending"
