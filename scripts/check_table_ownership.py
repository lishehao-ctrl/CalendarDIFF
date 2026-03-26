#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.base import Base
from app.db.model_registry import load_all_models

load_all_models()

VALID_OWNERS = {
    "shared",
    "sources",
    "runtime.connectors",
    "runtime.llm",
    "runtime.apply",
    "changes",
    "families",
    "notify",
}

TABLE_OWNERSHIP: dict[str, str] = {
    "users": "shared",
    "user_sessions": "shared",
    "input_sources": "sources",
    "input_source_configs": "sources",
    "input_source_secrets": "sources",
    "input_source_cursors": "sources",
    "sync_requests": "sources",
    "ingest_jobs": "runtime.connectors",
    "ingest_results": "runtime.connectors",
    "calendar_component_parse_tasks": "runtime.llm",
    "gmail_message_parse_cache": "runtime.llm",
    "gmail_message_purpose_cache": "runtime.llm",
    "calendar_component_parse_cache": "runtime.llm",
    "integration_outbox": "shared",
    "integration_inbox": "shared",
    "ingest_apply_log": "runtime.apply",
    "source_event_observations": "runtime.apply",
    "event_entities": "runtime.apply",
    "ingest_unresolved_records": "runtime.apply",
    "changes": "changes",
    "change_source_refs": "changes",
    "course_work_item_label_families": "families",
    "course_work_item_raw_types": "families",
    "course_raw_type_suggestions": "families",
    "notifications": "notify",
    "digest_send_log": "notify",
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
