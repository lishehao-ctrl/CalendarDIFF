# Scheduler Multi-Instance Acceptance Runbook

## Goal

Validate that two API instances sharing the same PostgreSQL database:

1. run automatic scheduler ticks,
2. produce snapshots/diffs without manual sync clicks,
3. do not emit duplicate notifications for the same change.

## Prerequisites

1. Docker is running.
2. Project virtualenv exists at `.venv`.
3. `.env` has a valid `APP_API_KEY`.

## Quick Path (Automated)

```bash
scripts/smoke_scheduler_multi_instance.sh
```

Expected terminal output:

- `notification_dedup_ok total_notifications=...`
- `Smoke success: scheduler ran on two instances without duplicate notifications.`

## What the script does

1. Starts PostgreSQL via `docker compose up -d postgres`.
2. Resets DB via `scripts/reset_postgres_db.sh`.
3. Starts local ICS feed server on `127.0.0.1:8765`.
4. Starts SMTP debug sink on `127.0.0.1:1025`.
5. Starts two API instances on ports `8000` and `8001` with scheduler enabled.
6. Creates one input and waits for scheduler baseline sync.
7. Mutates ICS content and waits for scheduler-generated diff.
8. Asserts `notifications` table has no `change_id` with count > 1.

## Manual Verification (Optional)

1. Check health endpoints:
   - `curl http://127.0.0.1:8000/health`
   - `curl http://127.0.0.1:8001/health`
2. Check scheduler lock skip behavior:
   - one instance should report lock skips over time
3. Check changes:
   - `curl -H "X-API-Key: <APP_API_KEY>" "http://127.0.0.1:8000/v1/inputs/<id>/changes"`
4. Check input list runtime state:
   - `curl -H "X-API-Key: <APP_API_KEY>" "http://127.0.0.1:8000/v1/inputs"`
5. Check notification dedup in DB:
   - no duplicate rows per `change_id` in `notifications`

## LOCK_SKIPPED UX/UAT (Manual Sync Contention)

Goal: verify lock contention is recoverable and user-facing behavior stays neutral.

### Scenario A: Two instances (`8000` + `8001`)

1. Prepare one input id (`INPUT_ID`) in shared DB.
2. Trigger manual sync at the same time from both instances:
   - `curl -sS -X POST "http://127.0.0.1:8000/v1/inputs/${INPUT_ID}/sync" -H "X-API-Key: <APP_API_KEY>"`
   - `curl -sS -X POST "http://127.0.0.1:8001/v1/inputs/${INPUT_ID}/sync" -H "X-API-Key: <APP_API_KEY>"`
3. Expected:
   - one request runs normally (`200`)
   - one request returns `409` with detail containing:
     - `status=LOCK_SKIPPED`
     - `code=input_busy`
     - `retry_after_seconds=10`

### Scenario B: Single instance concurrent clicks

1. Open Dashboard and click `Sync now` rapidly on the same input (or send two concurrent `POST /sync` requests).
2. Expected UI behavior:
   - show neutral busy hint (`Sync in progress`)
   - auto retry once after 10 seconds
   - if still busy, keep `Retry now` action available
3. Expected behavior:
   - one request receives `409 code=input_busy`
   - another request succeeds
   - health and input list runtime fields advance after lock is released

## Failure Hints

1. If API never becomes healthy:
   - inspect `/tmp/deadline_diff_smoke/api_a.log` and `api_b.log`
2. If no changes are detected:
   - verify ICS file update was applied in script logs
   - verify input `interval_minutes` and scheduler tick values
3. If duplicates are detected:
   - inspect `notifications` rows and unique constraints
   - verify migration applied `uq_notifications_change_channel`
