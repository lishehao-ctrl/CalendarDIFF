# Backend Remove Link Alert Layer Agent Report

## Result

- Completed.
- Backend alert layer (`EventLinkAlert`) has been removed from runtime model, ingest/apply side-effects, review routes, summary, and internal metrics.
- Link governance is now two-lane only:
  - accepted links: `event_entity_links`
  - review-needed links: `event_link_candidates`
- Frontend files were not modified.

## Execution Plan

1. Inspect all `EventLinkAlert` references across model, ingest, review_links, review worker, summary/metrics, routes, tests, and docs.
2. Remove model/runtime artifacts first (table model + enums + relations + exports), then remove ingest/review alert side-effects.
3. Remove backend API/consumer modules and route wiring for `/review/link-alerts/*`.
4. Update summary/metrics contracts and tests to reflect alert-layer removal.
5. Run targeted backend compile/test validation and sync backend docs to the new two-lane governance.

## Changes Made

1. Database/model layer
   - Removed `EventLinkAlert` model and alert enums from `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/review.py`.
   - Removed `event_link_alerts` relationships from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/input.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/shared.py`
   - Removed alert exports/imports from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/db/models/__init__.py`
   - Removed table ownership declaration for `event_link_alerts` in:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/scripts/check_table_ownership.py`

2. Ingest/apply/linking side-effects
   - Removed alert outbox/pending integration from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/apply.py`
   - Removed `auto_link_contexts` alert path from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/gmail_apply.py`
   - Removed candidate-opened alert resolve emission from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/linking_engine.py`
   - Deleted alert-only core ingest modules:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/link_alert_outbox.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/core_ingest/pending_auto_link_alerts.py`

3. Review link layer and worker
   - Removed alert route composition from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/router.py`
   - Removed alert resolution side-effects from link mutation flows:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/links_service.py`
   - Removed alert DTOs and summary field from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/schemas.py`
   - Removed `link_alerts_pending` summary computation from:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/summary_service.py`
   - Deleted alert-only review link modules:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_router.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_query_service.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_decision_service.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_upsert_service.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_event_consumer.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_links/alerts_errors.py`
   - Removed alert-consumer tick integration from review worker:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/services/review_api/main.py`

4. Summary/metrics cleanup
   - Removed alert counters from internal review metrics:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/app/modules/review_changes/metrics_router.py`

5. Tests
   - Updated summary API expectation to no longer require alert count:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_review_items_summary_api.py`
   - Updated pending boundary assertions to remove `pending_auto_link_alerts` dependency:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_core_ingest_pending_boundaries.py`
   - Updated shell-reexport guard list after alert module deletion:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_no_reexport_shell_modules.py`
   - Removed alert-only backend tests:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_review_link_alerts_api.py`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/tests/test_review_link_alert_events_consumer.py`

6. Backend docs sync
   - Updated to remove link-alert queue/routes/metrics semantics:
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/docs/architecture.md`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/docs/api_surface_current.md`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/docs/event_contracts.md`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/docs/dataflow_input_to_notification.md`
     - `/Users/lishehao/Desktop/Project/CalendarDIFF/docs/service_table_ownership.md`

## Validation

1. Compile sanity
```bash
python -m py_compile \
  app/db/models/review.py \
  app/db/models/input.py \
  app/db/models/shared.py \
  app/db/models/__init__.py \
  app/modules/core_ingest/apply.py \
  app/modules/core_ingest/gmail_apply.py \
  app/modules/core_ingest/linking_engine.py \
  app/modules/review_links/router.py \
  app/modules/review_links/schemas.py \
  app/modules/review_links/summary_service.py \
  app/modules/review_links/links_service.py \
  app/modules/review_changes/metrics_router.py \
  services/review_api/main.py \
  tests/test_review_items_summary_api.py \
  tests/test_core_ingest_pending_boundaries.py \
  tests/test_no_reexport_shell_modules.py
```
- Result: pass

2. Targeted backend tests
```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_review_items_summary_api.py \
  tests/test_review_link_candidates_api.py \
  tests/test_core_ingest_pending_boundaries.py \
  tests/test_internal_metrics_endpoints.py \
  tests/test_core_ingest_pending_outbox_contract.py
```
- Result: `13 passed`

3. Additional guard tests
```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_no_reexport_shell_modules.py \
  tests/test_no_internal_version_names.py
```
- Result: `3 passed`

4. Static grep check
```bash
rg -n "EventLinkAlert|event_link_alert|review\\.link_alert|link-alerts|pending_auto_link_alerts|link_alert_outbox|alerts_event_consumer|alerts_router|alerts_query_service|alerts_decision_service|alerts_upsert_service|alerts_errors" app services tests scripts
```
- Result: no runtime references remain (only disallowed-token list in `tests/test_no_internal_version_names.py`).

## Risks / Remaining Issues

1. This pass removes alert-specific backend routes and DTO fields without frontend adaptation (as specified backend-only); existing frontend integration for `/review/link-alerts/*` will break until frontend cleanup lands.
2. Current workspace contains unrelated pre-existing file deletions/changes outside this pass; they were not modified by this implementation and should be reviewed separately before final integration.
