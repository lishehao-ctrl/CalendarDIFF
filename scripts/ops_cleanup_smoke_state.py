#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.db.models.review import Change, ReviewStatus
from app.db.schema_guard import ensure_schema_ready
from app.db.session import get_engine, get_session_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cleanup smoke pending review items by source_id (pending -> rejected)."
    )
    parser.add_argument(
        "--source-id",
        dest="source_ids",
        action="append",
        type=int,
        default=[],
        help="Target source_id. Can be repeated.",
    )
    parser.add_argument(
        "--note",
        default="ops_smoke_cleanup",
        help="Review note prefix. Timestamp is appended automatically on apply.",
    )
    parser.add_argument(
        "--reviewed-by-user-id",
        type=int,
        default=None,
        help="Optional reviewed_by_user_id to stamp on rejected rows.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2000,
        help="Max number of pending rows to inspect in one run.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--apply", action="store_true", help="Apply changes (default is dry-run).")
    mode_group.add_argument("--dry-run", action="store_true", help="Force dry-run mode.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    return parser.parse_args()


def _extract_source_ids(raw_sources: object) -> set[int]:
    if not isinstance(raw_sources, list):
        return set()
    out: set[int] = set()
    for item in raw_sources:
        if isinstance(item, dict) and isinstance(item.get("source_id"), int):
            out.add(int(item["source_id"]))
    return out


def _validate_args(args: argparse.Namespace) -> set[int]:
    if args.limit <= 0:
        raise ValueError("--limit must be greater than 0")
    if not args.source_ids:
        raise ValueError("at least one --source-id is required")
    source_ids = {int(value) for value in args.source_ids}
    if any(value <= 0 for value in source_ids):
        raise ValueError("--source-id must be positive")
    if args.reviewed_by_user_id is not None and args.reviewed_by_user_id <= 0:
        raise ValueError("--reviewed-by-user-id must be positive")
    return source_ids


def _query_candidates(db: Session, *, limit: int, target_source_ids: set[int]) -> tuple[list[Change], dict[int, int], bool]:
    rows = db.scalars(
        select(Change)
        .where(Change.review_status == ReviewStatus.PENDING)
        .order_by(Change.id.asc())
        .limit(limit + 1)
    ).all()

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    matched: list[Change] = []
    source_hits: dict[int, int] = {}
    for row in rows:
        row_source_ids = _extract_source_ids(row.proposal_sources_json)
        hit_ids = sorted(row_source_ids.intersection(target_source_ids))
        if not hit_ids:
            continue
        matched.append(row)
        for source_id in hit_ids:
            source_hits[source_id] = source_hits.get(source_id, 0) + 1

    return matched, source_hits, truncated


def _render_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=True))
        return

    print("ops_cleanup_smoke_state summary")
    print(f"  dry_run: {result['dry_run']}")
    print(f"  source_ids: {result['source_ids']}")
    print(f"  limit: {result['limit']}")
    print(f"  truncated: {result['truncated']}")
    print(f"  matched_count: {result['matched_count']}")
    print(f"  updated_count: {result['updated_count']}")
    print(f"  matched_change_ids: {result['matched_change_ids']}")
    print(f"  source_id_hits: {result['source_id_hits']}")
    if result.get("review_note_applied") is not None:
        print(f"  review_note_applied: {result['review_note_applied']}")


def run(args: argparse.Namespace) -> int:
    target_source_ids = _validate_args(args)
    apply_mode = bool(args.apply) and not bool(args.dry_run)

    settings = get_settings()
    if settings.schema_guard_enabled:
        ensure_schema_ready(get_engine(), force_refresh=True)

    session_factory = get_session_factory()
    with session_factory() as db:
        matched, source_hits, truncated = _query_candidates(
            db,
            limit=args.limit,
            target_source_ids=target_source_ids,
        )

        review_note_applied: str | None = None
        updated_count = 0

        if apply_mode and matched:
            now = datetime.now(UTC)
            review_note_applied = f"{args.note}:{now.isoformat()}"
            for row in matched:
                row.review_status = ReviewStatus.REJECTED
                row.reviewed_at = now
                row.review_note = review_note_applied
                row.reviewed_by_user_id = args.reviewed_by_user_id
            db.commit()
            updated_count = len(matched)

        result = {
            "dry_run": not apply_mode,
            "source_ids": sorted(target_source_ids),
            "limit": args.limit,
            "truncated": truncated,
            "matched_count": len(matched),
            "updated_count": updated_count,
            "matched_change_ids": sorted(int(row.id) for row in matched),
            "source_id_hits": {str(key): value for key, value in sorted(source_hits.items())},
            "review_note_applied": review_note_applied,
            "reviewed_by_user_id": args.reviewed_by_user_id,
        }
        _render_result(result, as_json=args.json)
        return 0


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except Exception as exc:
        payload = {"error": str(exc), "dry_run": not bool(args.apply)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print(f"ops_cleanup_smoke_state failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
