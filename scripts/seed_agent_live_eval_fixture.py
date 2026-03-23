#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.models.input import IngestTriggerType, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeSourceRef, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.db.session import get_session_factory
from app.modules.auth.service import register_user
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


DEFAULT_NOTIFY_EMAIL = "agent-live-eval@example.com"
DEFAULT_PASSWORD = "password123"
DEFAULT_TIMEZONE = "America/Los_Angeles"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed a repeatable local fixture user for agent live eval runs.")
    parser.add_argument("--notify-email", default=DEFAULT_NOTIFY_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--course", default="CSE 160 WI26")
    parser.add_argument("--reset", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session_factory = get_session_factory()
    with session_factory() as db:
        user = db.scalar(select(User).where(User.notify_email == args.notify_email).limit(1))
        if user is not None and bool(args.reset):
            db.delete(user)
            db.commit()
            user = None
        if user is None:
            user = register_user(
                db,
                notify_email=str(args.notify_email),
                password=str(args.password),
                timezone_name=str(args.timezone),
            )
        source = create_input_source(
            db,
            user=user,
            payload=InputSourceCreateRequest(
                source_kind="calendar",
                provider="ics",
                display_name="Agent Live Eval Canvas ICS",
                config={"monitor_since": "2026-01-05"},
                secrets={"url": "https://example.com/agent-live-eval/calendar.ics"},
            ),
        )
        disconnected_gmail_source = create_input_source(
            db,
            user=user,
            payload=InputSourceCreateRequest(
                source_kind="email",
                provider="gmail",
                display_name="Agent Live Eval Gmail",
                config={"label_id": "INBOX", "monitor_since": "2026-01-05"},
                secrets={},
            ),
        )
        family = create_family(
            db,
            user_id=user.id,
            course_display=str(args.course),
            canonical_label="Homework",
        )
        seed_changes(db, user_id=user.id, source_id=source.id, family_id=family.id)
        seed_failed_sync(db, source_id=source.id)
        db.refresh(user)
        db.refresh(source)
        db.refresh(disconnected_gmail_source)
        payload = {
            "user_id": user.id,
            "notify_email": user.notify_email,
            "password": args.password,
            "timezone_name": user.timezone_name,
            "source_id": source.id,
            "disconnected_gmail_source_id": disconnected_gmail_source.id,
            "family_id": family.id,
            "pending_change_ids": [
                row.id
                for row in db.scalars(
                    select(Change)
                    .where(Change.user_id == user.id, Change.review_status == ReviewStatus.PENDING)
                    .order_by(Change.detected_at.desc(), Change.id.desc())
                ).all()
            ],
            "reviewed_change_ids": [
                row.id
                for row in db.scalars(
                    select(Change)
                    .where(Change.user_id == user.id, Change.review_status != ReviewStatus.PENDING)
                    .order_by(Change.detected_at.desc(), Change.id.desc())
                ).all()
            ],
            "failed_request_ids": [
                row.request_id
                for row in db.scalars(
                    select(SyncRequest)
                    .where(SyncRequest.source_id == source.id, SyncRequest.status == SyncRequestStatus.FAILED)
                    .order_by(SyncRequest.created_at.desc(), SyncRequest.id.desc())
                ).all()
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def create_family(db, *, user_id: int, course_display: str, canonical_label: str) -> CourseWorkItemLabelFamily:
    parsed = parse_course_display(course_display)
    family = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_dept=parsed["course_dept"],
        course_number=parsed["course_number"],
        course_suffix=parsed["course_suffix"],
        course_quarter=parsed["course_quarter"],
        course_year2=parsed["course_year2"],
        normalized_course_identity=normalized_course_identity_key(
            course_dept=parsed["course_dept"],
            course_number=parsed["course_number"],
            course_suffix=parsed["course_suffix"],
            course_quarter=parsed["course_quarter"],
            course_year2=parsed["course_year2"],
        ),
        canonical_label=canonical_label,
        normalized_canonical_label=normalize_label_token(canonical_label),
    )
    db.add(family)
    db.commit()
    db.refresh(family)
    return family


def seed_changes(db, *, user_id: int, source_id: int, family_id: int) -> None:
    now = datetime.now(UTC)
    baseline_change = Change(
        user_id=user_id,
        entity_uid="agent-live-eval-baseline",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.CREATED,
        intake_phase=ChangeIntakePhase.BASELINE,
        review_bucket=ChangeReviewBucket.INITIAL_REVIEW,
        detected_at=now - timedelta(minutes=10),
        after_semantic_json={
            "uid": "agent-live-eval-baseline",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 1",
            "ordinal": 1,
            "due_date": "2026-03-20",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        review_status=ReviewStatus.PENDING,
    )
    primary_replay_change = Change(
        user_id=user_id,
        entity_uid="agent-live-eval-replay",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=now - timedelta(minutes=5),
        before_semantic_json={
            "uid": "agent-live-eval-replay",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 2",
            "ordinal": 2,
            "due_date": "2026-03-21",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        after_semantic_json={
            "uid": "agent-live-eval-replay",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 2",
            "ordinal": 2,
            "due_date": "2026-03-22",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        before_evidence_json={"provider": "ics"},
        after_evidence_json={"provider": "ics"},
        review_status=ReviewStatus.PENDING,
    )
    repeat_change = Change(
        user_id=user_id,
        entity_uid="agent-live-eval-repeat",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=now - timedelta(minutes=4),
        before_semantic_json={
            "uid": "agent-live-eval-repeat",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 3",
            "ordinal": 3,
            "due_date": "2026-03-23",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        after_semantic_json={
            "uid": "agent-live-eval-repeat",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 3",
            "ordinal": 3,
            "due_date": "2026-03-24",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        before_evidence_json={"provider": "ics"},
        after_evidence_json={"provider": "ics"},
        review_status=ReviewStatus.PENDING,
    )
    drift_change = Change(
        user_id=user_id,
        entity_uid="agent-live-eval-drift",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=now - timedelta(minutes=3),
        before_semantic_json={
            "uid": "agent-live-eval-drift",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 4",
            "ordinal": 4,
            "due_date": "2026-03-25",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        after_semantic_json={
            "uid": "agent-live-eval-drift",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 4",
            "ordinal": 4,
            "due_date": "2026-03-26",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        before_evidence_json={"provider": "ics"},
        after_evidence_json={"provider": "ics"},
        review_status=ReviewStatus.PENDING,
    )
    reviewed_change = Change(
        user_id=user_id,
        entity_uid="agent-live-eval-reviewed",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.CREATED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=now - timedelta(minutes=2),
        after_semantic_json={
            "uid": "agent-live-eval-reviewed",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "event_name": "Homework 5",
            "ordinal": 5,
            "due_date": "2026-03-27",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        review_status=ReviewStatus.APPROVED,
        reviewed_at=now - timedelta(minutes=1),
    )
    db.add_all([baseline_change, primary_replay_change, repeat_change, drift_change, reviewed_change])
    db.flush()
    db.add_all(
        [
            ChangeSourceRef(
                change_id=baseline_change.id,
                position=0,
                source_id=source_id,
                source_kind="calendar",
                provider="ics",
                external_event_id="evt-agent-live-eval-baseline",
                confidence=0.95,
            ),
            ChangeSourceRef(
                change_id=primary_replay_change.id,
                position=0,
                source_id=source_id,
                source_kind="calendar",
                provider="ics",
                external_event_id="evt-agent-live-eval-replay",
                confidence=0.95,
            ),
            ChangeSourceRef(
                change_id=repeat_change.id,
                position=0,
                source_id=source_id,
                source_kind="calendar",
                provider="ics",
                external_event_id="evt-agent-live-eval-repeat",
                confidence=0.95,
            ),
            ChangeSourceRef(
                change_id=drift_change.id,
                position=0,
                source_id=source_id,
                source_kind="calendar",
                provider="ics",
                external_event_id="evt-agent-live-eval-drift",
                confidence=0.95,
            ),
            ChangeSourceRef(
                change_id=reviewed_change.id,
                position=0,
                source_id=source_id,
                source_kind="calendar",
                provider="ics",
                external_event_id="evt-agent-live-eval-reviewed",
                confidence=0.95,
            ),
        ]
    )
    db.commit()


def seed_failed_sync(db, *, source_id: int) -> None:
    now = datetime.now(UTC)
    request = SyncRequest(
        request_id=f"agent-live-eval-sync-{int(now.timestamp())}",
        source_id=source_id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.FAILED,
        stage=SyncRequestStage.FAILED,
        substage="connector_failed",
        stage_updated_at=now,
        progress_json={
            "phase": "connector_fetch",
            "label": "Fetch failed",
            "detail": "Simulated failed sync for agent live eval.",
            "current": None,
            "total": None,
            "percent": None,
            "unit": None,
            "updated_at": now.isoformat(),
        },
        idempotency_key=f"idemp:agent-live-eval:{int(now.timestamp())}",
        error_code="agent_live_eval_seeded_failure",
        error_message="Simulated failed sync for agent live eval.",
        metadata_json={"seeded_by": "seed_agent_live_eval_fixture"},
    )
    db.add(request)
    db.commit()


if __name__ == "__main__":
    main()
