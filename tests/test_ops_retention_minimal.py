from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeType, Input, InputType, ReviewStatus, SourceEventObservation
from app.db.models.shared import User


def _run_retention_script(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    return subprocess.run(
        [sys.executable, "scripts/ops_retention_minimal.py", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _read_json_output(result: subprocess.CompletedProcess[str]) -> dict:
    stdout = result.stdout.strip()
    assert stdout
    return json.loads(stdout.splitlines()[-1])


def _seed_retention_rows(db_session: Session) -> tuple[int, int]:
    now = datetime.now(UTC)
    user = User(
        email="retention@example.com",
        notify_email="retention@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="retention-source",
        display_name="Retention Source",
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.flush()

    canonical_input = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key=f"canonical:user:{user.id}",
        is_active=True,
    )
    db_session.add(canonical_input)
    db_session.flush()

    obs_old_inactive = SourceEventObservation(
        user_id=user.id,
        source_id=source.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        external_event_id="obs-old-inactive",
        merge_key="mk-old-inactive",
        event_payload={"uid": "obs-old-inactive"},
        event_hash="hash-old-inactive",
        observed_at=now - timedelta(days=45),
        is_active=False,
        last_request_id="req-old",
    )
    obs_recent_inactive = SourceEventObservation(
        user_id=user.id,
        source_id=source.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        external_event_id="obs-recent-inactive",
        merge_key="mk-recent-inactive",
        event_payload={"uid": "obs-recent-inactive"},
        event_hash="hash-recent-inactive",
        observed_at=now - timedelta(days=5),
        is_active=False,
        last_request_id="req-recent",
    )
    obs_old_active = SourceEventObservation(
        user_id=user.id,
        source_id=source.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        external_event_id="obs-old-active",
        merge_key="mk-old-active",
        event_payload={"uid": "obs-old-active"},
        event_hash="hash-old-active",
        observed_at=now - timedelta(days=60),
        is_active=True,
        last_request_id="req-active",
    )
    db_session.add_all([obs_old_inactive, obs_recent_inactive, obs_old_active])

    rejected_old = Change(
        input_id=canonical_input.id,
        event_uid="chg-rejected-old",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now - timedelta(days=120),
        before_json=None,
        after_json=None,
        delta_seconds=None,
        review_status=ReviewStatus.REJECTED,
        reviewed_at=now - timedelta(days=120),
        review_note="old reject",
        proposal_merge_key="mk-rejected-old",
        proposal_sources_json=[{"source_id": source.id, "source_kind": "calendar"}],
    )
    rejected_recent = Change(
        input_id=canonical_input.id,
        event_uid="chg-rejected-recent",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now - timedelta(days=30),
        before_json=None,
        after_json=None,
        delta_seconds=None,
        review_status=ReviewStatus.REJECTED,
        reviewed_at=now - timedelta(days=30),
        review_note="recent reject",
        proposal_merge_key="mk-rejected-recent",
        proposal_sources_json=[{"source_id": source.id, "source_kind": "calendar"}],
    )
    pending_old = Change(
        input_id=canonical_input.id,
        event_uid="chg-pending-old",
        change_type=ChangeType.DUE_CHANGED,
        detected_at=now - timedelta(days=200),
        before_json=None,
        after_json=None,
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key="mk-pending-old",
        proposal_sources_json=[{"source_id": source.id, "source_kind": "calendar"}],
    )
    db_session.add_all([rejected_old, rejected_recent, pending_old])
    db_session.commit()

    return user.id, source.id


def _count_old_inactive_observations(db_session: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=30)
    return int(
        db_session.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.is_active.is_(False),
                SourceEventObservation.observed_at < cutoff,
            )
        )
        or 0
    )


def _count_old_rejected_changes(db_session: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=90)
    return int(
        db_session.scalar(
            select(func.count(Change.id)).where(
                Change.review_status == ReviewStatus.REJECTED,
                func.coalesce(Change.reviewed_at, Change.detected_at) < cutoff,
            )
        )
        or 0
    )


def test_ops_retention_minimal_dry_run_and_apply(db_session: Session) -> None:
    _seed_retention_rows(db_session)

    dry_run = _run_retention_script("--dry-run", "--json")
    assert dry_run.returncode == 0, dry_run.stderr or dry_run.stdout
    dry_payload = _read_json_output(dry_run)
    assert dry_payload["dry_run"] is True
    assert dry_payload["candidate_inactive_observations"] == 1
    assert dry_payload["candidate_rejected_changes"] == 1
    assert dry_payload["deleted_inactive_observations"] == 0
    assert dry_payload["deleted_rejected_changes"] == 0

    db_session.expire_all()
    assert _count_old_inactive_observations(db_session) == 1
    assert _count_old_rejected_changes(db_session) == 1

    apply_run = _run_retention_script("--apply", "--batch-size", "1", "--json")
    assert apply_run.returncode == 0, apply_run.stderr or apply_run.stdout
    apply_payload = _read_json_output(apply_run)
    assert apply_payload["dry_run"] is False
    assert apply_payload["deleted_inactive_observations"] == 1
    assert apply_payload["deleted_rejected_changes"] == 1

    db_session.expire_all()
    assert _count_old_inactive_observations(db_session) == 0
    assert _count_old_rejected_changes(db_session) == 0

    remaining_pending = db_session.scalar(
        select(func.count(Change.id)).where(Change.review_status == ReviewStatus.PENDING)
    )
    assert int(remaining_pending or 0) == 1


def test_ops_retention_minimal_guardrail_blocks_large_apply(db_session: Session) -> None:
    now = datetime.now(UTC)
    user = User(
        email="retention-guard@example.com",
        notify_email="retention-guard@example.com",
        onboarding_completed_at=now,
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="retention-guard-source",
        display_name="Retention Guard Source",
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.flush()

    db_session.add_all(
        [
            SourceEventObservation(
                user_id=user.id,
                source_id=source.id,
                source_kind=SourceKind.CALENDAR,
                provider="ics",
                external_event_id="guard-obs-1",
                merge_key="guard-mk-1",
                event_payload={"uid": "guard-obs-1"},
                event_hash="guard-hash-1",
                observed_at=now - timedelta(days=40),
                is_active=False,
                last_request_id="guard-req-1",
            ),
            SourceEventObservation(
                user_id=user.id,
                source_id=source.id,
                source_kind=SourceKind.CALENDAR,
                provider="ics",
                external_event_id="guard-obs-2",
                merge_key="guard-mk-2",
                event_payload={"uid": "guard-obs-2"},
                event_hash="guard-hash-2",
                observed_at=now - timedelta(days=41),
                is_active=False,
                last_request_id="guard-req-2",
            ),
        ]
    )
    db_session.commit()

    guard_run = _run_retention_script("--apply", "--max-delete-per-run", "1", "--json")
    assert guard_run.returncode == 1
    guard_payload = _read_json_output(guard_run)
    assert guard_payload["guardrail_triggered"] is True
    assert guard_payload["deleted_inactive_observations"] == 0
    assert guard_payload["deleted_rejected_changes"] == 0

    db_session.expire_all()
    remaining = int(
        db_session.scalar(
            select(func.count(SourceEventObservation.id)).where(SourceEventObservation.is_active.is_(False))
        )
        or 0
    )
    assert remaining == 2
