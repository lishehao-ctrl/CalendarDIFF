# Validation Guide

Prefer the smallest relevant check set first. Expand only after the first targeted pass is green.

## Semantic/review changes
```bash
pytest tests/test_review_*.py \
  tests/test_manual_events_api.py \
  tests/test_course_work_item_families_api.py \
  tests/test_course_raw_types_api.py \
  tests/test_users_timezone_api.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_runtime_entrypoints.py
```

## Parser/apply changes
Add the source-specific suites you touched, for example:

```bash
pytest tests/test_core_ingest_gmail_directive_apply.py \
  tests/test_core_ingest_apply_calendar_delta.py \
  tests/test_input_gmail_source_api.py \
  tests/test_input_ics_source_api.py
```

## Onboarding/source control plane changes
```bash
pytest tests/test_input_oauth_service.py \
  tests/test_onboarding_flow_api.py
```

## Frontend DTO or route consumption changes
```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

## OpenAPI changes
```bash
python scripts/update_openapi_snapshots.py
pytest tests/test_openapi_contract_snapshots.py
```

## Runtime entrypoint changes
```bash
pytest tests/test_runtime_entrypoints.py
```
