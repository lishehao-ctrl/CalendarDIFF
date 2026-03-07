# Service Table Ownership (Shared PostgreSQL Runtime)

This matrix defines write ownership for the microservice split with shared PostgreSQL.

Rules:

1. Only owner service can write owner tables.
2. Non-owner services are read-only unless explicitly allowed and sunset-dated.
3. Cross-service mutations must go through outbox/inbox events.

## Ownership Matrix

| Table | Owner Service | Non-owner Access | Notes |
|---|---|---|---|
| users | platform-shared | read | Shared identity profile table in runtime |
| input_sources | input-service | read | Source lifecycle |
| input_source_configs | input-service | read | Source config |
| input_source_secrets | input-service | read | Encrypted source secrets |
| input_source_cursors | input-service | read | Source cursor state |
| sync_requests | input-service | read/update status by ingest-service | Ingest can update runtime status/error fields |
| ingest_jobs | ingest-service | read | Job claim/retry/dead-letter |
| ingest_results | ingest-service | read | Connector output |
| integration_outbox | platform-shared | read/write | Event relay table, namespace by event_type |
| integration_inbox | platform-shared | read/write | Consumer dedupe table, namespace by consumer_name |
| ingest_apply_log | review-service | read | Apply idempotency log |
| source_event_observations | review-service | read | Observation store |
| event_entities | review-service | read | Cross-source entity profile (`course_best` + aliases) |
| event_entity_links | review-service | read | Normalized observation->entity link table (auto/manual) |
| event_link_candidates | review-service | read | Review queue for deterministic linker rule misses / missing anchors |
| event_link_blocks | review-service | read | Permanent block list for rejected source->entity bindings |
| event_link_alerts | review-service | read | Medium-risk non-blocking queue for auto-link without canonical pending |
| inputs | review-service | read | Canonical input container |
| events | review-service | read | Canonical events |
| snapshots | review-service | read | Snapshot metadata |
| snapshot_events | review-service | read | Snapshot event materialization |
| changes | review-service | read | Review lifecycle |
| notifications | notification-service | read | Notification queue |
| digest_send_log | notification-service | read | Digest send ledger |

## Allowed Transitional Exceptions

| Table | Writing Service | Sunset Date | Reason |
|---|---|---|---|
| sync_requests | ingest-service | 2026-06-30 | Runtime status update while source ownership remains in input-service |

## Enforcement

Use:

```bash
python scripts/check_table_ownership.py
```

The check validates that all runtime tables are declared and ownership values are valid.
