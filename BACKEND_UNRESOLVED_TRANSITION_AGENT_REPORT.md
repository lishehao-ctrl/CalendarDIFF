# Backend Unresolved Transition Agent Report

## Result

- Completed
- `valid -> unresolved` 现在会在 ingest 层显式退役同 `source_id + external_event_id` 的旧 active observation。
- 该过渡不会新增 `changes`，也不会新增 `review.pending.created` 事件。

## Execution Plan

1. Inspect calendar/gmail unresolved transition branches and confirm stale-active retention behavior.
2. Add shared helper to retire active observations specifically for unresolved transition (without semantic side effects).
3. Wire helper into calendar/gmail unresolved branches.
4. Add regression tests for calendar and Gmail `valid -> unresolved`.
5. Run targeted backend validation and update this report.

## Changes Made

1. Added unresolved-transition retirement helper in [observation_store.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/observation_store.py):
   - `retire_active_observation_for_unresolved_transition(...)`
   - Targets only active row for `(source_id, external_event_id)`.
   - Sets `is_active=False`, updates `observed_at` and `last_request_id`.
   - Returns diagnostic `bool`; does not feed pending rebuild flow.
2. Updated calendar unresolved branch in [calendar_apply.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/calendar_apply.py):
   - Calls unresolved retirement helper before unresolved bucket upsert.
   - Removed unresolved-path `seen_external_ids` marking so unresolved IDs no longer preserve stale active rows in full-sync handling.
   - Keeps unresolved branch isolated from semantic proposal emission.
3. Updated Gmail unresolved branch in [gmail_apply.py](/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/gmail_apply.py):
   - Calls unresolved retirement helper before unresolved bucket upsert.
   - Keeps `continue` boundary so unresolved transition does not enter observation/link/proposal path.
4. Added regression coverage in [test_core_ingest_unresolved_bucket.py](/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_core_ingest_unresolved_bucket.py):
   - `test_calendar_valid_to_unresolved_retires_active_observation_without_semantic_side_effects`
   - `test_gmail_valid_to_unresolved_retires_active_observation_without_semantic_side_effects`
   - Assertions include:
     - active observation count becomes `0` for transitioned source record
     - unresolved active row exists
     - `Change` count unchanged across transition
     - `review.pending.created` outbox count unchanged across transition
     - Gmail link/candidate counts unchanged across transition

## Validation

1. Compile/import sanity:
   - `python -m py_compile app/modules/core_ingest/observation_store.py app/modules/core_ingest/calendar_apply.py app/modules/core_ingest/gmail_apply.py app/modules/core_ingest/unresolved_store.py tests/test_core_ingest_unresolved_bucket.py`
   - Result: pass
2. Targeted backend pytest:
   - `PYTHONPATH=. python -m pytest -q tests/test_core_ingest_unresolved_bucket.py tests/test_core_ingest_apply_calendar_delta.py tests/test_core_ingest_pending_proposal_rebuild.py tests/test_core_ingest_pending_outbox_contract.py`
   - Result: `13 passed in 2.07s`

## Risks / Remaining Issues

1. This pass is intentionally narrow and backend-only; no frontend or user-facing unresolved APIs were added.
2. Existing pending changes in unrelated dirty files were intentionally left untouched.
