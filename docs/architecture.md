# Architecture

## Runtime model
CalendarDIFF uses one backend process for the default runtime.

User-facing product lanes are converging to:

- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

That process contains these module boundaries:
- `auth`: session auth, register/login/logout, bootstrap admin
- `profile`: user profile and timezone settings
- `input_control_plane`: sources, OAuth session creation, sync requests, webhooks
- `ingestion`: source polling, connector runtime, parsing orchestration
- `core_ingest`: apply parsed results into review state and approved entity state
- `review_changes`: review queues, decisions, edits, label learning
- `review_taxonomy`: course family and raw-type management under `/review/course-work-item-*`
- `events`: manual event CRUD under `/events/manual*`
- `notify`: notification enqueue and delivery
- `llm_runtime` / `llm_gateway`: parser execution, queueing, provider transport

## Operational observability

Source operation should be interpreted in two phases:

- `bootstrap`: initial source warmup / first large sync
- `replay`: normal ongoing operation after warmup

This distinction matters for:

- replay harness behavior
- token/cache/latency accounting
- user-facing source health and cost interpretation

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
- `/review/course-work-item-families*`
- `/review/course-work-item-raw-types*`
- `/events/manual*`
- `/health`

## Internal execution
Worker loops for ingestion, review apply, notification dispatch, and llm parsing run inside the monolith as background tasks. They still use their existing enable/tick env vars, but they are no longer separate deployable services.

## Observability stance
- Source intake is interpreted in two phases:
  - `bootstrap`: initial source warmup / first large sync
  - `replay`: normal ongoing sync after warmup
- Sync-level token/cache/latency aggregation currently lives on `sync_requests.metadata_json.llm_usage_summary`
- Source-level UI observability should build from sync requests rather than raw worker logs

## Contracts
- Canonical OpenAPI snapshot: `contracts/openapi/public-service.json`
- Runtime flow and module ownership docs live in:
  - `docs/api_surface_current.md`
  - `docs/dataflow_input_to_notification.md`
  - `docs/event_contracts.md`
  - `docs/service_table_ownership.md`
