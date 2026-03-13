# Backend OpenAPI Snapshot Regen Spec

## Purpose

This backend-only pass fixes the contract artifact drift introduced by the recent `EventLinkAlert` layer removal.

The runtime/backend cleanup is already mostly correct, but the checked-in OpenAPI snapshots are stale:

- `contracts/openapi/public-service.json` still exposes `/review/link-alerts/*`
- `ReviewItemsSummaryResponse` still requires `link_alerts_pending`
- `tests/test_openapi_contract_snapshots.py` currently fails

This pass exists to bring the checked-in OpenAPI contract artifacts back in sync with the actual backend runtime.

Frontend is explicitly out of scope for this pass.

## Fixed Decisions

These decisions are already made.

1. The `EventLinkAlert` layer is removed from active backend runtime.
2. `/review/link-alerts/*` is not part of the backend API anymore.
3. `ReviewItemsSummaryResponse` no longer includes `link_alerts_pending`.
4. The checked-in OpenAPI snapshots must match the current backend runtime, not the removed alert-layer API.
5. This is a backend-only cleanup pass. Do not modify frontend files.

## Required End State

After this pass:

1. OpenAPI snapshots reflect the current backend runtime after alert-layer removal.
2. `contracts/openapi/public-service.json` no longer contains `/review/link-alerts/*`.
3. `contracts/openapi/public-service.json` no longer contains `link_alerts_pending`.
4. `tests/test_openapi_contract_snapshots.py` passes.
5. No unrelated backend behavior is changed just to make snapshots pass.

## Required Implementation Areas

Likely files:

- `/Users/lishehao/Desktop/Project/CalendarDIFF/contracts/openapi/public-service.json`
- any other generated OpenAPI snapshots touched by the snapshot update workflow
- `/Users/lishehao/Desktop/Project/CalendarDIFF/scripts/update_openapi_snapshots.py` only if the current generation flow itself is broken
- narrow backend docs only if they are part of the snapshot-generation workflow and must be synced

The preferred path is to regenerate snapshots, not to hand-edit generated JSON unless generation is blocked.

## Acceptance Criteria

This pass is complete when all of the following are true:

1. checked-in OpenAPI snapshots match the current backend runtime
2. `test_openapi_contract_snapshots.py` passes
3. no frontend files are modified
4. no unrelated runtime refactor is introduced

## Required Tests

At minimum, run:

1. the OpenAPI snapshot regeneration command
2. `PYTHONPATH=. python -m pytest -q tests/test_openapi_contract_snapshots.py`

Recommended follow-up check:

3. rerun the recent backend alert-removal suite to confirm snapshot sync did not hide a runtime regression:
   - `tests/test_review_items_summary_api.py`
   - `tests/test_review_link_candidates_api.py`
   - `tests/test_core_ingest_pending_boundaries.py`
   - `tests/test_internal_metrics_endpoints.py`
   - `tests/test_core_ingest_pending_outbox_contract.py`

## Explicit Non-Goals

Do not do these in this pass:

- frontend cleanup
- new backend architecture changes
- reintroducing alert-layer APIs just to match stale snapshots
- broad docs rewrites unrelated to the generated contract drift

## Validation

The executing agent should derive the exact command list from the final diff, but validation must include:

- OpenAPI snapshot regeneration
- `tests/test_openapi_contract_snapshots.py`
- compile/import sanity only if backend source files are actually modified

This is a backend-only pass; frontend must remain untouched.
