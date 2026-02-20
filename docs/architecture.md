# Deadline Diff Watcher MVP Architecture

## 1) Product Goal and MVP Scope

### Goal
Build a backend service that watches ICS calendar feeds and notifies users only when detected event deadlines change.

Core behavior:
- Accept ICS feed URL from API.
- Periodically fetch and parse ICS data.
- Normalize event data into a canonical model.
- Compare current snapshot with prior canonical state.
- Persist change audit records.
- Send email notifications only when at least one change is detected in a sync run.

### In Scope
- FastAPI service with Postgres persistence.
- In-app scheduler (no platform cron).
- Postgres advisory lock to avoid duplicate scheduler execution across instances.
- API key authentication for MVP.
- Encrypted ICS URL at rest.

### Out of Scope (MVP)
- Full authentication/authorization system.
- Multi-tenant RBAC.
- Frontend/UI.
- Provider-specific deployment integrations.

## 2) Component Breakdown

1. API Layer (`FastAPI`)
- Endpoints for source management, manual sync trigger, change listing, health checks.
- API key guard on protected endpoints.

2. Scheduler Runner (`APScheduler`)
- Periodic runner checks due sources every minute.
- Uses Postgres advisory lock for singleton execution.

3. Source Connector (`httpx`)
- Downloads ICS content with connect/read timeouts and bounded retries.
- Captures ETag (if provided).

4. Parser + Normalizer (`icalendar` + app logic)
- Parses VEVENT fields from ICS payload.
- Normalizes to UTC-aware canonical event objects.
- Infers `course_label` heuristically from summary/description.

5. Diff Engine
- Compares current snapshot events against canonical `events` table.
- Emits `created`, `removed`, `due_changed`, `title_changed`, `course_changed`.
- Debounces removals by requiring missing in 3 consecutive snapshots.

6. Notification Dispatcher
- SMTP implementation behind notifier interface.
- Sends grouped email digest when run contains changes.
- Persists per-change notification status (`pending`, `sent`, `failed`).

7. Evidence Store (Filesystem, ICS-only)
- Stores the exact raw ICS payload fetched for each successful sync.
- Generates a structured `raw_evidence_key` object (`kind`, `store`, `path`, `sha256`, `retrieved_at`) and persists it on snapshots.
- Uses atomic file writes (temp file + rename) so evidence artifacts are never partially written.

8. Persistence Layer (`SQLAlchemy 2.0` + Alembic)
- Stores sources, canonical events, snapshots, snapshot events, changes, and notifications.

## 3) Data Flow

### Normal Flow

```text
POST /v1/sources/ics
  -> validate + encrypt URL
  -> insert sources row

Scheduler tick or POST /v1/sources/{id}/sync
  -> acquire advisory lock
  -> fetch ICS via httpx
  -> store raw ICS evidence on local filesystem
  -> parse VEVENTs
  -> normalize to canonical events (UTC)
  -> store snapshots(raw_evidence_key) + snapshot_events
  -> diff against canonical events
  -> insert changes rows (before_snapshot_id, after_snapshot_id, evidence_keys)
  -> update canonical events table
  -> if changes > 0: send email digest
  -> insert/update notifications rows
  -> update sources.last_checked_at, sources.last_error
```

### Fetch Failure Branch

```text
fetch error
  -> set sources.last_checked_at
  -> set sources.last_error
  -> do not create snapshots
  -> do not create changes
  -> do not send email
```

## 4) DB Schema Summary

`events` is the authoritative current canonical state for each source.

### `users`
- Purpose: future-ready owner table.
- Columns: `id`, `email`, `created_at`.

### `sources`
- Purpose: registered feed sources.
- Columns: `id`, `user_id`, `type`, `name`, `encrypted_url`, `interval_minutes`, `is_active`, `last_checked_at`, `last_error`, `created_at`.
- Notes: feed URL is encrypted and never returned by API.

### `events`
- Purpose: canonical latest events for each source.
- Columns: `id`, `source_id`, `uid`, `course_label`, `title`, `start_at_utc`, `end_at_utc`, `updated_at`.
- Constraints: unique (`source_id`, `uid`).

### `snapshots`
- Purpose: metadata for each sync capture.
- Columns: `id`, `source_id`, `retrieved_at`, `etag`, `content_hash`, `event_count`, `raw_evidence_key`.

### `snapshot_events`
- Purpose: immutable event rows per snapshot.
- Columns: `id`, `snapshot_id`, `uid`, `course_label`, `title`, `start_at_utc`, `end_at_utc`.

### `changes`
- Purpose: audit log of detected differences.
- Columns: `id`, `source_id`, `event_uid`, `change_type`, `detected_at`, `before_json`, `after_json`, `delta_seconds`, `before_snapshot_id`, `after_snapshot_id`, `evidence_keys`.
- Index: (`source_id`, `detected_at` desc).

### `notifications`
- Purpose: outbound delivery tracking per change.
- Columns: `id`, `change_id`, `channel`, `status`, `sent_at`, `error`.

## 5) Sync Lifecycle

1. Scheduler tick executes every minute.
2. Runner attempts global advisory lock (`pg_try_advisory_lock`).
3. If lock not acquired, run is skipped.
4. Runner selects active due sources:
- due if `last_checked_at` is null, or elapsed minutes >= `interval_minutes`.
5. For each source:
- fetch -> parse -> normalize -> persist snapshot -> diff -> persist changes -> update canonical state -> notify (if needed).
6. Update `sources.last_checked_at` on every attempt.
7. Set `sources.last_error` on failure, clear on success.

## 6) Diff Semantics

### Event Keying
- Primary key: `(source_id, uid)`.
- If UID missing: fallback deterministic fingerprint
  - `uid = "fp:" + sha256(title|start|end)[:16]`.

### Change Rules
- `created`: event in new snapshot but not in canonical events.
- `removed`: event missing from new snapshot and missing in prior 2 snapshots too (3 consecutive misses).
- `due_changed`: start or end changed.
- `title_changed`: title changed.
- `course_changed`: inferred course label changed.

### Priority and Coalescing
- Exactly one `changes` row per event per sync run.
- If multiple fields changed in one event, choose highest priority:
  - `due_changed > title_changed > course_changed`.
- `before_json` and `after_json` include all changed fields.

## 7) Failure Modes and Mitigations

1. ICS fetch timeout/network failure
- Mitigation: connect/read timeout + retries, store `last_error`, no diff/no email.

2. ICS parse failure (invalid feed/transient content)
- Mitigation: store `last_error`, skip state mutation and notifications.

3. Duplicate scheduler runs (multi-instance)
- Mitigation: Postgres advisory lock around scheduler loop.

4. Notification failure (SMTP issue)
- Mitigation: mark notification rows `failed` with error; do not rollback change audit rows.

5. DB contention/transient failure
- Mitigation: short transactions per source, lock acquisition fallback, explicit error handling.

## 8) Security and Secrets Handling

- API key header `X-API-Key` required for protected endpoints.
- ICS URL is encrypted at rest via Fernet key (`APP_SECRET_KEY`).
- ICS URL is excluded from API responses and redacted from logs.
- APIs expose evidence metadata (`raw_evidence_key` path and hashes), never raw ICS content or source URL.
- Use environment variables for SMTP and app secrets.

## 9) Observability

- Structured application logs with secret redaction.
- In-memory scheduler runtime status:
  - running flag
  - last run start/end
  - last error
  - last skip reason
  - last synced source count
- Persistent source status fields:
  - `last_checked_at`
  - `last_error`
- `/health` endpoint reports DB connectivity and scheduler summary.
