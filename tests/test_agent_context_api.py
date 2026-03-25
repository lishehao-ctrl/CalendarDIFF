from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeSourceRef, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
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


def test_agent_workspace_context_exposes_summary_and_top_pending_changes(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-workspace@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 150 WI26", canonical_label="Homework")
    now = datetime.now(timezone.utc)

    baseline_change = Change(
        user_id=user.id,
        entity_uid="ent-agent-baseline",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.CREATED,
        intake_phase=ChangeIntakePhase.BASELINE,
        review_bucket=ChangeReviewBucket.INITIAL_REVIEW,
        detected_at=now,
        after_semantic_json={
            "uid": "ent-agent-baseline",
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
        entity_uid="ent-agent-replay",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=now,
        after_semantic_json={
            "uid": "ent-agent-replay",
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
    db_session.add_all(
        [
            ChangeSourceRef(
                change_id=baseline_change.id,
                position=0,
                source_id=source.id,
                source_kind=source.source_kind,
                provider=source.provider,
                external_event_id="evt-agent-baseline",
                confidence=0.95,
            ),
            ChangeSourceRef(
                change_id=replay_change.id,
                position=0,
                source_id=source.id,
                source_kind=source.source_kind,
                provider=source.provider,
                external_event_id="evt-agent-replay",
                confidence=0.95,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/agent/context/workspace", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["baseline_review_pending"] == 1
    assert payload["summary"]["changes_pending"] == 1
    assert payload["recommended_next_action"]["lane"] == "initial_review"
    assert payload["recommended_next_action"]["recommended_tool"] == "review_initial_review_changes"
    assert len(payload["top_pending_changes"]) == 2
    assert payload["blocking_conditions"][0]["code"] == "baseline_review_pending"
    assert "review_source_context" in payload["available_next_tools"]
    assert isinstance(payload["generated_at"], str)


def test_agent_change_context_exposes_change_decision_shape(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-change@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Quiz")
    now = datetime.now(timezone.utc)
    change = Change(
        user_id=user.id,
        entity_uid="ent-agent-change",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=now,
        before_semantic_json={
            "uid": "ent-agent-change",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": "Quiz",
            "event_name": "Quiz 1",
            "ordinal": 1,
            "due_date": "2026-03-20",
            "due_time": "09:00:00",
            "time_precision": "datetime",
        },
        after_semantic_json={
            "uid": "ent-agent-change",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": "Quiz",
            "event_name": "Quiz 1",
            "ordinal": 1,
            "due_date": "2026-03-21",
            "due_time": "09:00:00",
            "time_precision": "datetime",
        },
        before_evidence_json={"provider": "ics"},
        after_evidence_json={"provider": "ics"},
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(change)
    db_session.flush()
    db_session.add(
        ChangeSourceRef(
            change_id=change.id,
            position=0,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="evt-agent-change",
            confidence=0.95,
        )
    )
    db_session.commit()

    response = client.get(f"/agent/context/changes/{change.id}", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["change"]["id"] == change.id
    assert payload["recommended_next_action"]["lane"] == "changes"
    assert payload["recommended_next_action"]["risk_level"] == "medium"
    assert payload["recommended_next_action"]["recommended_tool"] == "submit_change_decision"
    assert "submit_change_decision" in payload["available_next_tools"]
    assert "preview_change_edit" in payload["available_next_tools"]
    assert payload["blocking_conditions"] == []


def test_agent_source_context_exposes_source_and_runtime_consistently(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session, email="agent-source@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    sync_request = SyncRequest(
        request_id="agent-source-sync",
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        stage=SyncRequestStage.CONNECTOR_FETCH,
        substage="gmail_message_hydrate",
        stage_updated_at=datetime.now(timezone.utc),
        progress_json={
            "phase": "connector_fetch",
            "label": "Fetching Gmail message metadata",
            "detail": "Hydrated 8 of 20 changed emails.",
            "current": 8,
            "total": 20,
            "percent": 40.0,
            "unit": "emails",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        idempotency_key="idemp:agent-source-sync",
        metadata_json={"kind": "test"},
    )
    db_session.add(sync_request)
    db_session.commit()

    authenticate_client(input_client, user=user)
    response = input_client.get(f"/agent/context/sources/{source.id}", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["source_id"] == source.id
    assert payload["source"]["active_request_id"] == "agent-source-sync"
    assert payload["observability"]["active_request_id"] == "agent-source-sync"
    assert payload["active_sync_request"]["request_id"] == "agent-source-sync"
    assert payload["active_sync_request"]["stage"] == "connector_fetch"
    assert payload["recommended_next_action"]["lane"] == "sources"
    assert payload["recommended_next_action"]["label"] == payload["observability"]["source_recovery"]["next_action_label"]
    assert payload["recommended_next_action"]["reason"] == payload["observability"]["source_recovery"]["impact_summary"]
    assert "run_source_sync" in payload["available_next_tools"]
    assert "view_sync_history" in payload["available_next_tools"]
    assert any(item["severity"] == "blocking" for item in payload["blocking_conditions"])
