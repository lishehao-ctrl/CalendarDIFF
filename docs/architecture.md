# CalendarDIFF Backend Architecture (Core Simplified)

## 1) Scope and Principles

CalendarDIFF runtime is organized around one canonical pipeline:

1. ingest input data (`ics` / `email`)
2. update canonical timeline (`events`)
3. generate auditable diffs (`changes`)
4. enqueue/send notifications (`notifications`)

Current cleanup phase priorities:

1. remove term runtime complexity from main flow
2. keep onboarding strict and deterministic
3. keep a single email review domain (`/v1/emails/*`)

## 2) Runtime Stack

1. API host: FastAPI
2. Database: PostgreSQL + SQLAlchemy + Alembic
3. Scheduler: APScheduler + Postgres advisory locks
4. UI host: Next.js static export served at `/ui`
5. External integrations:
   - ICS HTTP fetch + parser
   - Gmail OAuth + Gmail REST metadata/history
   - SMTP notification delivery

## 3) Core Domain Boundaries

### 3.1 User / Onboarding Domain

Owns:

1. `users`
2. onboarding stage resolution (`needs_user | needs_ics | needs_baseline | ready`)

Responsibilities:

1. define registration vs onboarding completion
2. gate protected APIs until onboarding is complete

Key invariant:

1. onboarding completion is written only after first ICS baseline sync succeeds (`users.onboarding_completed_at`)

### 3.2 Input Ingestion Domain

Owns:

1. `inputs` (`type=ics|email`)
2. sync orchestration and run records (`sync_runs`)

Responsibilities:

1. input identity upsert
2. baseline-first semantics on first successful sync
3. per-input lock and error shaping (`input_busy`)

### 3.3 Canonical Timeline + Diff/Audit Domain

Owns:

1. `events`
2. `snapshots`
3. `changes`

Responsibilities:

1. preserve canonical state and audit history
2. ensure every user-visible diff comes from `changes`
3. keep evidence links (`evidence_keys`) for traceability

### 3.4 Notification / Digest Domain

Owns:

1. `notifications`
2. `user_notification_prefs`
3. `digest_send_log`

Responsibilities:

1. queue or dispatch notification events from `changes`
2. apply digest and idempotency policy
3. enforce user-level priority (EMAIL before Calendar)

### 3.5 Email Review Domain

Single runtime domain:

1. `email_messages`
2. `email_rule_labels`
3. `email_action_items`
4. `email_rule_analysis`
5. `email_routes`
6. API: `/v1/emails/*`

Responsibilities:

1. ingest deterministic rule extraction results
2. expose review queue actions (apply/archive/drop/notify/viewed)
3. convert approved review actions into canonical `changes`

## 4) Schema Baseline

Active migration head: `0010_drop_review_candidates`.

Notable state:

1. term runtime structures are removed from operational path:
   - no `user_terms`
   - no `input_term_baselines`
   - no `inputs.user_term_id`
   - no `changes.user_term_id`
2. onboarding baseline and email review queue are first-class runtime features
3. legacy review-candidate table is removed (`email_rule_candidates`)

## 5) Core Runtime Flows

### 5.1 Onboarding

1. `POST /v1/onboarding/register` with `notify_email + ics.url`
2. create/update user + first ICS input
3. onboarding reconfiguration keeps a single active ICS (newly submitted ICS remains active, older ICS inputs are deactivated)
4. run immediate first sync
5. if baseline succeeds:
   - write `users.onboarding_completed_at`
   - return `status=ready`
6. if baseline fails:
   - onboarding remains incomplete
   - protected APIs stay gated

### 5.2 ICS Sync

1. lock input
2. fetch/parse ICS
3. first successful run is baseline-only (`changes_created=0`)
4. later runs produce `changes` against canonical `events`
5. notifications follow normal queue/dispatch policy

### 5.3 Gmail Sync

1. first successful run initializes cursor (no changes)
2. incremental runs read new message metadata
3. each new message creates a Change record for traceability
4. actionable messages are also ingested into email review queue tables
5. no automatic canonical mutation from rules

### 5.4 Email Review Apply

Endpoint: `POST /v1/emails/{email_id}/apply`

Modes:

1. `create_new` -> create a new canonical event/task + emit `ChangeType.CREATED`
2. `update_existing` -> modify selected canonical event + emit `ChangeType.DUE_CHANGED`

Post-apply behavior:

1. route moves to `archive`
2. enqueue notification via existing notify pipeline

## 6) Public API Contract (Current)

### 6.1 Feed

`GET /v1/feed` query:

1. `input_id?`
2. `view=all|unread`
3. `input_types=email,ics`
4. `limit`
5. `offset`

No term filters or term fields remain in feed contract.

### 6.2 Removed APIs

Removed from runtime surface:

1. `/v1/review_candidates*`
2. `/v1/user/terms*`
3. `POST /v1/user` (initialization now only via onboarding)

### 6.3 Email Review APIs

Available:

1. `GET /v1/emails/queue`
2. `POST /v1/emails/{email_id}/route`
3. `POST /v1/emails/{email_id}/mark_viewed`
4. `POST /v1/emails/{email_id}/apply`

### 6.4 Busy Error Contract

Manual sync contention returns `409` with:

1. `detail.code = "input_busy"`
2. `detail.status = "LOCK_SKIPPED"`
3. `detail.retry_after_seconds`

## 7) Locking and Scheduling

1. global scheduler lock: one runner executes each tick
2. per-input lock: same input cannot be processed concurrently
3. lock skip is recoverable and does not mutate canonical state

## 8) Guardrails

1. keep `/v1/emails/*` as the only email review entrypoint
2. keep term and review-candidate legacy symbols out of runtime code
3. keep onboarding initialization through `/v1/onboarding/register` only
