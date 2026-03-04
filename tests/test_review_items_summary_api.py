from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import (
    Change,
    ChangeType,
    EventLinkAlert,
    EventLinkAlertReason,
    EventLinkAlertResolution,
    EventLinkAlertRiskLevel,
    EventLinkAlertStatus,
    EventLinkCandidate,
    EventLinkCandidateReason,
    EventLinkCandidateStatus,
    Input,
    InputSource,
    InputType,
    ReviewStatus,
    SourceKind,
    User,
)


def _create_onboarded_user_with_source(db_session, *, email: str, source_key: str) -> tuple[User, InputSource]:
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
        source_key=source_key,
        display_name=f"Source {source_key}",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.flush()
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def test_review_items_summary_counts_pending_only_for_current_user(client, db_session) -> None:
    user, source = _create_onboarded_user_with_source(
        db_session,
        email="summary-owner@example.com",
        source_key="summary-owner-source",
    )
    other_user, other_source = _create_onboarded_user_with_source(
        db_session,
        email="summary-other@example.com",
        source_key="summary-other-source",
    )

    owner_input = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="summary-owner-canonical",
        is_active=True,
    )
    other_input = Input(
        user_id=other_user.id,
        type=InputType.ICS,
        identity_key="summary-other-canonical",
        is_active=True,
    )
    db_session.add(owner_input)
    db_session.add(other_input)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        Change(
            input_id=owner_input.id,
            event_uid="summary-owner-change-pending",
            change_type=ChangeType.CREATED,
            detected_at=now,
            before_json=None,
            after_json={"title": "Owner pending"},
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.add(
        Change(
            input_id=owner_input.id,
            event_uid="summary-owner-change-approved",
            change_type=ChangeType.CREATED,
            detected_at=now,
            before_json=None,
            after_json={"title": "Owner approved"},
            review_status=ReviewStatus.APPROVED,
        )
    )
    db_session.add(
        Change(
            input_id=other_input.id,
            event_uid="summary-other-change-pending",
            change_type=ChangeType.CREATED,
            detected_at=now,
            before_json=None,
            after_json={"title": "Other pending"},
            review_status=ReviewStatus.PENDING,
        )
    )

    db_session.add(
        EventLinkCandidate(
            user_id=user.id,
            source_id=source.id,
            external_event_id="summary-owner-candidate-pending",
            proposed_entity_uid="ent_owner_pending",
            score=0.8,
            score_breakdown_json={"rule_reason": "pending"},
            reason_code=EventLinkCandidateReason.SCORE_BAND,
            status=EventLinkCandidateStatus.PENDING,
        )
    )
    db_session.add(
        EventLinkCandidate(
            user_id=user.id,
            source_id=source.id,
            external_event_id="summary-owner-candidate-approved",
            proposed_entity_uid="ent_owner_approved",
            score=0.8,
            score_breakdown_json={"rule_reason": "approved"},
            reason_code=EventLinkCandidateReason.SCORE_BAND,
            status=EventLinkCandidateStatus.APPROVED,
        )
    )
    db_session.add(
        EventLinkCandidate(
            user_id=other_user.id,
            source_id=other_source.id,
            external_event_id="summary-other-candidate-pending",
            proposed_entity_uid="ent_other_pending",
            score=0.8,
            score_breakdown_json={"rule_reason": "pending"},
            reason_code=EventLinkCandidateReason.SCORE_BAND,
            status=EventLinkCandidateStatus.PENDING,
        )
    )

    db_session.add(
        EventLinkAlert(
            user_id=user.id,
            source_id=source.id,
            external_event_id="summary-owner-alert-pending",
            entity_uid="ent_owner_pending",
            link_id=None,
            risk_level=EventLinkAlertRiskLevel.MEDIUM,
            reason_code=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE,
            status=EventLinkAlertStatus.PENDING,
            resolution_code=None,
            evidence_snapshot_json={"rule_reason": "pending"},
            reviewed_by_user_id=None,
            reviewed_at=None,
            review_note=None,
        )
    )
    db_session.add(
        EventLinkAlert(
            user_id=user.id,
            source_id=source.id,
            external_event_id="summary-owner-alert-resolved",
            entity_uid="ent_owner_resolved",
            link_id=None,
            risk_level=EventLinkAlertRiskLevel.MEDIUM,
            reason_code=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE,
            status=EventLinkAlertStatus.RESOLVED,
            resolution_code=EventLinkAlertResolution.LINK_REMOVED,
            evidence_snapshot_json={"rule_reason": "resolved"},
            reviewed_by_user_id=None,
            reviewed_at=now,
            review_note="resolved",
        )
    )
    db_session.add(
        EventLinkAlert(
            user_id=other_user.id,
            source_id=other_source.id,
            external_event_id="summary-other-alert-pending",
            entity_uid="ent_other_pending",
            link_id=None,
            risk_level=EventLinkAlertRiskLevel.MEDIUM,
            reason_code=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE,
            status=EventLinkAlertStatus.PENDING,
            resolution_code=None,
            evidence_snapshot_json={"rule_reason": "pending"},
            reviewed_by_user_id=None,
            reviewed_at=None,
            review_note=None,
        )
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/review/summary", headers=headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["changes_pending"] == 1
    assert payload["link_candidates_pending"] == 1
    assert payload["link_alerts_pending"] == 1
    assert isinstance(payload["generated_at"], str)
