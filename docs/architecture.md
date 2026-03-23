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
- `agents`: read-only context aggregation, persisted proposal generation, and approval-ticket execution gateway
- `settings`: user profile, timezone settings, and user-owned MCP access tokens
- `sources`: source CRUD, OAuth session creation, sync requests, observability, webhooks
- `runtime.connectors`: source polling, connector runtime, provider discovery, replay/bootstrap continuation
  - includes provider-specific clients under `runtime.connectors.clients`
- `runtime.llm`: parser queueing, preflight, message processing, provider reduce
- `runtime.apply`: apply parsed results into observations, proposal rebuild, and approved entity state
- `runtime.kernel`: shared job lifecycle, queues, retries, outbox/result handoff, sync stage writer
- `changes`: review queues, decisions, edits, label learning under `/changes*`
- `families`: course family and raw-type management under `/families*`
- `manual`: manual event CRUD under `/manual/events*`
- `notify`: notification enqueue and delivery
- `llm_gateway`: model transport, cache policy, and invocation profiles

`sync_requests` is the single user-visible runtime state machine.

Fine-grained runtime truth now lives on:

- `stage`
- `substage`
- `stage_updated_at`
- `progress_json`

The coarse `status` field remains, but operator-facing observability should read explicit stage data rather than reconstructing state from incidental job payload fields.

## Operational observability

Source operation should be interpreted in two phases:

- `bootstrap`: initial source warmup / first large sync
- `replay`: normal ongoing operation after warmup

This distinction matters for:

- replay harness behavior
- token/cache/latency accounting
- user-facing source health and cost interpretation

Each sync advances through explicit runtime stages:

- `connector_fetch`
- `llm_queue`
- `llm_parse`
- `provider_reduce`
- `result_ready`
- `applying`
- `completed`
- `failed`

The backend workbench overview should not be reconstructed in the UI from multiple lane calls.
`GET /changes/summary` is the current aggregated intake/workbench contract:

- pending `Changes` count
- `Families` governance attention
- active `Manual` override count
- aggregated `Sources` posture
- one backend-chosen recommended lane/reason

## Entry points
- Default backend entrypoint: `services/app_api/main.py`
- External MCP entrypoint: `services/mcp_server/main.py`

There is no compatibility public-app wrapper or default split runtime entrypoint anymore.

## Public route groups
- `/auth/*`
- `/agent/context/*`
- `/agent/proposals/*`
- `/agent/approval-tickets/*`
- `/settings/profile`
- `/sources/*`
- `/onboarding/*`
- `/changes*`
- `/families*`
- `/manual/events*`
- `/health`

## Internal execution
Worker loops for `runtime.connectors`, `runtime.apply`, notification dispatch, and `runtime.llm` run inside the monolith as background tasks. They still use their existing enable/tick env vars, but they are no longer separate deployable services.

## Observability stance
- Source intake is interpreted in two phases:
  - `bootstrap`: initial source warmup / first large sync
  - `replay`: normal ongoing sync after warmup
- Sync-level token/cache/latency aggregation currently lives on `sync_requests.metadata_json.llm_usage_summary`
- Source-level UI observability should build from sync requests rather than raw worker logs

## Contracts
- Canonical OpenAPI snapshot: `contracts/openapi/public-service.json`
- Runtime flow and module ownership docs live in:
  - `docs/api_layering_contract.md`
  - `docs/api_surface_current.md`
  - `docs/project_structure.md`
  - `docs/deployment.md`
  - `docs/dataflow_input_to_notification.md`
  - `docs/event_contracts.md`
  - `docs/frontend_backend_contracts.md`
  - `docs/service_table_ownership.md`
