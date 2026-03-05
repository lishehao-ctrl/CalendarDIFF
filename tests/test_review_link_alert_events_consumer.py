from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.contracts.events import new_event
from app.db.models.input import InputSource, SourceKind
from app.db.models.review import (
    EventLinkAlert,
    EventLinkAlertReason,
    EventLinkAlertResolution,
    EventLinkAlertRiskLevel,
    EventLinkAlertStatus,
)
from app.db.models.shared import IntegrationInbox, IntegrationOutbox, OutboxStatus, User
from app.modules.review_links.alerts_event_consumer import (
    REVIEW_LINK_ALERTS_CONSUMER,
    run_review_link_alert_events_tick,
)


def _seed_user_source(db_session) -> tuple[User, InputSource]:
    now = datetime.now(timezone.utc)
    user = User(
        email="alerts-consumer@example.com",
        notify_email="alerts-consumer@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key=f"alerts-src-{user.id}",
        display_name="Alerts Source",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=now,
    )
    db_session.add(source)
    db_session.flush()
    return user, source


def _seed_pending_alert(
    db_session,
    *,
    user_id: int,
    source_id: int,
    external_event_id: str,
    entity_uid: str,
) -> EventLinkAlert:
    row = EventLinkAlert(
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        entity_uid=entity_uid,
        link_id=None,
        risk_level=EventLinkAlertRiskLevel.MEDIUM,
        reason_code=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE,
        status=EventLinkAlertStatus.PENDING,
        resolution_code=None,
        evidence_snapshot_json={"kind": "seed"},
        reviewed_by_user_id=None,
        reviewed_at=None,
        review_note=None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _enqueue_link_alert_event(
    db_session,
    *,
    event_type: str,
    aggregate_id: str,
    payload: dict,
    event_id: str | None = None,
) -> IntegrationOutbox:
    event = new_event(
        event_type=event_type,
        aggregate_type="link_alert_request",
        aggregate_id=aggregate_id,
        payload=payload,
    )
    row = IntegrationOutbox(
        event_id=event_id or event.event_id,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        payload_json=event.payload,
        status=OutboxStatus.PENDING,
        available_at=event.available_at,
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_review_link_alert_events_consumer_processes_three_event_types(db_session) -> None:
    user, source = _seed_user_source(db_session)
    pair_alert = _seed_pending_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="evt-pair",
        entity_uid="entity-pair",
    )
    entities_alert = _seed_pending_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="evt-entities",
        entity_uid="entity-target",
    )
    _enqueue_link_alert_event(
        db_session,
        event_type="review.link_alert.upsert.requested",
        aggregate_id=f"{user.id}:{source.id}:evt-upsert:entity-new",
        payload={
            "user_id": user.id,
            "source_id": source.id,
            "external_event_id": "evt-upsert",
            "entity_uid": "entity-new",
            "link_id": None,
            "evidence_snapshot": {"reason": "auto_link_without_pending"},
        },
    )
    _enqueue_link_alert_event(
        db_session,
        event_type="review.link_alert.resolve_pair.requested",
        aggregate_id=f"{user.id}:{source.id}:evt-pair",
        payload={
            "user_id": user.id,
            "source_id": source.id,
            "external_event_id": "evt-pair",
            "resolution_code": EventLinkAlertResolution.CANDIDATE_OPENED.value,
            "note": "pair resolved",
        },
    )
    _enqueue_link_alert_event(
        db_session,
        event_type="review.link_alert.resolve_entities.requested",
        aggregate_id=f"{user.id}:entities",
        payload={
            "user_id": user.id,
            "entity_uids": ["entity-target"],
            "resolution_code": EventLinkAlertResolution.CANONICAL_PENDING_CREATED.value,
            "note": "entities resolved",
        },
    )
    db_session.commit()

    processed = run_review_link_alert_events_tick(db_session, batch_limit=50)
    assert processed == 3

    outbox_rows = db_session.scalars(select(IntegrationOutbox).order_by(IntegrationOutbox.id.asc())).all()
    assert len(outbox_rows) == 3
    assert all(row.status == OutboxStatus.PROCESSED for row in outbox_rows)

    db_session.refresh(pair_alert)
    db_session.refresh(entities_alert)
    assert pair_alert.status == EventLinkAlertStatus.RESOLVED
    assert pair_alert.resolution_code == EventLinkAlertResolution.CANDIDATE_OPENED
    assert entities_alert.status == EventLinkAlertStatus.RESOLVED
    assert entities_alert.resolution_code == EventLinkAlertResolution.CANONICAL_PENDING_CREATED

    created_alert = db_session.scalar(
        select(EventLinkAlert).where(
            EventLinkAlert.user_id == user.id,
            EventLinkAlert.source_id == source.id,
            EventLinkAlert.external_event_id == "evt-upsert",
            EventLinkAlert.entity_uid == "entity-new",
        )
    )
    assert created_alert is not None
    assert created_alert.status == EventLinkAlertStatus.PENDING

    inbox_count = db_session.scalar(
        select(func.count()).select_from(IntegrationInbox).where(IntegrationInbox.consumer_name == REVIEW_LINK_ALERTS_CONSUMER)
    )
    assert int(inbox_count or 0) == 3


def test_review_link_alert_events_consumer_is_idempotent_by_inbox(db_session) -> None:
    user, source = _seed_user_source(db_session)
    pair_alert = _seed_pending_alert(
        db_session,
        user_id=user.id,
        source_id=source.id,
        external_event_id="evt-replay",
        entity_uid="entity-replay",
    )
    outbox_row = _enqueue_link_alert_event(
        db_session,
        event_type="review.link_alert.resolve_pair.requested",
        aggregate_id=f"{user.id}:{source.id}:evt-replay",
        payload={
            "user_id": user.id,
            "source_id": source.id,
            "external_event_id": "evt-replay",
            "resolution_code": EventLinkAlertResolution.LINK_RELINKED.value,
            "note": "replay-safe",
        },
        event_id="review-link-alert-event-replay-1",
    )
    db_session.commit()

    processed = run_review_link_alert_events_tick(db_session, batch_limit=10)
    assert processed == 1

    db_session.refresh(outbox_row)
    outbox_row.status = OutboxStatus.PENDING
    outbox_row.processed_at = None
    db_session.commit()

    processed_again = run_review_link_alert_events_tick(db_session, batch_limit=10)
    assert processed_again == 1

    db_session.refresh(outbox_row)
    db_session.refresh(pair_alert)
    assert outbox_row.status == OutboxStatus.PROCESSED
    assert pair_alert.status == EventLinkAlertStatus.RESOLVED
    assert pair_alert.resolution_code == EventLinkAlertResolution.LINK_RELINKED

    inbox_count = db_session.scalar(
        select(func.count()).select_from(IntegrationInbox).where(
            IntegrationInbox.consumer_name == REVIEW_LINK_ALERTS_CONSUMER,
            IntegrationInbox.event_id == "review-link-alert-event-replay-1",
        )
    )
    assert int(inbox_count or 0) == 1
