from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Change, ChangeType, Input, InputSource, InputType, ReviewStatus, SourceKind, User


def _run_cleanup_script(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    return subprocess.run(
        [sys.executable, "scripts/ops_cleanup_smoke_state.py", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _read_json_output(result: subprocess.CompletedProcess[str]) -> dict:
    stdout = result.stdout.strip()
    assert stdout
    return json.loads(stdout.splitlines()[-1])


def _seed_pending_changes(db_session: Session) -> tuple[int, int, int, int]:
    now = datetime.now(UTC)
    user = User(
        email="cleanup@example.com",
        notify_email="cleanup@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source_a = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="cleanup-source-a",
        display_name="Cleanup Source A",
        poll_interval_seconds=900,
    )
    source_b = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key="cleanup-source-b",
        display_name="Cleanup Source B",
        poll_interval_seconds=900,
    )
    db_session.add_all([source_a, source_b])
    db_session.flush()

    canonical_input = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    db_session.add(canonical_input)
    db_session.flush()

    both_sources_pending = Change(
        input_id=canonical_input.id,
        event_uid="evt-both",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now - timedelta(hours=2),
        before_json=None,
        after_json={"uid": "evt-both"},
        delta_seconds=3600,
        review_status=ReviewStatus.PENDING,
        proposal_sources_json=[
            {"source_id": source_a.id, "source_kind": "calendar"},
            {"source_id": source_b.id, "source_kind": "email"},
        ],
        proposal_merge_key="mk-both",
    )
    source_b_pending = Change(
        input_id=canonical_input.id,
        event_uid="evt-b",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now - timedelta(hours=1),
        before_json=None,
        after_json={"uid": "evt-b"},
        delta_seconds=1200,
        review_status=ReviewStatus.PENDING,
        proposal_sources_json=[
            {"source_id": source_b.id, "source_kind": "email"},
        ],
        proposal_merge_key="mk-b",
    )
    source_a_approved = Change(
        input_id=canonical_input.id,
        event_uid="evt-a-approved",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now,
        before_json=None,
        after_json={"uid": "evt-a-approved"},
        delta_seconds=600,
        review_status=ReviewStatus.APPROVED,
        proposal_sources_json=[
            {"source_id": source_a.id, "source_kind": "calendar"},
        ],
        proposal_merge_key="mk-a-approved",
    )
    db_session.add_all([both_sources_pending, source_b_pending, source_a_approved])
    db_session.commit()

    return source_a.id, source_b.id, both_sources_pending.id, source_b_pending.id


def test_ops_cleanup_smoke_state_dry_run_apply_and_idempotent(db_session: Session) -> None:
    source_a_id, source_b_id, change_both_id, change_b_id = _seed_pending_changes(db_session)

    dry_run = _run_cleanup_script("--source-id", str(source_a_id), "--json")
    assert dry_run.returncode == 0, dry_run.stderr or dry_run.stdout
    dry_payload = _read_json_output(dry_run)
    assert dry_payload["dry_run"] is True
    assert dry_payload["matched_count"] == 1
    assert dry_payload["updated_count"] == 0
    assert dry_payload["matched_change_ids"] == [change_both_id]

    db_session.expire_all()
    statuses_after_dry = {
        row.id: row.review_status
        for row in db_session.scalars(
            select(Change).where(Change.id.in_([change_both_id, change_b_id])).order_by(Change.id.asc())
        ).all()
    }
    assert statuses_after_dry[change_both_id] == ReviewStatus.PENDING
    assert statuses_after_dry[change_b_id] == ReviewStatus.PENDING

    apply_run = _run_cleanup_script(
        "--source-id",
        str(source_a_id),
        "--apply",
        "--json",
    )
    assert apply_run.returncode == 0, apply_run.stderr or apply_run.stdout
    apply_payload = _read_json_output(apply_run)
    assert apply_payload["dry_run"] is False
    assert apply_payload["matched_count"] == 1
    assert apply_payload["updated_count"] == 1
    assert apply_payload["matched_change_ids"] == [change_both_id]
    assert str(source_a_id) in apply_payload["source_id_hits"]
    assert apply_payload["review_note_applied"].startswith("ops_smoke_cleanup:")

    db_session.expire_all()
    updated_rows = {
        row.id: row
        for row in db_session.scalars(
            select(Change).where(Change.id.in_([change_both_id, change_b_id])).order_by(Change.id.asc())
        ).all()
    }
    assert updated_rows[change_both_id].review_status == ReviewStatus.REJECTED
    assert updated_rows[change_both_id].review_note.startswith("ops_smoke_cleanup:")
    assert updated_rows[change_b_id].review_status == ReviewStatus.PENDING

    idempotent_run = _run_cleanup_script(
        "--source-id",
        str(source_a_id),
        "--apply",
        "--json",
    )
    assert idempotent_run.returncode == 0, idempotent_run.stderr or idempotent_run.stdout
    idempotent_payload = _read_json_output(idempotent_run)
    assert idempotent_payload["matched_count"] == 0
    assert idempotent_payload["updated_count"] == 0

    # source B can still be cleaned independently.
    apply_source_b = _run_cleanup_script("--source-id", str(source_b_id), "--apply", "--json")
    assert apply_source_b.returncode == 0
    source_b_payload = _read_json_output(apply_source_b)
    assert source_b_payload["updated_count"] == 1
    assert source_b_payload["matched_change_ids"] == [change_b_id]


def test_ops_cleanup_smoke_state_requires_source_id() -> None:
    result = _run_cleanup_script("--json")
    assert result.returncode == 1
