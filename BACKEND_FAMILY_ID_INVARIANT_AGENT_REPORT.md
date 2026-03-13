# Backend Family ID Invariant Agent Report

## Result

- Completed

## Execution Plan

1. Add unresolved ingest bucket model + persistence helpers.
2. Enforce family-resolution invariant in kind resolution and apply paths.
3. Isolate unresolved records from observation/change/outbox flows.
4. Add recovery behavior when later ingest becomes resolvable.
5. Add backend tests and run targeted validation.
6. Sync backend docs to reflect unresolved isolation behavior.

## Changes Made

1. Added unresolved ingest model:
   - `app/db/models/ingestion.py`: added `IngestUnresolvedRecord` with required fields and indexes.
   - `app/db/models/__init__.py`: exported `IngestUnresolvedRecord`.
2. Added unresolved ingest persistence helpers:
   - `app/modules/core_ingest/unresolved_store.py`
   - `upsert_active_unresolved_record(...)`
   - `resolve_active_unresolved_records(...)`
3. Hardened family resolution:
   - `app/modules/core_ingest/course_work_item_family_resolution.py`
   - added `source_facts` fallback chain for label resolution (`raw_type -> event_name -> source_title`)
   - unresolved path now marks `reason_code=missing_course_identity`
   - non-unresolved path now enforces `family_id` integrity
4. Applied unresolved isolation in ingest apply:
   - `app/modules/core_ingest/calendar_apply.py`
   - `app/modules/core_ingest/gmail_apply.py`
   - unresolved records now persist to unresolved bucket and skip normal observation/review flow
   - later resolvable ingests resolve active unresolved entries
   - calendar remove records now clear active unresolved entries for the same source/external id
5. Added defensive family-id guards:
   - `app/modules/core_ingest/pending_proposal_rebuild.py`: candidate payload now fails on missing semantic `family_id`
   - `app/modules/review_changes/approved_entity_state.py`: active state apply now fails on missing `family_id`
6. Completed backend tests update:
   - updated `tests/test_core_ingest_pending_proposal_rebuild.py` fixtures to use non-null `family_id`
   - added `tests/test_core_ingest_unresolved_bucket.py` (new)
   - added missing-family guard test in `tests/test_event_entity_registry.py`
   - added calendar-remove cleanup test for active unresolved records
7. Synced backend docs:
   - `docs/architecture.md`
   - `docs/dataflow_input_to_notification.md`
   - `docs/event_contracts.md`
   - added unresolved ingest isolation behavior and no-review/no-outbox guarantees for unresolved records

## Validation

1. Compile sanity:
   - `python -m py_compile app/db/models/ingestion.py app/db/models/__init__.py app/modules/core_ingest/unresolved_store.py app/modules/core_ingest/course_work_item_family_resolution.py app/modules/core_ingest/calendar_apply.py app/modules/core_ingest/gmail_apply.py app/modules/core_ingest/pending_proposal_rebuild.py app/modules/review_changes/approved_entity_state.py tests/test_core_ingest_pending_proposal_rebuild.py tests/test_core_ingest_unresolved_bucket.py tests/test_event_entity_registry.py`
   - Result: pass
2. Targeted backend pytest:
   - `PYTHONPATH=. python -m pytest -q tests/test_core_ingest_pending_proposal_rebuild.py tests/test_core_ingest_pending_outbox_contract.py tests/test_core_ingest_apply_calendar_delta.py tests/test_review_changes_unified.py tests/test_event_entity_registry.py tests/test_raw_type_suggestion_resolution.py tests/test_course_work_item_family_migration.py tests/test_core_ingest_unresolved_bucket.py`
   - Result: `19 passed in 3.15s`
3. Required compile command subset:
   - `python -m py_compile app/db/models/ingestion.py app/modules/core_ingest/course_work_item_family_resolution.py app/modules/core_ingest/calendar_apply.py app/modules/core_ingest/gmail_apply.py app/modules/core_ingest/pending_proposal_rebuild.py app/modules/review_changes/approved_entity_state.py`
   - Result: pass
4. Import-boundary sanity:
   - `PYTHONPATH=. python -m pytest -q tests/test_module_import_boundaries.py`
   - Result: `2 passed`

## Risks / Remaining Issues

1. Existing pre-existing dirty worktree files outside this task remain (not modified/reverted in this pass).
2. This pass intentionally does not add user-facing unresolved APIs/UI; unresolved records are backend-only as specified.
