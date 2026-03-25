from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.review import Change, ChangeOrigin, ChangeType, ReviewStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus, User
from app.modules.runtime.apply.pending_change_outbox import emit_change_pending_created_event


def _seed_user_and_changes(db_session) -> tuple[User, list[Change]]:
    now = datetime.now(timezone.utc)
    user = User(email="pending-outbox@example.com")
    db_session.add(user)
    db_session.flush()

    changes = [
        Change(
            user_id=user.id,
            entity_uid="evt-1",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.CREATED,
            detected_at=now,
            before_semantic_json=None,
            after_semantic_json={"uid": "evt-1", "event_name": "Quiz 1", "due_date": "2026-03-01", "time_precision": "date_only"},
            review_status=ReviewStatus.PENDING,
        ),
        Change(
            user_id=user.id,
            entity_uid="evt-2",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.DUE_CHANGED,
            detected_at=now,
            before_semantic_json={"uid": "evt-2", "event_name": "Quiz 2", "due_date": "2026-03-01", "time_precision": "date_only"},
            after_semantic_json={"uid": "evt-2", "event_name": "Quiz 2", "due_date": "2026-03-02", "time_precision": "date_only"},
            delta_seconds=86400,
            review_status=ReviewStatus.PENDING,
        ),
    ]
    db_session.add_all(changes)
    db_session.commit()
    for change in changes:
        db_session.refresh(change)
    return user, changes


def test_emit_change_pending_created_event_contract(db_session) -> None:
    user, changes = _seed_user_and_changes(db_session)
    detected_at = datetime.now(timezone.utc)

    emit_change_pending_created_event(
        db=db_session,
        user_id=user.id,
        changes=changes,
        detected_at=detected_at,
    )
    db_session.commit()

    row = db_session.scalar(
        select(IntegrationOutbox).where(
            IntegrationOutbox.event_type == "changes.pending.created",
            IntegrationOutbox.aggregate_type == "change_batch",
        )
    )
    assert row is not None
    assert row.status == OutboxStatus.PENDING
    assert row.aggregate_id == str(changes[0].id)
    payload = row.payload_json
    assert isinstance(payload, dict)
    assert payload.get("user_id") == user.id
    assert payload.get("change_ids") == [changes[0].id, changes[1].id]
    assert payload.get("deliver_after") == detected_at.isoformat()
