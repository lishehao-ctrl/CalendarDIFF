from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.core.security import encrypt_secret
from app.db.models.input import InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind
from app.db.models.review import Change, ChangeType, Input, InputType, ReviewStatus, SourceEventObservation
from app.db.models.shared import User


def _create_user(db_session) -> User:
    user = User(
        email="source-summary-owner@example.com",
        notify_email="source-summary-owner@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    return user


def _create_source(
    db_session,
    *,
    user: User,
    provider: str,
    source_kind: SourceKind,
    source_key: str,
    display_name: str,
    secrets: dict,
) -> InputSource:
    source = InputSource(
        user_id=user.id,
        source_kind=source_kind,
        provider=provider,
        source_key=source_key,
        display_name=display_name,
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={}))
    db_session.add(
        InputSourceSecret(
            source_id=source.id,
            encrypted_payload=encrypt_secret(json.dumps(secrets)),
        )
    )
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    db_session.flush()
    return source


def _create_canonical_input(db_session, *, user: User, input_type: InputType, identity_key: str) -> Input:
    input_row = Input(user_id=user.id, type=input_type, identity_key=identity_key, is_active=True)
    db_session.add(input_row)
    db_session.flush()
    return input_row


def _create_change(
    db_session,
    *,
    input_id: int,
    event_uid: str,
    change_type: ChangeType,
    before_json: dict | None,
    after_json: dict | None,
    proposal_merge_key: str,
    proposal_sources_json: list[dict],
) -> Change:
    change = Change(
        input_id=input_id,
        event_uid=event_uid,
        change_type=change_type,
        detected_at=datetime.now(timezone.utc),
        before_json=before_json,
        after_json=after_json,
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        reviewed_at=None,
        review_note=None,
        reviewed_by_user_id=None,
        proposal_merge_key=proposal_merge_key,
        proposal_sources_json=proposal_sources_json,
        before_snapshot_id=None,
        after_snapshot_id=None,
        evidence_keys=None,
    )
    db_session.add(change)
    db_session.flush()
    return change


def _create_observation(
    db_session,
    *,
    user: User,
    source: InputSource,
    external_event_id: str,
    merge_key: str,
    observed_at: datetime,
) -> SourceEventObservation:
    observation = SourceEventObservation(
        user_id=user.id,
        source_id=source.id,
        source_kind=source.source_kind,
        provider=source.provider,
        external_event_id=external_event_id,
        merge_key=merge_key,
        event_payload={"title": "Source observation"},
        event_hash=f"hash:{source.id}:{external_event_id}",
        observed_at=observed_at,
        is_active=True,
        last_request_id=None,
    )
    db_session.add(observation)
    db_session.flush()
    return observation


def test_review_changes_created_exposes_current_source_summary(client, db_session, auth_headers) -> None:
    user = _create_user(db_session)
    calendar_source = _create_source(
        db_session,
        user=user,
        provider="ics",
        source_kind=SourceKind.CALENDAR,
        source_key="canvas_ics",
        display_name="Canvas ICS",
        secrets={"url": "https://example.com/source-summary.ics"},
    )
    canonical_input = _create_canonical_input(db_session, user=user, input_type=InputType.ICS, identity_key="created-input")
    observed_at = datetime(2026, 3, 7, 8, 15, tzinfo=timezone.utc)
    _create_observation(
        db_session,
        user=user,
        source=calendar_source,
        external_event_id="created-calendar-1",
        merge_key="ent-created-1",
        observed_at=observed_at,
    )
    _create_change(
        db_session,
        input_id=canonical_input.id,
        event_uid="ent-created-1",
        change_type=ChangeType.CREATED,
        before_json=None,
        after_json={"title": "Quiz 1", "start_at_utc": "2026-03-10T20:00:00+00:00"},
        proposal_merge_key="ent-created-1",
        proposal_sources_json=[
            {
                "source_id": calendar_source.id,
                "source_kind": "calendar",
                "provider": "ics",
                "external_event_id": "created-calendar-1",
                "confidence": 0.94,
            }
        ],
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.get("/review/changes?review_status=pending&limit=1", headers=headers)
    assert response.status_code == 200
    payload = response.json()[0]

    assert set(payload["change_summary"]["old"].keys()) == {"value_time", "source_label", "source_kind", "source_observed_at"}
    assert set(payload["change_summary"]["new"].keys()) == {"value_time", "source_label", "source_kind", "source_observed_at"}
    assert payload["change_summary"]["old"]["source_label"] is None
    assert payload["change_summary"]["old"]["source_kind"] is None
    assert payload["change_summary"]["new"]["source_label"] == "Canvas ICS"
    assert payload["change_summary"]["new"]["source_kind"] == "calendar"
    assert payload["change_summary"]["new"]["source_observed_at"] == "2026-03-07T08:15:00Z"


def test_review_changes_removed_keeps_only_previous_source_summary(client, db_session, auth_headers) -> None:
    user = _create_user(db_session)
    _create_source(
        db_session,
        user=user,
        provider="ics",
        source_kind=SourceKind.CALENDAR,
        source_key="canvas_ics",
        display_name="Canvas ICS",
        secrets={"url": "https://example.com/source-summary.ics"},
    )
    canonical_input = _create_canonical_input(db_session, user=user, input_type=InputType.ICS, identity_key="removed-input")
    _create_change(
        db_session,
        input_id=canonical_input.id,
        event_uid="ent-removed-1",
        change_type=ChangeType.REMOVED,
        before_json={"title": "Homework 2", "start_at_utc": "2026-03-12T18:00:00+00:00"},
        after_json=None,
        proposal_merge_key="ent-removed-1",
        proposal_sources_json=[],
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.get("/review/changes?review_status=pending&limit=1", headers=headers)
    assert response.status_code == 200
    payload = response.json()[0]

    assert payload["change_summary"]["old"]["source_label"] == "Calendar · Primary"
    assert payload["change_summary"]["old"]["source_kind"] == "calendar"
    assert payload["change_summary"]["new"]["source_label"] is None
    assert payload["change_summary"]["new"]["source_kind"] is None
    assert payload["change_summary"]["new"]["source_observed_at"] is None


def test_review_changes_due_changed_uses_primary_proposal_source_context(client, db_session, auth_headers) -> None:
    user = _create_user(db_session)
    _create_source(
        db_session,
        user=user,
        provider="ics",
        source_kind=SourceKind.CALENDAR,
        source_key="canvas_ics",
        display_name="Canvas ICS",
        secrets={"url": "https://example.com/source-summary.ics"},
    )
    gmail_source = _create_source(
        db_session,
        user=user,
        provider="gmail",
        source_kind=SourceKind.EMAIL,
        source_key="summary-gmail-source",
        display_name="Summary Gmail Source",
        secrets={"access_token": "token", "account_email": "merge@example.edu"},
    )
    canonical_input = _create_canonical_input(db_session, user=user, input_type=InputType.ICS, identity_key="due-changed-input")
    observed_at = datetime(2026, 3, 7, 9, 45, tzinfo=timezone.utc)
    _create_observation(
        db_session,
        user=user,
        source=gmail_source,
        external_event_id="gmail-msg-1",
        merge_key="ent-due-changed-1",
        observed_at=observed_at,
    )
    _create_change(
        db_session,
        input_id=canonical_input.id,
        event_uid="ent-due-changed-1",
        change_type=ChangeType.DUE_CHANGED,
        before_json={"title": "Lab 3", "start_at_utc": "2026-03-14T19:00:00+00:00"},
        after_json={"title": "Lab 3", "start_at_utc": "2026-03-15T01:30:00+00:00"},
        proposal_merge_key="ent-due-changed-1",
        proposal_sources_json=[
            {
                "source_id": gmail_source.id,
                "source_kind": "email",
                "provider": "gmail",
                "external_event_id": "gmail-msg-1",
                "confidence": 0.87,
            }
        ],
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.get("/review/changes?review_status=pending&limit=1", headers=headers)
    assert response.status_code == 200
    payload = response.json()[0]

    assert payload["change_summary"]["old"]["source_label"] == "Calendar · Primary"
    assert payload["change_summary"]["old"]["source_kind"] == "calendar"
    assert payload["change_summary"]["new"]["source_label"] == "Gmail · merge@example.edu"
    assert payload["change_summary"]["new"]["source_kind"] == "email"
    assert payload["change_summary"]["new"]["source_observed_at"] == "2026-03-07T09:45:00Z"


def test_review_changes_missing_observation_keeps_source_label_and_null_observed_time(client, db_session, auth_headers) -> None:
    user = _create_user(db_session)
    _create_source(
        db_session,
        user=user,
        provider="ics",
        source_kind=SourceKind.CALENDAR,
        source_key="canvas_ics",
        display_name="Canvas ICS",
        secrets={"url": "https://example.com/source-summary.ics"},
    )
    gmail_source = _create_source(
        db_session,
        user=user,
        provider="gmail",
        source_kind=SourceKind.EMAIL,
        source_key="summary-gmail-source",
        display_name="Summary Gmail Source",
        secrets={"access_token": "token", "account_email": "missing-observation@example.edu"},
    )
    canonical_input = _create_canonical_input(db_session, user=user, input_type=InputType.ICS, identity_key="missing-observation-input")
    _create_change(
        db_session,
        input_id=canonical_input.id,
        event_uid="ent-missing-observation-1",
        change_type=ChangeType.DUE_CHANGED,
        before_json={"title": "Project milestone", "start_at_utc": "2026-03-20T22:00:00+00:00"},
        after_json={"title": "Project milestone", "start_at_utc": "2026-03-21T00:30:00+00:00"},
        proposal_merge_key="ent-missing-observation-1",
        proposal_sources_json=[
            {
                "source_id": gmail_source.id,
                "source_kind": "email",
                "provider": "gmail",
                "external_event_id": "gmail-msg-missing",
                "confidence": 0.76,
            }
        ],
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    response = client.get("/review/changes?review_status=pending&limit=1", headers=headers)
    assert response.status_code == 200
    payload = response.json()[0]

    assert payload["change_summary"]["new"]["source_label"] == "Gmail · missing-observation@example.edu"
    assert payload["change_summary"]["new"]["source_observed_at"] is None
