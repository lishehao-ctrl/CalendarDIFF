# Dataflow: Input To Notification

## Default monolith flow
1. `input_control_plane` stores source config, OAuth state, and sync requests.
2. `ingestion` fetches Gmail / ICS data and normalizes source payloads.
3. `core_ingest` applies parsed results into review tables and approved entity state.
4. `review_changes` and `review_links` expose decision workflows.
5. `events` handles manual event CRUD for approved user-visible items.
6. `notify` reads pending outbox / digest state and sends notifications.

## Important boundary change
These are module boundaries inside one backend process, not HTTP service boundaries between separate apps.

## Default ports
Only the monolith backend port is required for app behavior:
- Backend `8200`
- Frontend `3000`
