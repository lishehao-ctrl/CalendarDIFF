from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.agents import AgentProposal, AgentProposalStatus, AgentProposalType
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source
from app.db.models.input import SourceKind
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeType, EventEntity, EventEntityLifecycle, ReviewStatus, SourceEventObservation
from app.db.models.shared import CourseRawTypeSuggestion, CourseRawTypeSuggestionStatus, CourseWorkItemLabelFamily, CourseWorkItemRawType, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display


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


def _create_source(db_session, *, user: User):
    return create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            config={"monitor_since": "2026-01-05"},
            secrets={"url": "https://example.com/calendar.ics"},
        ),
    )


def test_agent_family_relink_preview_proposal_is_persisted_and_fetchable(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-family-proposal@example.com")
    source_family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Quiz")
    target_family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")
    raw_type = CourseWorkItemRawType(
        family_id=source_family.id,
        raw_type="write-up",
        normalized_raw_type="write up",
        metadata_json={},
    )
    db_session.add(raw_type)
    db_session.flush()
    suggestion = CourseRawTypeSuggestion(
        source_raw_type_id=raw_type.id,
        suggested_raw_type_id=None,
        source_observation_id=None,
        status=CourseRawTypeSuggestionStatus.PENDING,
        confidence=0.87,
        evidence="matched from import",
    )
    db_session.add(suggestion)
    db_session.commit()

    response = client.post(
        "/agent/proposals/family-relink-preview",
        headers=auth_headers(client, user=user),
        json={"raw_type_id": raw_type.id, "family_id": target_family.id},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["proposal_type"] == "family_relink_preview"
    assert payload["target_kind"] == "family_relink"
    assert payload["suggested_action"] == "preview_relink"
    assert payload["owner_user_id"] == user.id
    assert payload["origin_kind"] == "web"
    assert payload["origin_label"] == "embedded_agent"
    assert payload["suggested_payload"] == {
        "kind": "web_only_family_relink_preview",
        "raw_type_id": raw_type.id,
        "family_id": target_family.id,
    }
    assert payload["context"]["raw_type"]["raw_type"] == "write-up"
    assert payload["context"]["impact"]["impacted_event_count"] == 0
    assert payload["context"]["impact"]["impacted_pending_change_count"] == 0
    assert payload["target_snapshot"]["target_family_id"] == target_family.id

    row = db_session.scalar(select(AgentProposal).where(AgentProposal.id == payload["proposal_id"]))
    assert row is not None
    assert row.proposal_type == AgentProposalType.FAMILY_RELINK_PREVIEW
    assert row.status == AgentProposalStatus.OPEN

    fetched = client.get(f"/agent/proposals/{payload['proposal_id']}", headers=auth_headers(client, user=user))
    assert fetched.status_code == 200
    assert fetched.json()["proposal_id"] == payload["proposal_id"]


def test_agent_family_relink_preview_rejects_same_family_target(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-family-proposal-same@example.com")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")
    raw_type = CourseWorkItemRawType(
        family_id=family.id,
        raw_type="write-up",
        normalized_raw_type="write up",
        metadata_json={},
    )
    db_session.add(raw_type)
    db_session.commit()

    response = client.post(
        "/agent/proposals/family-relink-preview",
        headers=auth_headers(client, user=user),
        json={"raw_type_id": raw_type.id, "family_id": family.id},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agents.proposals.family.already_in_family"


def test_agent_family_relink_commit_proposal_is_executable_when_low_risk(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-family-commit@example.com")
    source_family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Quiz")
    target_family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")
    raw_type = CourseWorkItemRawType(
        family_id=source_family.id,
        raw_type="write-up",
        normalized_raw_type="write up",
        metadata_json={},
    )
    db_session.add(raw_type)
    db_session.commit()

    response = client.post(
        "/agent/proposals/family-relink-commit",
        headers=auth_headers(client, user=user),
        json={"raw_type_id": raw_type.id, "family_id": target_family.id},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["proposal_type"] == "family_relink_preview"
    assert payload["suggested_action"] == "commit_relink"
    assert payload["execution_mode"] == "approval_ticket_required"
    assert payload["can_create_ticket"] is True
    assert payload["suggested_payload"]["kind"] == "family_relink_commit"
    assert payload["target_snapshot"]["current_family_id"] == source_family.id
    assert payload["target_snapshot"]["target_family_id"] == target_family.id


def test_agent_family_relink_commit_proposal_rejects_when_pending_changes_would_be_affected(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-family-commit-risk@example.com")
    source = _create_source(db_session, user=user)
    source_family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Quiz")
    target_family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")
    raw_type = CourseWorkItemRawType(
        family_id=source_family.id,
        raw_type="write-up",
        normalized_raw_type="write up",
        metadata_json={},
    )
    db_session.add(raw_type)
    db_session.flush()
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=SourceKind.CALENDAR,
            provider="ics",
            external_event_id="evt-risk",
            entity_uid="family-risk-1",
            event_payload={
                "semantic_event": {
                    "course_dept": "CSE",
                    "course_number": 160,
                    "course_quarter": "WI",
                    "course_year2": 26,
                    "family_id": source_family.id,
                    "raw_type": "write-up",
                    "event_name": "Write-up 1",
                }
            },
            event_hash="hash",
        )
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="family-risk-1",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=160,
            course_quarter="WI",
            course_year2=26,
            family_id=source_family.id,
            raw_type="write-up",
            event_name="Write-up 1",
            ordinal=1,
        )
    )
    db_session.add(
        Change(
            user_id=user.id,
            entity_uid="family-risk-1",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.CREATED,
            intake_phase=ChangeIntakePhase.REPLAY,
            review_bucket=ChangeReviewBucket.CHANGES,
            detected_at=datetime.now(timezone.utc),
            after_semantic_json={
                "family_id": source_family.id,
                "family_name": source_family.canonical_label,
                "raw_type": "write-up",
            },
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.commit()

    response = client.post(
        "/agent/proposals/family-relink-commit",
        headers=auth_headers(client, user=user),
        json={"raw_type_id": raw_type.id, "family_id": target_family.id},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agents.proposals.family.commit_not_low_risk"
