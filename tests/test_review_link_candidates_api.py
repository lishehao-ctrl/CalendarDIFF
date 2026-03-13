from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import EventEntity, EventEntityLink, EventLinkBlock, EventLinkCandidate, EventLinkCandidateReason, EventLinkCandidateStatus, EventLinkOrigin
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key


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


def _create_family(db_session, *, user_id: int, canonical_label: str = "Homework") -> CourseWorkItemLabelFamily:
    family = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_dept="CSE",
        course_number=100,
        course_suffix=None,
        course_quarter=None,
        course_year2=None,
        normalized_course_identity=normalized_course_identity_key(
            course_dept="CSE",
            course_number=100,
            course_suffix=None,
            course_quarter=None,
            course_year2=None,
        ),
        canonical_label=canonical_label,
        normalized_canonical_label=normalize_label_token(canonical_label),
    )
    db_session.add(family)
    db_session.flush()
    return family


def _add_entity(db_session, *, user_id: int, entity_uid: str, family_id: int) -> None:
    db_session.add(
        EventEntity(
            user_id=user_id,
            entity_uid=entity_uid,
            course_dept="CSE",
            course_number=100,
            family_id=family_id,
            raw_type="Homework",
            event_name="Homework 1",
            ordinal=1,
            due_date=datetime(2026, 3, 12, tzinfo=timezone.utc).date(),
            time_precision="date_only",
        )
    )


def test_link_candidate_approve_creates_manual_link(client, db_session, auth_headers) -> None:
    user, source = _create_user_and_email_source(db_session)
    family = _create_family(db_session, user_id=user.id, canonical_label="Problem Set")
    _add_entity(db_session, user_id=user.id, entity_uid="ent_target_a", family_id=family.id)
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

    headers = auth_headers(client, user=user)
    response = client.get("/review/link-candidates?status=pending", headers=headers)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["proposed_entity"]["event_display"]["family_name"] == "Problem Set"
    candidate_id = rows[0]["id"]

    decide = client.post(
        f"/review/link-candidates/{candidate_id}/decisions",
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
        f"/review/link-candidates/{candidate_id}/decisions",
        headers=headers,
        json={"decision": "approve", "note": "noop"},
    )
    assert decide_again.status_code == 200
    assert decide_again.json()["idempotent"] is True


def test_link_candidate_reject_creates_block_and_unblock(client, db_session, auth_headers) -> None:
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

    headers = auth_headers(client, user=user)
    rows = client.get("/review/link-candidates?status=pending", headers=headers).json()
    assert len(rows) == 1
    candidate_id = rows[0]["id"]

    reject = client.post(
        f"/review/link-candidates/{candidate_id}/decisions",
        headers=headers,
        json={"decision": "reject", "note": "wrong binding"},
    )
    assert reject.status_code == 200
    reject_payload = reject.json()
    assert reject_payload["status"] == "rejected"
    assert reject_payload["idempotent"] is False
    assert isinstance(reject_payload["block_id"], int)

    blocks_resp = client.get("/review/link-candidates/blocks", headers=headers)
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

    delete_resp = client.delete(f"/review/link-candidates/blocks/{block_id}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"deleted": True, "id": block_id}

    blocks_after = client.get("/review/link-candidates/blocks", headers=headers)
    assert blocks_after.status_code == 200
    assert blocks_after.json() == []


def test_links_api_list_delete_and_relink(client, db_session, auth_headers) -> None:
    user, source = _create_user_and_email_source(db_session)
    family = _create_family(db_session, user_id=user.id, canonical_label="Homework")
    _add_entity(db_session, user_id=user.id, entity_uid="ent_target_a", family_id=family.id)
    _add_entity(db_session, user_id=user.id, entity_uid="ent_target_b", family_id=family.id)
    db_session.flush()
    db_session.add(
        EventEntityLink(
            user_id=user.id,
            source_id=source.id,
            source_kind=SourceKind.EMAIL,
            external_event_id="gmail-msg-link-1",
            entity_uid="ent_target_a",
            link_origin=EventLinkOrigin.AUTO,
            link_score=0.9,
            signals_json={"keywords": ["exam"]},
        )
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    links_resp = client.get("/review/links", headers=headers)
    assert links_resp.status_code == 200
    rows = links_resp.json()
    assert len(rows) == 1
    link_id = rows[0]["id"]
    assert rows[0]["entity_uid"] == "ent_target_a"
    assert rows[0]["link_origin"] == "auto"

    delete_resp = client.delete(f"/review/links/{link_id}", headers=headers)
    assert delete_resp.status_code == 200
    delete_payload = delete_resp.json()
    assert delete_payload["deleted"] is True
    assert delete_payload["id"] == link_id
    assert isinstance(delete_payload["block_id"], int)

    links_after_delete = client.get("/review/links", headers=headers)
    assert links_after_delete.status_code == 200
    assert links_after_delete.json() == []

    relink_resp = client.post(
        "/review/links/relink",
        headers=headers,
        json={
            "source_id": source.id,
            "external_event_id": "gmail-msg-link-1",
            "entity_uid": "ent_target_b",
            "clear_block": True,
            "note": "manual relink",
        },
    )
    assert relink_resp.status_code == 200
    relink_payload = relink_resp.json()
    assert relink_payload["entity_uid"] == "ent_target_b"
    assert relink_payload["source_id"] == source.id
    assert relink_payload["external_event_id"] == "gmail-msg-link-1"
    assert relink_payload["cleared_blocks"] >= 0

    final_links = client.get("/review/links", headers=headers)
    assert final_links.status_code == 200
    final_rows = final_links.json()
    assert len(final_rows) == 1
    assert final_rows[0]["entity_uid"] == "ent_target_b"


def test_link_candidate_batch_approve_partial_success(client, db_session, auth_headers) -> None:
    user, source = _create_user_and_email_source(db_session)
    family = _create_family(db_session, user_id=user.id, canonical_label="Homework")
    _add_entity(db_session, user_id=user.id, entity_uid="ent_batch_a", family_id=family.id)
    db_session.flush()

    candidate_ok = EventLinkCandidate(
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-batch-ok",
        proposed_entity_uid="ent_batch_a",
        score=0.91,
        score_breakdown_json={"rule_reason": "unique_match"},
        reason_code=EventLinkCandidateReason.SCORE_BAND,
        status=EventLinkCandidateStatus.PENDING,
    )
    candidate_invalid = EventLinkCandidate(
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-batch-invalid",
        proposed_entity_uid=None,
        score=0.5,
        score_breakdown_json={"rule_reason": "missing_entity"},
        reason_code=EventLinkCandidateReason.SCORE_BAND,
        status=EventLinkCandidateStatus.PENDING,
    )
    db_session.add(candidate_ok)
    db_session.add(candidate_invalid)
    db_session.commit()

    headers = auth_headers(client, user=user)
    resp = client.post(
        "/review/link-candidates/batch/decisions",
        headers=headers,
        json={
            "decision": "approve",
            "ids": [candidate_ok.id, candidate_invalid.id, 999999, candidate_ok.id],
            "note": "bulk approve",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["decision"] == "approve"
    assert payload["total_requested"] == 3
    assert payload["succeeded"] == 1
    assert payload["failed"] == 2

    by_id = {row["id"]: row for row in payload["results"]}
    assert by_id[candidate_ok.id]["ok"] is True
    assert by_id[candidate_ok.id]["status"] == "approved"
    assert by_id[candidate_ok.id]["idempotent"] is False
    assert isinstance(by_id[candidate_ok.id]["link_id"], int)
    assert by_id[candidate_ok.id]["block_id"] is None

    assert by_id[candidate_invalid.id]["ok"] is False
    assert by_id[candidate_invalid.id]["status"] is None
    assert by_id[candidate_invalid.id]["error_code"] == "invalid_state"

    assert by_id[999999]["ok"] is False
    assert by_id[999999]["error_code"] == "not_found"


def test_link_candidate_batch_reject_creates_blocks(client, db_session, auth_headers) -> None:
    user, source = _create_user_and_email_source(db_session)
    candidate_a = EventLinkCandidate(
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-batch-reject-a",
        proposed_entity_uid="ent_batch_reject_a",
        score=0.8,
        score_breakdown_json={"rule_reason": "manual_review"},
        reason_code=EventLinkCandidateReason.SCORE_BAND,
        status=EventLinkCandidateStatus.PENDING,
    )
    candidate_b = EventLinkCandidate(
        user_id=user.id,
        source_id=source.id,
        external_event_id="gmail-batch-reject-b",
        proposed_entity_uid="ent_batch_reject_b",
        score=0.82,
        score_breakdown_json={"rule_reason": "manual_review"},
        reason_code=EventLinkCandidateReason.SCORE_BAND,
        status=EventLinkCandidateStatus.PENDING,
    )
    db_session.add(candidate_a)
    db_session.add(candidate_b)
    db_session.commit()

    headers = auth_headers(client, user=user)
    resp = client.post(
        "/review/link-candidates/batch/decisions",
        headers=headers,
        json={
            "decision": "reject",
            "ids": [candidate_a.id, candidate_b.id],
            "note": "bulk reject",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["decision"] == "reject"
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0

    for row in payload["results"]:
        assert row["ok"] is True
        assert row["status"] == "rejected"
        assert row["idempotent"] is False
        assert row["link_id"] is None
        assert isinstance(row["block_id"], int)


def test_link_candidate_batch_decisions_validate_payload(client, db_session, auth_headers) -> None:
    user, _ = _create_user_and_email_source(db_session)
    headers = auth_headers(client, user=user)

    empty_ids = client.post(
        "/review/link-candidates/batch/decisions",
        headers=headers,
        json={"decision": "approve", "ids": []},
    )
    assert empty_ids.status_code == 422

    non_positive_id = client.post(
        "/review/link-candidates/batch/decisions",
        headers=headers,
        json={"decision": "approve", "ids": [0]},
    )
    assert non_positive_id.status_code == 422
