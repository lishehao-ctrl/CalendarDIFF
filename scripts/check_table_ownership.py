#!/usr/bin/env python3
from __future__ import annotations

import json

from app.db.base import Base
from app.db.model_registry import load_all_models

load_all_models()

VALID_OWNERS = {
    "input-service",
    "ingest-service",
    "review-service",
    "notification-service",
    "platform-shared",
}

TABLE_OWNERSHIP: dict[str, str] = {
    "users": "platform-shared",
    "user_sessions": "platform-shared",
    "input_sources": "input-service",
    "input_source_configs": "input-service",
    "input_source_secrets": "input-service",
    "input_source_cursors": "input-service",
    "sync_requests": "input-service",
    "ingest_jobs": "ingest-service",
    "ingest_results": "ingest-service",
    "integration_outbox": "platform-shared",
    "integration_inbox": "platform-shared",
    "ingest_apply_log": "review-service",
    "source_event_observations": "review-service",
    "event_entities": "review-service",
    "event_entity_links": "review-service",
    "event_link_candidates": "review-service",
    "event_link_blocks": "review-service",
    "changes": "review-service",
    "change_source_refs": "review-service",
    "course_work_item_label_families": "review-service",
    "course_work_item_raw_types": "review-service",
    "course_raw_type_suggestions": "review-service",
    "notifications": "notification-service",
    "digest_send_log": "notification-service",
}


def main() -> int:
    runtime_tables = set(Base.metadata.tables.keys())
    declared_tables = set(TABLE_OWNERSHIP.keys())

    errors: list[str] = []

    missing_declarations = sorted(runtime_tables - declared_tables)
    if missing_declarations:
        errors.append(f"missing ownership declarations: {missing_declarations}")

    stale_declarations = sorted(declared_tables - runtime_tables)
    if stale_declarations:
        errors.append(f"declared tables not in metadata: {stale_declarations}")

    invalid_owners = sorted(
        table for table, owner in TABLE_OWNERSHIP.items() if owner not in VALID_OWNERS
    )
    if invalid_owners:
        errors.append(f"invalid owner value on tables: {invalid_owners}")

    summary = {
        "valid": not errors,
        "table_count": len(runtime_tables),
        "declared_count": len(declared_tables),
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=True))

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
