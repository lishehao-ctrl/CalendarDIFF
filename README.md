# CalendarDIFF

CalendarDIFF is a deadline-diff demo focused on one core job:

1. ingest Canvas ICS + Gmail inputs
2. detect canonical deadline changes
3. review email-derived actions before apply
4. send digest notifications on fixed slots

## Core Runtime Goals

1. single user workspace
2. hard invariant: one user has exactly one ICS input row
3. change types for alerts: `created`, `removed`, `due_changed`
4. Gmail is review-first: sync writes review queue, not feed changes
5. notifications are digest-only (fixed `09:00`, `18:00`)

## Runtime Stack

1. FastAPI backend
2. PostgreSQL + Alembic
3. APScheduler + Postgres advisory locks
4. Next.js static UI (served by backend at `/ui`)

## UI Surface (Minimal)

1. `/ui/onboarding`
2. `/ui/inputs`
3. `/ui/processing`
4. `/ui/feed`
5. `/ui/emails/review`

Removed UI routes:

1. `/ui/runs`
2. `/ui/dev`

## Quick Start

1. install deps and create env:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

2. build frontend:

```bash
cd frontend
npm ci
npm run build
cd ..
```

3. start postgres + reset schema:

```bash
docker compose up -d postgres
scripts/reset_postgres_db.sh
```

4. start backend:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

5. open:

```text
http://localhost:8000/ui
```

## Configuration Profiles

Use progressive profiles instead of filling every possible environment variable.

### 1) Core (required)

Minimum config to run the app locally:

```env
APP_API_KEY=dev-api-key-change-me
APP_SECRET_KEY=7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff
ENABLE_NOTIFICATIONS=false
```

This is enough for the core flow. OAuth/SMTP are optional extensions.

### 2) Gmail OAuth (optional, only for Connect Gmail)

Append these values to `.env` only when enabling Gmail input:

```env
APP_BASE_URL=http://localhost:8000
GMAIL_OAUTH_CLIENT_SECRETS_FILE=/Users/<you>/.secrets/calendar-diff/client_secret.jsonl
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
```

Google Cloud setup checklist:

1. enable Gmail API
2. configure OAuth consent screen
3. add your Gmail account under Test users (Testing mode)
4. create OAuth 2.0 Client ID (`Web application`)
5. ensure the first redirect URI in your client secrets file is `http://localhost:8000/v1/oauth/gmail/callback`
6. keep the file outside repo and run `chmod 600 /path/to/client_secret.jsonl`

Reconnect flow:

1. open `/ui/inputs`
2. click `Connect Gmail`
3. authorize and return to `/ui/inputs` (the page auto-runs one initial sync for the connected input)

### 3) SMTP Digest (optional, only for real email delivery)

Enable notifications and append SMTP config when you want actual digest emails:

```env
ENABLE_NOTIFICATIONS=true
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASS=
SMTP_USE_TLS=false
SMTP_FROM=no-reply@example.com
SMTP_TO=you@example.com
```

### Testing (on demand)

Add this only when running test suite against a dedicated test database:

```env
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_test
```

### Gmail OAuth Notes

1. First-time Gmail connect requires `refresh_token`; if Google does not return it, reconnect and grant offline access.
2. Repeated authorize may return only `access_token`; runtime keeps existing stored `refresh_token`.
3. OAuth success callback triggers one automatic sync in `/ui/inputs` for immediate connectivity check.
4. The first Gmail sync initializes the history cursor and does not backfill historical mailbox messages.
5. On token-refresh failure, sync marks the input failed and asks for reconnect (input is not auto-deactivated).
6. Scheduler default remains 15 minutes; scheduler sync and manual sync use the same backend path.

### OAuth Troubleshooting

1. `redirect_uri_mismatch`
   - ensure the first `redirect_uris` entry in your client secrets file matches expected callback URI exactly.
2. `Gmail OAuth client secrets file is not configured`
   - check `GMAIL_OAUTH_CLIENT_SECRETS_FILE`.
3. `client secrets file must be outside the repository`
   - move the file outside repo path and update `GMAIL_OAUTH_CLIENT_SECRETS_FILE`.
4. `client secrets file permissions are too open`
   - run `chmod 600 /path/to/client_secret.jsonl`.
5. `client secrets file content is invalid`
   - download a fresh OAuth client secrets file from Google Cloud and retry.
6. refresh/token errors (`invalid_grant`, missing refresh token)
   - reconnect in `/ui/inputs`; if needed revoke app access in Google account first, then reconnect.

## Main Demo Flow

1. `Onboarding` (first-time only): submit `notify_email + ics.url`.
2. `Inputs`: connect/deactivate Gmail inputs and manage input runtime status.
3. `Processing`: run manual sync (`POST /v1/inputs/{input_id}/sync`).
4. `Feed`: inspect canonical diff cards and evidence preview.
5. `Email Review`: route/apply email queue items.

## Public API (Current Core)

### Onboarding

1. `GET /v1/onboarding/status`
2. `POST /v1/onboarding/register`

### Inputs / Processing

1. `GET /v1/inputs`
2. `POST /v1/inputs/email/gmail/oauth/start`
3. `DELETE /v1/inputs/{input_id}` (soft delete, blocks sole active ICS)
4. `POST /v1/inputs/{input_id}/sync`
5. `GET /v1/events`
6. `GET /v1/inputs/{input_id}/changes`
7. `PATCH /v1/inputs/{input_id}/changes/{change_id}/viewed`
8. `GET /v1/inputs/{input_id}/snapshots`
9. `GET /health`

### Feed / Evidence

1. `GET /v1/feed`
2. `GET /v1/changes/{change_id}/evidence/{side}/preview`

### Email Review

1. `GET /v1/emails/queue`
2. `POST /v1/emails/{email_id}/route` (`drop|archive|review`)
3. `POST /v1/emails/{email_id}/mark_viewed`
4. `POST /v1/emails/{email_id}/apply`

`apply.mode`:

1. `create_new`
2. `update_existing` (requires `target_event_uid`)
3. `remove_existing` (requires `target_event_uid`)

## Removed API Surface

1. `/v1/review_candidates*`
2. `/v1/user/terms*`
3. `/v1/status`
4. `/v1/notification_prefs*`
5. `/v1/notifications/send_digest_now`
6. `/v1/inputs/{input_id}/runs`
7. `/v1/inputs/{input_id}/deadlines`
8. `/v1/inputs/{input_id}/overrides`
9. `/v1/inputs/{input_id}/changes/{change_id}/evidence/{side}/download`
10. `/v1/inputs/{input_id}/changes/{change_id}/evidence/{side}/preview`
11. `/v1/inputs/ics`

## One-ICS Invariant

1. each user can have at most one ICS input row
2. onboarding re-register with new ICS URL uses replace semantics (delete old + create new)
3. if replacement baseline fails, ICS is cleared and onboarding falls back to `needs_ics`

## Tests

```bash
source .venv/bin/activate
python -m pytest -q
cd frontend && npm run typecheck && npm run lint && npm run build
```

## More Docs

1. `docs/architecture.md`
2. `docs/demo_ui_acceptance.md`
3. `docs/legacy_cleanup.md`
4. `docs/manual_email_test.md`
5. `docs/runbooks/gmail_email_input_mvp.md`
6. `docs/runbooks/scheduler_multi_instance_acceptance.md`
