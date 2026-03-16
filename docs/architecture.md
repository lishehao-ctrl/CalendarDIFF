# Architecture

## Runtime model
CalendarDIFF uses one backend process for the default runtime.

That process contains these module boundaries:
- `auth`: session auth, register/login/logout, bootstrap admin
- `profile`: user profile and timezone settings
- `input_control_plane`: sources, OAuth session creation, sync requests, webhooks
- `ingestion`: source polling, connector runtime, parsing orchestration
- `core_ingest`: apply parsed results into review state and approved entity state
- `review_changes`: review queues, decisions, edits, label learning
- `review_links`: link candidates, manual relink, block management, review summary
- `review_taxonomy`: course family and raw-type management under `/review/course-work-item-*`
- `events`: manual event CRUD under `/events/manual*`
- `notify`: notification enqueue and delivery
- `llm_runtime` / `llm_gateway`: parser execution, queueing, provider transport

## Entry points
- Default backend entrypoint: `services/app_api/main.py`
- Compatibility export: `services/public_api/main.py`

There is no default split runtime entrypoint set anymore.

## Public route groups
- `/auth/*`
- `/profile/me`
- `/sources/*`
- `/onboarding/*`
- `/review/changes*`
- `/review/links*`
- `/review/course-work-item-families*`
- `/review/course-work-item-raw-types*`
- `/events/manual*`
- `/health`

## Internal execution
Worker loops for ingestion, review apply, notification dispatch, and llm parsing run inside the monolith as background tasks. They still use their existing enable/tick env vars, but they are no longer separate deployable services.

## Contracts
- Canonical OpenAPI snapshot: `contracts/openapi/public-service.json`
- Runtime flow and module ownership docs live in:
  - `docs/api_surface_current.md`
  - `docs/dataflow_input_to_notification.md`
  - `docs/event_contracts.md`
  - `docs/service_table_ownership.md`
