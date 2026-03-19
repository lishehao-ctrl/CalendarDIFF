# Event Contracts

CalendarDIFF now treats event flow as module boundaries inside one backend process.

## Main persisted handoff objects
- `SourceEventObservation`: normalized source observations captured from Gmail / ICS / other sources
- `Change`: reviewable proposed or manual semantic changes
- `EventEntity`: approved entity state used by product surfaces
- `IntegrationOutbox`: notification/audit events emitted after decisions

## Flow semantics
1. Source ingestion writes observations and parsed payloads.
2. Apply logic deterministically resolves `entity_uid` and converts payloads into pending `Change` rows.
3. Review decisions or canonical edits update `EventEntity` state.
4. Notification and audit code consume approved state / outbox rows.

## Manual edits and taxonomy
- Manual event CRUD uses `/events/manual*` and records canonical edit audit changes.
- Course family and raw-type management use `/review/course-work-item-families*` and `/review/course-work-item-raw-types*`.

## Public API note
There is no `/users/...` review or taxonomy surface anymore.
