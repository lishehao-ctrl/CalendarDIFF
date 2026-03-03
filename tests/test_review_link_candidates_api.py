from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import (
    EventEntity,
    EventEntityLink,
    EventLinkBlock,
    EventLinkCandidate,
    EventLinkCandidateReason,
    EventLinkCandidateStatus,
    EventLinkOrigin,
    InputSource,
    SourceKind,
    User,
)


def _create_user_and_email_source(db_session) -> tuple[User, InputSource]:
    user = User(
        email="review-links-owner@example.com",
        notify_email="review-links-owner@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="review-links-gmail",
        display_name="Review Links Gmail",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.flush()
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def test_link_candidate_approve_creates_manual_link(client, db_session) -> None:
    user, source = _create_user_and_email_source(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="ent_target_a",
            course_best_json={"display_name": "CSE 151A WI26"},
            course_best_strength=5,
            course_aliases_json=[],
            title_aliases_json=[],
            metadata_json={},
        )
    )
    db_session.add(
        EventLinkCandidate(
            user_id=user.id,
            source_id=source.id,
            external_event_id="gmail-msg-approve-1",
            proposed_entity_uid="ent_target_a",
            score=0.78,
            score_breakdown_json={"total": 0.78, "incoming_signals": {"keywords": ["exam"]}},
            reason_code=EventLinkCandidateReason.SCORE_BAND,
            status=EventLinkCandidateStatus.PENDING,
        )
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    response = client.get("/v2/review-items/link-candidates?status=pending", headers=headers)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    candidate_id = rows[0]["id"]

    decide = client.post(
        f"/v2/review-items/link-candidates/{candidate_id}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "looks correct"},
    )
    assert decide.status_code == 200
    payload = decide.json()
    assert payload["status"] == "approved"
    assert payload["idempotent"] is False
    assert isinstance(payload["link_id"], int)

    link_row = db_session.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == user.id,
            EventEntityLink.source_id == source.id,
            EventEntityLink.external_event_id == "gmail-msg-approve-1",
        )
    )
    assert link_row is not None
    assert link_row.entity_uid == "ent_target_a"
    assert link_row.link_origin == EventLinkOrigin.MANUAL_CANDIDATE

    decide_again = client.post(
        f"/v2/review-items/link-candidates/{candidate_id}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "noop"},
    )
    assert decide_again.status_code == 200
    assert decide_again.json()["idempotent"] is True


def test_link_candidate_reject_creates_block_and_unblock(client, db_session) -> None:
    user, source = _create_user_and_email_source(db_session)
    db_session.add(
        EventLinkCandidate(
            user_id=user.id,
            source_id=source.id,
            external_event_id="gmail-msg-reject-1",
            proposed_entity_uid="ent_target_blocked",
            score=0.72,
            score_breakdown_json={"total": 0.72},
            reason_code=EventLinkCandidateReason.SCORE_BAND,
            status=EventLinkCandidateStatus.PENDING,
        )
    )
    db_session.commit()

    headers = {"X-API-Key": "test-api-key"}
    rows = client.get("/v2/review-items/link-candidates?status=pending", headers=headers).json()
    assert len(rows) == 1
    candidate_id = rows[0]["id"]

    reject = client.post(
        f"/v2/review-items/link-candidates/{candidate_id}/decisions",
        headers=headers,
        json={"decision": "reject", "note": "wrong binding"},
    )
    assert reject.status_code == 200
    reject_payload = reject.json()
    assert reject_payload["status"] == "rejected"
    assert reject_payload["idempotent"] is False
    assert isinstance(reject_payload["block_id"], int)

    blocks_resp = client.get("/v2/review-items/link-candidates/blocks", headers=headers)
    assert blocks_resp.status_code == 200
    blocks = blocks_resp.json()
    assert len(blocks) == 1
    block_id = blocks[0]["id"]

    block_row = db_session.scalar(
        select(EventLinkBlock).where(
            EventLinkBlock.id == block_id,
            EventLinkBlock.user_id == user.id,
        )
    )
    assert block_row is not None

    delete_resp = client.delete(f"/v2/review-items/link-candidates/blocks/{block_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"deleted": True, "id": block_id}

    blocks_after = client.get("/v2/review-items/link-candidates/blocks", headers=headers)
    assert blocks_after.status_code == 200
    assert blocks_after.json() == []
