# CalendarDIFF

Calendar deadline diff watcher:

- FastAPI backend (`/v1/*`)
- PostgreSQL-first persistence
- Scheduler + PG advisory lock
- Next.js UI static export served by backend at `/ui`

## Quick Start (First Time)

1. Create venv and install backend deps:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

2. Build UI static assets:

```bash
cd frontend
npm ci
npm run build
cd ..
```

3. Start PostgreSQL and reset DB:

```bash
docker compose up -d postgres
scripts/reset_postgres_db.sh
```

4. Start backend:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

5. Open demo:

- `http://localhost:8000/ui`
- root UI routing:
  - onboarding `stage != ready` -> `/ui/onboarding`
  - onboarding `stage = ready` -> `/ui/processing`

Important:

- Acceptance entry is always `8000/ui` (not `3000/ui`).

## Daily Start (Fast Path)

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

If UI changed or `frontend/out` is stale, rebuild:

```bash
cd frontend && npm run build && cd ..
```

## How To Run Email Test (MailHog)

### Minimal path

1. Start MailHog:

```bash
docker rm -f calendardiff-mailhog 2>/dev/null || true
docker run --name calendardiff-mailhog -d -p 1025:1025 -p 8025:8025 mailhog/mailhog:v1.0.1
```

2. Set SMTP env in `.env` (optional extended path; default demo can keep notifications off):

```env
ENABLE_NOTIFICATIONS=false
SMTP_HOST=127.0.0.1
SMTP_PORT=1025
SMTP_USER=
SMTP_PASS=
SMTP_USE_TLS=false
SMTP_FROM=no-reply@example.com
SMTP_TO=notify@example.com
```

3. Restart backend (config is loaded at startup).
4. Follow full runbook:

- `docs/manual_email_test.md`

### What should pass

1. First sync is baseline: `is_baseline_sync=true`, `changes_created=0`, no email.
2. After ICS change, second sync is `CHANGED` and MailHog receives email.
3. Wrong `SMTP_PORT` triggers `EMAIL_FAILED`.
4. `last_email_sent_at` must stay unchanged on failed send.

### APIs used for verification

All require `X-API-Key`.

- `GET /v1/inputs`
- `GET /v1/inputs/{id}/runs?limit=20`

## Gmail Email Input + Review Queue (MVP)

This project supports `Input.type=email` with `provider=gmail`.

### Optional env vars (for Gmail extension)

```env
GMAIL_OAUTH_CLIENT_ID=...
GMAIL_OAUTH_CLIENT_SECRET=...
GMAIL_OAUTH_REDIRECT_URI=http://localhost:8000/v1/oauth/gmail/callback
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
APP_BASE_URL=http://localhost:8000
```

### Local OAuth setup (Google Cloud)

1. Create OAuth client (Web application).
2. Add redirect URI: `http://localhost:8000/v1/oauth/gmail/callback`.
3. Restart backend after updating `.env`.
4. Open `http://localhost:8000/ui`.
5. Complete onboarding first, then run sync from `/ui/processing`.

### Runtime semantics

1. First sync is baseline-first: stores cursor (`historyId`), no notification.
2. Later syncs process only messages after cursor.
3. Each new Gmail `message_id` creates one `Change` (`event_uid=message_id`).
4. Change metadata is in `after_json`:
   - `subject`, `snippet`, `internal_date`, `from`, `gmail_message_id`, `open_in_gmail_url`.
5. Existing notifier pipeline and dedup rules are reused.
6. Email review queue:
   - actionable metadata/snippet signals are ingested into `email_*` review tables
   - queue API: `/v1/emails/queue`, `/v1/emails/{email_id}/route`, `/v1/emails/{email_id}/mark_viewed`, `/v1/emails/{email_id}/apply`
   - `apply` writes canonical changes (create new or update existing) through the same diff/audit pipeline
   - no auto-apply on sync path

### Verification APIs

- `GET /v1/inputs`
- `GET /v1/inputs/{id}/changes?limit=20`
- `GET /v1/inputs/<id>/runs?limit=20`

## User-Only Input Priority (EMAIL > Calendar)

The input model is user-only (`user + inputs`):

1. One user can have multiple inputs overall, but exactly one ICS input record (`type=ics`) at any time.
2. Priority is fixed as `EMAIL > Calendar` in feed ordering and notification sequencing.
3. Calendar notifications can be delayed by user-level window (`calendar_delay_seconds`, default `120`).
4. No cross-input dedup is applied (email and calendar changes are both preserved for traceability).

### Onboarding + User APIs

- `GET /v1/onboarding/status`
- `POST /v1/onboarding/register` (required fields: `notify_email + first ICS URL`)
- `GET /v1/user`
- `PATCH /v1/user` (edit `notify_email`, `calendar_delay_seconds`)
- `GET /v1/emails/queue`
- `POST /v1/emails/{email_id}/route`
- `POST /v1/emails/{email_id}/mark_viewed`
- `POST /v1/emails/{email_id}/apply`

Onboarding completion contract:

1. A user is **registered** when `notify_email` is valid.
2. A user is **onboarded** only when:
   - `notify_email` valid
   - first ICS input exists
   - first ICS baseline sync succeeds
3. `/v1/onboarding/status` stages:
   - `needs_user | needs_ics | needs_baseline | ready`
4. `POST /v1/onboarding/register` writes `users.onboarding_completed_at` only after successful baseline sync.
5. Re-running onboarding with a new ICS URL performs replace-by-recreate:
   - previous ICS input row is removed
   - new ICS row becomes the single ICS record
6. If replacement baseline fails, the new ICS is cleared and onboarding is downgraded to `needs_ics`.
7. Gate errors:
   - `user_not_initialized` (not registered)
   - `user_onboarding_incomplete` (registered, not onboarded)
8. `PATCH /v1/user` rejects clearing `notify_email`.
9. Protected endpoints return `409` before onboarding is ready:
   - `/v1/feed`
   - `/v1/inputs*`
   - `/v1/inputs/email/gmail/oauth/start`
   - `/v1/notification_prefs*`
   - `/v1/notifications/send_digest_now`
   - `/v1/emails*`

### Input Layer policy (fixed)

1. Input creation UI focuses on Gmail connection; ICS baseline is managed in onboarding.
2. Input-level `notify_email` is not configurable and not used for delivery routing.
3. Input-level `interval_minutes` is fixed at `15` minutes (DB-enforced).
4. Input create payloads reject legacy fields (`interval_minutes`, `notify_email`) with `422`.
5. Effective recipient is resolved at user level: `user.notify_email`.
6. First ICS successful sync is the onboarding baseline. It suppresses first-run diff/notification noise.
7. Replacing ICS URL is destructive for old ICS timeline history by design.

### Feed API

- `GET /v1/feed`
  - Query: `input_id?`, `view=all|unread`, `input_types=email,ics`, `limit`, `offset`
  - Ordered by: `priority_rank ASC (email first)`, then `detected_at DESC`, then `id DESC`
  - Extra fields: `input_type`, `priority_rank`, `priority_label`, `notification_state`, `deliver_after`
  - Baseline behavior:
    - first-ever ICS sync is baseline-first (no diff notification)
    - subsequent syncs emit normal diff/notify relative to canonical timeline
  - Old/New summary times in UI are rendered in the viewer's local timezone.

### UI information architecture

1. `/ui` -> onboarding gate:
   - `GET /v1/onboarding/status` then route by stage
   - `stage=ready` -> `/ui/processing`
   - otherwise -> `/ui/onboarding`
2. `/ui/onboarding` -> submit `notify_email + ics.url` to `POST /v1/onboarding/register`.
3. `/ui/processing` -> health, manual sync, and runtime diagnostics (primary control surface).
4. `/ui/feed` -> aggregated change feed (EMAIL > Calendar ordering); onboarding-incomplete direct access redirects to onboarding.
5. `/ui/emails/review` -> email review queue for Apply/Archive/Drop/Mark viewed operations.

## Notification Digest Schedule

Notification digests are user-configurable and idempotent by local-date + local-time slot.

APIs:

- `GET /v1/notification_prefs`
- `PUT /v1/notification_prefs`
- `POST /v1/notifications/send_digest_now`

Preferences payload:

```json
{
  "digest_enabled": true,
  "timezone": "America/Los_Angeles",
  "digest_times": ["09:00", "18:30"]
}
```

Validation:

1. `digest_times` format: `HH:MM` 24h.
2. Allowed count: 1..6.
3. Times are sorted and de-duplicated before persistence.

## Health / Debug

```bash
curl http://localhost:8000/health
curl -H "X-API-Key: <APP_API_KEY>" http://localhost:8000/v1/status
curl http://localhost:8000/ui/app-config.js
```

## Run Tests

```bash
source .venv/bin/activate
python -m pytest -q
cd frontend && npm run typecheck && npm run lint && npm run build
```

## LLM Email Labeling Pipeline

Offline silver-label generation tools are in `tools/labeling/`.

Quick path:

```bash
source .venv/bin/activate
python -m tools.label_emails --in data/DDW-CANDIDATE.mbox --out data/labeled.jsonl --workers 10
python tools/labeling/validate_labeled.py
```

Important:

1. Do not commit `data/` or any raw email content.
2. Do not commit keys/tokens/secrets.
3. Invalid model outputs are repaired up to 2 rounds; rows still invalid are written to `label_errors.jsonl` only (not added to `labeled.jsonl`).
4. See `tools/labeling/README.md` for full env/config details.

## Notes

1. Manual `POST /v1/inputs/{id}/sync` returns `409 input_busy` on input lock contention (recoverable).
2. Conflict detail now includes `status=LOCK_SKIPPED` and `retry_after_seconds` for recoverable UX.
3. Busy error code is `input_busy`.
4. UI handles busy lock contention with one auto retry after 10 seconds plus a `Retry now` action.
5. Scheduler path is still non-blocking and uses a 30-second cooldown after scheduler `LOCK_SKIPPED`.
6. For LOCK_SKIPPED acceptance steps, use `docs/runbooks/scheduler_multi_instance_acceptance.md`.
7. Input-centric API cutover is complete: use `/v1/inputs*` and `/v1/feed`.
8. ICS input creation is onboarding-only (`POST /v1/onboarding/register`); `/v1/inputs/ics` is removed.
9. Legacy `/v1/sources*` and `/v1/changes/feed` endpoints are removed.
10. Change and snapshot detail routes are input-scoped:
    - `GET /v1/inputs/{input_id}/changes`
    - `PATCH /v1/inputs/{input_id}/changes/{change_id}/viewed`
    - `GET /v1/changes/{change_id}/evidence/{side}/preview`
    - `GET /v1/inputs/{input_id}/snapshots`
11. Before onboarding is ready, protected endpoints return:
    - status `409`
    - `detail.code = "user_not_initialized"` or `"user_onboarding_incomplete"`

## More Docs

- Architecture (current runtime): `docs/architecture.md`
- Legacy cleanup matrix: `docs/legacy_cleanup.md`
- Legacy migration archive notes: `docs/legacy_migrations/README.md`
- Demo acceptance: `docs/demo_ui_acceptance.md`
- Manual email test: `docs/manual_email_test.md`
- Gmail EMAIL input runbook: `docs/runbooks/gmail_email_input_mvp.md`
- Scheduler multi-instance runbook: `docs/runbooks/scheduler_multi_instance_acceptance.md`
