#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.review import Change, ReviewStatus, SourceEventObservation
from app.db.schema_guard import ensure_schema_ready
from app.db.session import get_engine, get_session_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal retention cleanup for inactive observations and old rejected changes."
    )
    parser.add_argument(
        "--inactive-observations-days",
        type=int,
        default=30,
        help="Delete inactive source_event_observations older than this window.",
    )
    parser.add_argument(
        "--rejected-changes-days",
        type=int,
        default=90,
        help="Delete rejected changes older than this window (reviewed_at fallback detected_at).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Deletion batch size per transaction.",
    )
    parser.add_argument(
        "--max-delete-per-run",
        type=int,
        default=50000,
        help="Guardrail: refuse apply when total candidates exceed this number.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--apply", action="store_true", help="Apply deletes (default is dry-run).")
    mode_group.add_argument("--dry-run", action="store_true", help="Force dry-run mode.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if args.inactive_observations_days <= 0:
        raise ValueError("--inactive-observations-days must be greater than 0")
    if args.rejected_changes_days <= 0:
        raise ValueError("--rejected-changes-days must be greater than 0")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than 0")
    if args.max_delete_per_run <= 0:
        raise ValueError("--max-delete-per-run must be greater than 0")


def _count_candidates(db: Session, *, cutoff_obs: datetime, cutoff_changes: datetime) -> tuple[int, int]:
    observation_count = int(
        db.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.is_active.is_(False),
                SourceEventObservation.observed_at < cutoff_obs,
            )
        )
        or 0
    )

    rejected_count = int(
        db.scalar(
            select(func.count(Change.id)).where(
                Change.review_status == ReviewStatus.REJECTED,
                func.coalesce(Change.reviewed_at, Change.detected_at) < cutoff_changes,
            )
        )
        or 0
    )

    return observation_count, rejected_count


def _delete_observations_in_batches(db: Session, *, cutoff_obs: datetime, batch_size: int) -> int:
    deleted_total = 0
    while True:
        ids = db.scalars(
            select(SourceEventObservation.id)
            .where(
                SourceEventObservation.is_active.is_(False),
                SourceEventObservation.observed_at < cutoff_obs,
            )
            .order_by(SourceEventObservation.id.asc())
            .limit(batch_size)
        ).all()
        if not ids:
            break

        result = db.execute(delete(SourceEventObservation).where(SourceEventObservation.id.in_(ids)))
        db.commit()
        row_count = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(ids)
        deleted_total += int(row_count)

    return deleted_total


def _delete_rejected_changes_in_batches(db: Session, *, cutoff_changes: datetime, batch_size: int) -> int:
    deleted_total = 0
    while True:
        ids = db.scalars(
            select(Change.id)
            .where(
                Change.review_status == ReviewStatus.REJECTED,
                func.coalesce(Change.reviewed_at, Change.detected_at) < cutoff_changes,
            )
            .order_by(Change.id.asc())
            .limit(batch_size)
        ).all()
        if not ids:
            break

        result = db.execute(delete(Change).where(Change.id.in_(ids)))
        db.commit()
        row_count = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(ids)
        deleted_total += int(row_count)

    return deleted_total


def _render_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=True))
        return

    print("ops_retention_minimal summary")
    print(f"  dry_run: {result['dry_run']}")
    print(f"  cutoff_inactive_observations: {result['cutoff_inactive_observations']}")
    print(f"  cutoff_rejected_changes: {result['cutoff_rejected_changes']}")
    print(f"  candidate_inactive_observations: {result['candidate_inactive_observations']}")
    print(f"  candidate_rejected_changes: {result['candidate_rejected_changes']}")
    print(f"  deleted_inactive_observations: {result['deleted_inactive_observations']}")
    print(f"  deleted_rejected_changes: {result['deleted_rejected_changes']}")


def run(args: argparse.Namespace) -> int:
    _validate_args(args)
    apply_mode = bool(args.apply) and not bool(args.dry_run)

    settings = get_settings()
    if settings.schema_guard_enabled:
        ensure_schema_ready(get_engine(), force_refresh=True)

    now = datetime.now(UTC)
    cutoff_obs = now - timedelta(days=args.inactive_observations_days)
    cutoff_changes = now - timedelta(days=args.rejected_changes_days)

    session_factory = get_session_factory()
    with session_factory() as db:
        candidate_obs, candidate_rejected = _count_candidates(
            db,
            cutoff_obs=cutoff_obs,
            cutoff_changes=cutoff_changes,
        )
        candidate_total = candidate_obs + candidate_rejected

        if apply_mode and candidate_total > args.max_delete_per_run:
            result = {
                "dry_run": False,
                "cutoff_inactive_observations": cutoff_obs.isoformat(),
                "cutoff_rejected_changes": cutoff_changes.isoformat(),
                "candidate_inactive_observations": candidate_obs,
                "candidate_rejected_changes": candidate_rejected,
                "deleted_inactive_observations": 0,
                "deleted_rejected_changes": 0,
                "guardrail_triggered": True,
                "guardrail_message": (
                    "candidate deletes exceed max_delete_per_run "
                    f"(candidates={candidate_total}, max={args.max_delete_per_run})"
                ),
            }
            _render_result(result, as_json=args.json)
            return 1

        deleted_obs = 0
        deleted_rejected = 0
        if apply_mode:
            try:
                deleted_obs = _delete_observations_in_batches(
                    db,
                    cutoff_obs=cutoff_obs,
                    batch_size=args.batch_size,
                )
                deleted_rejected = _delete_rejected_changes_in_batches(
                    db,
                    cutoff_changes=cutoff_changes,
                    batch_size=args.batch_size,
                )
            except Exception:
                db.rollback()
                raise

        result = {
            "dry_run": not apply_mode,
            "cutoff_inactive_observations": cutoff_obs.isoformat(),
            "cutoff_rejected_changes": cutoff_changes.isoformat(),
            "candidate_inactive_observations": candidate_obs,
            "candidate_rejected_changes": candidate_rejected,
            "deleted_inactive_observations": deleted_obs,
            "deleted_rejected_changes": deleted_rejected,
            "guardrail_triggered": False,
            "guardrail_message": None,
        }
        _render_result(result, as_json=args.json)
        return 0


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except Exception as exc:
        payload = {
            "error": str(exc),
            "dry_run": not bool(args.apply),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print(f"ops_retention_minimal failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
