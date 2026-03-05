from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.review import Change, ChangeType, Input, InputType, ReviewStatus
from app.db.models.shared import IntegrationOutbox, OutboxStatus, User
from app.modules.core_ingest.pending_review_outbox import emit_review_pending_created_event


def _seed_input_and_changes(db_session) -> tuple[Input, list[Change]]:
    now = datetime.now(timezone.utc)
    user = User(email="pending-outbox@example.com", notify_email="pending-outbox@example.com")
    db_session.add(user)
    db_session.flush()
    input_row = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    db_session.add(input_row)
    db_session.flush()

    changes = [
        Change(
            input_id=input_row.id,
            event_uid="evt-1",
            change_type=ChangeType.CREATED,
            detected_at=now,
            before_json=None,
            after_json={"uid": "evt-1"},
            delta_seconds=None,
            review_status=ReviewStatus.PENDING,
            reviewed_at=None,
            review_note=None,
            reviewed_by_user_id=None,
            proposal_merge_key="evt-1",
            proposal_sources_json=[],
        ),
        Change(
            input_id=input_row.id,
            event_uid="evt-2",
            change_type=ChangeType.DUE_CHANGED,
            detected_at=now,
            before_json={"uid": "evt-2", "start_at_utc": "2026-03-01T10:00:00+00:00"},
            after_json={"uid": "evt-2", "start_at_utc": "2026-03-01T12:00:00+00:00"},
            delta_seconds=7200,
            review_status=ReviewStatus.PENDING,
            reviewed_at=None,
            review_note=None,
            reviewed_by_user_id=None,
            proposal_merge_key="evt-2",
            proposal_sources_json=[],
        ),
    ]
    db_session.add_all(changes)
    db_session.commit()
    for change in changes:
        db_session.refresh(change)
    return input_row, changes


def test_emit_review_pending_created_event_contract(db_session) -> None:
    input_row, changes = _seed_input_and_changes(db_session)
    detected_at = datetime.now(timezone.utc)

    emit_review_pending_created_event(
        db=db_session,
        canonical_input_id=input_row.id,
        changes=changes,
        detected_at=detected_at,
    )
    db_session.commit()

    row = db_session.scalar(
        select(IntegrationOutbox).where(
            IntegrationOutbox.event_type == "review.pending.created",
            IntegrationOutbox.aggregate_type == "change_batch",
        )
    )
    assert row is not None
    assert row.status == OutboxStatus.PENDING
    assert row.aggregate_id == str(changes[0].id)
    assert isinstance(row.payload_json, dict)
    payload = row.payload_json
    assert payload.get("input_id") == input_row.id
    assert payload.get("change_ids") == [changes[0].id, changes[1].id]
    assert payload.get("deliver_after") == detected_at.isoformat()
