# CalendarDIFF Architecture (Demo Converged v3)

## 1) Runtime Intent

Single stable loop:

1. ingest `ICS + Gmail`
2. compute canonical diffs on ICS timeline
3. route Gmail signals into review queue
4. apply reviewed items into canonical changes
5. deliver digest notifications on fixed schedule

## 2) Domain Boundaries

### User / Onboarding

Owns:

1. `users`
2. onboarding stage (`needs_user|needs_ics|needs_baseline|ready`)

Rule:

1. `ready` requires `onboarding_completed_at` and exactly one ICS row.

### Input Ingestion

Owns:

1. `inputs`
2. `sync_runs`

Rule:

1. input type is only `ics|email`
2. sync lock contention returns `409 code=input_busy`
3. input soft-delete is `is_active=false` (`DELETE /v1/inputs/{input_id}`)

### Canonical Timeline + Audit

Owns:

1. `events`
2. `snapshots`
3. `changes`

Rule:

1. user-facing diff is change-driven (`changes` is the audit surface)
2. runtime reminder types are `created|removed|due_changed`

### Notification / Digest

Owns:

1. `notifications`
2. `digest_send_log`

Rule:

1. digest-only send path
2. fixed schedule slots from config (default `09:00`, `18:00`)

### Email Review

Owns:

1. `email_messages`
2. `email_rule_labels`
3. `email_action_items`
4. `email_rule_analysis`
5. `email_routes`

Rule:

1. Gmail sync writes review queue only
2. canonical mutation requires explicit `POST /v1/review/emails/{email_id}/apply`

## 3) Request Flow

### Onboarding

1. `POST /v1/onboarding/register`
2. upsert user
3. replace/create single ICS input
4. run baseline sync
5. success -> set `onboarding_completed_at`
6. baseline failure -> clear ICS row and return to `needs_ics`

### ICS Sync

1. fetch + parse ICS
2. normalize deadline-like events
3. baseline run seeds canonical without user changes
4. later runs write `created|removed|due_changed` changes
5. enqueue digest notifications

### Gmail Sync

1. load history window
2. fetch metadata + plain text body in-memory
3. evaluate deterministic rule
4. write actionable rows into `email_*`
5. do not write feed changes directly

### Email Apply

1. allowed only when `route=review`
2. modes:
   - `create_new` -> `ChangeType.CREATED`
   - `update_existing` -> `ChangeType.DUE_CHANGED`
   - `remove_existing` -> `ChangeType.REMOVED`
3. apply success -> route becomes `archive`

## 4) Public Surface (Minimal)

1. `/v1/onboarding/*`
2. `/v1/workspace/bootstrap`
3. `/v1/inputs` + `/v1/inputs/{input_id}/sync` + `/v1/inputs/{input_id}` (DELETE)
4. `/v1/events` (debug/query endpoint)
5. `/v1/feed`
6. `/v1/changes/{change_id}/viewed`
7. `/v1/changes/{change_id}/evidence/{side}/preview`
8. `/v1/review/emails/*`
9. `/health`

## 5) Removed Surface

1. `/v1/review_candidates*`
2. `/v1/notification_prefs*`
3. `/v1/notifications/send_digest_now`
4. `/v1/status`
5. `/v1/inputs/{input_id}/runs`
6. `/v1/inputs/{input_id}/deadlines`
7. `/v1/inputs/{input_id}/overrides`
8. `/v1/inputs/{input_id}/changes`
9. `/v1/inputs/{input_id}/snapshots`
10. `/v1/inputs/{input_id}/changes/{change_id}/viewed`
11. `/v1/emails/*` (legacy review namespace)
12. input-scoped download evidence routes
13. `/ui/runs`, `/ui/dev`

## 6) Migration Head

Current Alembic head:

1. `0014_archive_legacy_change_types`
