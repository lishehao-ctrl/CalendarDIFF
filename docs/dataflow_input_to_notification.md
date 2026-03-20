# Dataflow: Input To Notification

## Default monolith flow
1. `sources` stores source config, OAuth state, and sync requests.
2. `runtime.connectors` fetches Gmail / ICS data and prepares provider payloads.
3. `runtime.llm` parses or reduces provider payloads into `IngestResult`.
4. `runtime.apply` applies parsed results into review tables and approved entity state.
5. `changes` exposes the user-facing decision workflow.
6. `manual` handles manual event CRUD for approved user-visible items.
7. `notify` reads pending outbox / digest state and sends notifications.

## Important boundary change
These are module boundaries inside one backend process, not HTTP service boundaries between separate apps.

## Default ports
Only the monolith backend port is required for app behavior:
- Backend `8200`
- Frontend `3000`
