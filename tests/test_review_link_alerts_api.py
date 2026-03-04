from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import (
    EventEntity,
    EventEntityLink,
    EventLinkAlert,
    EventLinkAlertReason,
    EventLinkAlertResolution,
    EventLinkAlertRiskLevel,
    EventLinkAlertStatus,
    EventLinkOrigin,
    InputSource,
    SourceKind,
    User,
)


def _create_user_and_email_source(db_session) -> tuple[User, InputSource]:
    user = User(
        email="review-alerts-owner@example.com",
        notify_email="review-alerts-owner@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="review-alerts-gmail",
        display_name="Review Alerts Gmail",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.flush()
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def _add_alert(
    db_session,
    *,
    user_id: int,
    source_id: int,
    external_event_id: str,
    entity_uid: str,
    status: EventLinkAlertStatus = EventLinkAlertStatus.PENDING,
) -> EventLinkAlert:
    row = EventLinkAlert(
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        entity_uid=entity_uid,
        link_id=None,
        risk_level=EventLinkAlertRiskLevel.MEDIUM,
        reason_code=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE,
        status=status,
        resolution_code=None,
        evidence_snapshot_json={"rule_reason": "linked"},
        reviewed_by_user_id=None,
        reviewed_at=None,
        review_note=None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_link_alerts_list_and_decisions(client, db_session) -> None:
    user, source = _create_user_and_email_source(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent_alert_a",
            course_best_json={"display_name": "CSE 151 WI26"},
            course_best_strength=5,
            course_aliases_json=[],
            title_aliases_json=[],
            metadata_json={},
        )
    )
    db_session.flush()
    alert = _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-1",
        entity_uid="ent_alert_a",
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    list_pending = client.get("/v2/review-items/link-alerts", headers=headers)
    assert list_pending.status_code == 200
    rows = list_pending.json()
    assert len(rows) == 1
    assert rows[0]["id"] == alert.id
    assert rows[0]["status"] == "pending"
    assert rows[0]["reason_code"] == "auto_link_without_canonical_change"

    dismiss = client.post(
        f"/v2/review-items/link-alerts/{alert.id}/dismiss",
        headers=headers,
        json={"note": "looks noisy"},
    )
    assert dismiss.status_code == 200
    dismiss_payload = dismiss.json()
    assert dismiss_payload["status"] == "dismissed"
    assert dismiss_payload["idempotent"] is False

    dismiss_again = client.post(
        f"/v2/review-items/link-alerts/{alert.id}/dismiss",
        headers=headers,
        json={"note": "noop"},
    )
    assert dismiss_again.status_code == 200
    assert dismiss_again.json()["idempotent"] is True

    list_dismissed = client.get("/v2/review-items/link-alerts?status=dismissed", headers=headers)
    assert list_dismissed.status_code == 200
    assert len(list_dismissed.json()) == 1

    alert_safe = _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-2",
        entity_uid="ent_alert_a",
    )
    db_session.commit()

    mark_safe = client.post(
        f"/v2/review-items/link-alerts/{alert_safe.id}/mark-safe",
        headers=headers,
        json={"note": "confirmed"},
    )
    assert mark_safe.status_code == 200
    mark_payload = mark_safe.json()
    assert mark_payload["status"] == "marked_safe"
    assert mark_payload["idempotent"] is False

    mark_safe_again = client.post(
        f"/v2/review-items/link-alerts/{alert_safe.id}/mark-safe",
        headers=headers,
        json={"note": "noop"},
    )
    assert mark_safe_again.status_code == 200
    assert mark_safe_again.json()["idempotent"] is True

    list_all = client.get("/v2/review-items/link-alerts?status=all", headers=headers)
    assert list_all.status_code == 200
    statuses = {row["status"] for row in list_all.json()}
    assert "dismissed" in statuses
    assert "marked_safe" in statuses


def test_link_alert_resolved_by_link_delete_and_relink(client, db_session) -> None:
    user, source = _create_user_and_email_source(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent_alert_a",
            course_best_json={"display_name": "CSE 151A WI26"},
            course_best_strength=5,
            course_aliases_json=[],
            title_aliases_json=[],
            metadata_json={},
        )
    )
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent_alert_b",
            course_best_json={"display_name": "CSE 151B WI26"},
            course_best_strength=5,
            course_aliases_json=[],
            title_aliases_json=[],
            metadata_json={},
        )
    )
    db_session.flush()

    link = EventEntityLink(
        user_id=user.id,
        source_id=source.id,
        source_kind=SourceKind.EMAIL,
        external_event_id="gmail-alert-link-1",
        entity_uid="ent_alert_a",
        link_origin=EventLinkOrigin.AUTO,
        link_score=0.9,
        signals_json={"keywords": ["exam"]},
    )
    db_session.add(link)
    db_session.flush()
    _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-link-1",
        entity_uid="ent_alert_a",
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    delete_resp = client.delete(f"/v2/review-items/links/{link.id}", headers=headers)
    assert delete_resp.status_code == 200

    resolved_after_delete = db_session.scalar(
        select(EventLinkAlert).where(
            EventLinkAlert.user_id == user.id,
            EventLinkAlert.source_id == source.id,
            EventLinkAlert.external_event_id == "gmail-alert-link-1",
            EventLinkAlert.entity_uid == "ent_alert_a",
        )
    )
    assert resolved_after_delete is not None
    assert resolved_after_delete.status == EventLinkAlertStatus.RESOLVED
    assert resolved_after_delete.resolution_code == EventLinkAlertResolution.LINK_REMOVED

    relink_source = EventEntityLink(
        user_id=user.id,
        source_id=source.id,
        source_kind=SourceKind.EMAIL,
        external_event_id="gmail-alert-link-2",
        entity_uid="ent_alert_a",
        link_origin=EventLinkOrigin.AUTO,
        link_score=0.9,
        signals_json={"keywords": ["exam"]},
    )
    db_session.add(relink_source)
    db_session.flush()
    _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-link-2",
        entity_uid="ent_alert_a",
    )
    db_session.commit()

    relink_resp = client.post(
        "/v2/review-items/links/relink",
        headers=headers,
        json={
            "source_id": source.id,
            "external_event_id": "gmail-alert-link-2",
            "entity_uid": "ent_alert_b",
            "clear_block": True,
            "note": "manual relink",
        },
    )
    assert relink_resp.status_code == 200

    resolved_after_relink = db_session.scalar(
        select(EventLinkAlert).where(
            EventLinkAlert.user_id == user.id,
            EventLinkAlert.source_id == source.id,
            EventLinkAlert.external_event_id == "gmail-alert-link-2",
            EventLinkAlert.entity_uid == "ent_alert_a",
        )
    )
    assert resolved_after_relink is not None
    assert resolved_after_relink.status == EventLinkAlertStatus.RESOLVED
    assert resolved_after_relink.resolution_code == EventLinkAlertResolution.LINK_RELINKED
