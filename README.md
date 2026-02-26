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

## UI Surface (Minimal 4 Pages)

1. `/ui/onboarding`
2. `/ui/processing`
3. `/ui/feed`
4. `/ui/emails/review`

Removed UI routes:

1. `/ui/inputs`
2. `/ui/runs`
3. `/ui/dev`

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

## Default Demo Config

For first-run demo stability, keep external integrations optional:

```env
ENABLE_NOTIFICATIONS=false
```

Gmail OAuth and SMTP can be added later. ICS-only flow still runs end-to-end.

## Main Demo Flow

1. `Onboarding`: submit `notify_email + ics.url`.
2. `Processing`: run manual sync (`POST /v1/inputs/{input_id}/sync`).
3. `Feed`: inspect canonical diff cards and evidence preview.
4. `Email Review`: route/apply email queue items.

## Public API (Current Core)

### Onboarding

1. `GET /v1/onboarding/status`
2. `POST /v1/onboarding/register`

### Inputs / Processing

1. `GET /v1/inputs`
2. `POST /v1/inputs/email/gmail/oauth/start`
3. `POST /v1/inputs/{input_id}/sync`
4. `GET /v1/inputs/{input_id}/changes`
5. `PATCH /v1/inputs/{input_id}/changes/{change_id}/viewed`
6. `GET /v1/inputs/{input_id}/snapshots`
7. `GET /health`

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
