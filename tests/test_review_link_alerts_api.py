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
    list_pending = client.get("/review/link-alerts", headers=headers)
    assert list_pending.status_code == 200
    rows = list_pending.json()
    assert len(rows) == 1
    assert rows[0]["id"] == alert.id
    assert rows[0]["status"] == "pending"
    assert rows[0]["reason_code"] == "auto_link_without_canonical_change"

    dismiss = client.post(
        f"/review/link-alerts/{alert.id}/dismiss",
        headers=headers,
        json={"note": "looks noisy"},
    )
    assert dismiss.status_code == 200
    dismiss_payload = dismiss.json()
    assert dismiss_payload["status"] == "dismissed"
    assert dismiss_payload["idempotent"] is False

    dismiss_again = client.post(
        f"/review/link-alerts/{alert.id}/dismiss",
        headers=headers,
        json={"note": "noop"},
    )
    assert dismiss_again.status_code == 200
    assert dismiss_again.json()["idempotent"] is True

    list_dismissed = client.get("/review/link-alerts?status=dismissed", headers=headers)
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
        f"/review/link-alerts/{alert_safe.id}/mark-safe",
        headers=headers,
        json={"note": "confirmed"},
    )
    assert mark_safe.status_code == 200
    mark_payload = mark_safe.json()
    assert mark_payload["status"] == "marked_safe"
    assert mark_payload["idempotent"] is False

    mark_safe_again = client.post(
        f"/review/link-alerts/{alert_safe.id}/mark-safe",
        headers=headers,
        json={"note": "noop"},
    )
    assert mark_safe_again.status_code == 200
    assert mark_safe_again.json()["idempotent"] is True

    list_all = client.get("/review/link-alerts?status=all", headers=headers)
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
    delete_resp = client.delete(f"/review/links/{link.id}", headers=headers)
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
        "/review/links/relink",
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


def test_link_alert_batch_dismiss_partial_success(client, db_session) -> None:
    user, source = _create_user_and_email_source(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent_alert_batch",
            course_best_json={"display_name": "CSE 142 SP26"},
            course_best_strength=5,
            course_aliases_json=[],
            title_aliases_json=[],
            metadata_json={},
        )
    )
    db_session.flush()

    pending_alert = _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-batch-pending",
        entity_uid="ent_alert_batch",
        status=EventLinkAlertStatus.PENDING,
    )
    dismissed_alert = _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-batch-dismissed",
        entity_uid="ent_alert_batch",
        status=EventLinkAlertStatus.DISMISSED,
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    resp = client.post(
        "/review/link-alerts/batch/decisions",
        headers=headers,
        json={
            "decision": "dismiss",
            "ids": [pending_alert.id, dismissed_alert.id, 999999, pending_alert.id],
            "note": "batch dismiss",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["decision"] == "dismiss"
    assert payload["total_requested"] == 3
    assert payload["succeeded"] == 2
    assert payload["failed"] == 1

    by_id = {row["id"]: row for row in payload["results"]}
    assert by_id[pending_alert.id]["ok"] is True
    assert by_id[pending_alert.id]["status"] == "dismissed"
    assert by_id[pending_alert.id]["idempotent"] is False
    assert by_id[pending_alert.id]["error_code"] is None

    assert by_id[dismissed_alert.id]["ok"] is True
    assert by_id[dismissed_alert.id]["status"] == "dismissed"
    assert by_id[dismissed_alert.id]["idempotent"] is True
    assert by_id[dismissed_alert.id]["error_code"] is None

    assert by_id[999999]["ok"] is False
    assert by_id[999999]["status"] is None
    assert by_id[999999]["error_code"] == "not_found"


def test_link_alert_batch_mark_safe_success(client, db_session) -> None:
    user, source = _create_user_and_email_source(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent_alert_batch_safe",
            course_best_json={"display_name": "CSE 143 SP26"},
            course_best_strength=5,
            course_aliases_json=[],
            title_aliases_json=[],
            metadata_json={},
        )
    )
    db_session.flush()

    first_alert = _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-batch-safe-1",
        entity_uid="ent_alert_batch_safe",
    )
    second_alert = _add_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-alert-batch-safe-2",
        entity_uid="ent_alert_batch_safe",
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    resp = client.post(
        "/review/link-alerts/batch/decisions",
        headers=headers,
        json={
            "decision": "mark_safe",
            "ids": [first_alert.id, second_alert.id],
            "note": "batch safe",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["decision"] == "mark_safe"
    assert payload["total_requested"] == 2
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0

    for row in payload["results"]:
        assert row["ok"] is True
        assert row["status"] == "marked_safe"
        assert row["idempotent"] is False
        assert row["error_code"] is None
        assert row["reviewed_at"] is not None


def test_link_alert_batch_decisions_validate_payload(client, db_session) -> None:
    _create_user_and_email_source(db_session)
    headers = {"X-API-Key": "test-api-key"}

    empty_ids = client.post(
        "/review/link-alerts/batch/decisions",
        headers=headers,
        json={"decision": "dismiss", "ids": []},
    )
    assert empty_ids.status_code == 422

    non_positive_id = client.post(
        "/review/link-alerts/batch/decisions",
        headers=headers,
        json={"decision": "dismiss", "ids": [0]},
    )
    assert non_positive_id.status_code == 422
