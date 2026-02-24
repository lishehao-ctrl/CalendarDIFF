# CalendarDIFF Architecture (Current Runtime)

## 1) Scope

CalendarDIFF ingests, diffs, and notifies on two input types:

1. `ics` calendar feeds
2. `email` feeds (Gmail OAuth readonly)

The runtime ownership model is **user-only**: one `user` owns many `inputs` and optional `user_terms`.

## 2) Runtime Stack

1. API and UI host: FastAPI
2. Scheduler: APScheduler
3. Database: PostgreSQL + SQLAlchemy + Alembic
4. UI: Next.js static export served from `/ui`
5. Integrations:
   - ICS: HTTP fetch + parser
   - Gmail: OAuth + Gmail REST (via `httpx`)
   - Notification: SMTP

## 3) Data Model (Operationally Relevant)

Active migration head: `0006_onboarding_term_baselines`.

Core tables:

1. `users`
   - user-level settings: `notify_email`, `calendar_delay_seconds`
   - onboarding completion marker: `onboarding_completed_at`
2. `user_terms`
   - optional semester windows under each user (`code`, `label`, `starts_on`, `ends_on`, `is_active`)
3. `inputs`
   - `type=ics|email`
   - owner: `user_id`
   - optional term binding: `user_term_id`
   - identity uniqueness: `(user_id, type, identity_key)`
   - policy constraints:
    - `interval_minutes` fixed at `15` (application + DB check)
    - input-level `notify_email` ignored for delivery routing
4. `sync_runs`
   - one row per sync attempt
5. `changes`
   - per-detected change records
   - `user_term_id` for change-level term attribution
6. `notifications`
   - queued email notifications with `deliver_after` and `enqueue_reason`
7. `user_notification_prefs` and `digest_send_log`
   - digest schedule and idempotent send ledger
8. `input_term_baselines`
   - unique `(input_id, user_term_id)` markers for auto-silent term baselines

## 4) Core Flows

### 4.1 Input Creation

1. ICS input:
   - `POST /v1/inputs/ics`
   - upsert by canonical URL identity
   - optional `user_term_id`
2. Gmail input:
   - `POST /v1/inputs/email/gmail/oauth/start`
   - callback exchanges token and upserts by account+filter identity

### 4.1.1 Onboarding Contract

1. `GET /v1/onboarding/status` returns:
   - `needs_user | needs_term | needs_ics | needs_baseline | ready`
2. `POST /v1/onboarding/register` performs in sequence:
   - register user (`notify_email`)
   - upsert first `user_term`
   - upsert first ICS input
   - run immediate baseline sync
3. `users.onboarding_completed_at` is written only when baseline sync succeeds.
4. Before onboarding completion, protected routes return:
   - `409 detail.code=user_not_initialized` or `user_onboarding_incomplete`

### 4.2 Sync Execution

Common rules:

1. input-level advisory lock prevents same-input concurrent execution
2. first successful sync is baseline-first (no noisy alert)
3. each run writes one `sync_runs` row

ICS path:

1. conditional HTTP fetch (`ETag` / `Last-Modified`)
2. normalize + hash content for no-op short-circuit
3. parse + diff against canonical events
4. create `changes` and queue notifications
5. for each ICS change, assign `changes.user_term_id` by event local date -> matching `user_terms` window
6. first run in a newly active term uses auto-silent baseline:
   - if `(input_id, term_id)` has no baseline marker, suppress current term candidate changes
   - persist marker in `input_term_baselines`
   - subsequent runs in same term emit normal diff/notify

Gmail path:

1. first sync stores cursor (`historyId`) only
2. incremental sync reads history since cursor
3. each new message creates one change (`event_uid=message_id`)

### 4.3 Notification Priority

Within one user:

1. EMAIL changes are dispatched first
2. Calendar changes may be delayed by `calendar_delay_seconds` (default 120)
3. recipient resolution order:
   - `user.notify_email`
   - `DEFAULT_NOTIFY_EMAIL` / `SMTP_TO`
   - fallback `user.email`

## 5) Locking and Scheduling

1. global scheduler advisory lock: only one instance executes a tick
2. per-input advisory lock: prevents duplicate processing for the same input
3. lock contention behavior:
   - scheduler conflict records `LOCK_SKIPPED`
   - manual conflict returns recoverable `409` (`source_busy`) and records `LOCK_SKIPPED`

## 6) APIs and UI

1. Core APIs:
   - `/v1/onboarding/*`
   - `/v1/user*`
   - `/v1/inputs*`
   - `/v1/feed`
   - `/v1/notification_prefs`
   - `/v1/notifications/send_digest_now`
2. UI routes:
   - `/ui` -> route by onboarding status:
     - `ready -> /ui/inputs`
     - otherwise `/ui/onboarding`
   - `/ui/onboarding`
   - `/ui/inputs`
   - `/ui/processing`
   - `/ui/feed`
   - `/ui/runs?input_id=<id>`
   - `/ui/dev` (dev-gated)
3. `/ui/profiles` is removed.

## 7) Feed Term Attribution

1. Feed term fields (`term_id`, `term_code`, `term_label`, `term_scope`) are derived from `Change.user_term_id`.
2. `Input.user_term_id` remains an input binding hint, not a historical attribution source.
3. This prevents cross-term history drift when one ICS input is reused across terms.

## 8) Structural Notes

1. `app/modules/sync/service.py` and `frontend/lib/hooks/use-dashboard-data.ts` are still large orchestrators.
2. Router boundary tests and private import boundary tests remain enforced in CI.
