# Production Release Runbook

## Scope

This runbook records the production launch flow that was actually executed for CalendarDIFF on:

- host: `ubuntu@54.152.242.119`
- domain: `cal.shehao.app`

Use it as the baseline for future single-host releases.

## Release candidate

Release candidate used:

- branch: `codex/release-cut-20260321`
- commit: `5a859d3`

Release cut notes:

- push RC branch first
- then push the same commit to `origin/main`
- ensure AWS checkout is synced to the exact same commit

## Backup

Before reset:

```bash
ssh -i ~/.ssh/aws-main.pem ubuntu@54.152.242.119 \
  'mkdir -p /home/ubuntu/backups/calendardiff && \
   TS=$(date +%Y%m%d-%H%M%S) && \
   OUT=/home/ubuntu/backups/calendardiff/deadline_diff-${TS}.sql.gz && \
   sudo docker exec calendardiff-postgres-1 pg_dump -U postgres deadline_diff | gzip > "$OUT" && \
   ls -lh "$OUT"'
```

Example backup created during launch:

- `/home/ubuntu/backups/calendardiff/deadline_diff-20260321-230841.sql.gz`

## Sync AWS checkout

Preferred pattern:

1. create a git bundle from the local release candidate
2. upload the bundle to AWS
3. fetch bundle on AWS checkout
4. hard reset checkout to bundle HEAD
5. rebuild and restart `frontend` and `public-service`

After sync, verify:

```bash
ssh -i ~/.ssh/aws-main.pem ubuntu@54.152.242.119 \
  'cd /home/ubuntu/apps/CalendarDIFF && git rev-parse --short HEAD'
```

Expected:

- exact release candidate commit
- newly recreated `frontend` / `public-service` containers running that commit

Current default release command:

```bash
scripts/release_aws_main.sh
```

Current script behavior:

- syncs the AWS checkout
- runs `sudo docker compose up -d --build frontend public-service`
- then verifies nginx, `health`, and `login`

## Reset and launch

This launch used `reset-and-launch`, not in-place migration.

Executed steps:

```bash
ssh -i ~/.ssh/aws-main.pem ubuntu@54.152.242.119 '
  set -e
  cd /home/ubuntu/apps/CalendarDIFF
  sudo docker compose stop frontend public-service
  sudo docker compose run --rm public-service bash -lc "./scripts/reset_postgres_db.sh deadline_diff"
  sudo docker compose up -d --build public-service frontend
  sudo docker compose ps
'
```

Result:

- database reset to empty state
- alembic upgraded to head
- frontend and public-service rebuilt and restarted

Note:

- even for normal in-place releases, do not stop at git sync
- if containers are not rebuilt, the host may keep serving old code from old images

## Post-reset smoke

Minimum checks:

```bash
curl https://cal.shehao.app/health
curl -I https://cal.shehao.app/login
```

API auth smoke:

```bash
curl -X POST https://cal.shehao.app/api/backend/auth/login \
  -H "X-API-Key: <APP_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"notify_email":"lishehao@gmail.com","password":"CalendarDiff!2026"}'
```

Expected:

- `health` returns 200
- `login` returns 200
- auth login returns 200 and sets session cookie

## Gmail OAuth repair

Issue encountered:

- production server still used an old `google_client_secret.json`
- local secret only contained localhost callback URIs
- runtime rejected production redirect URI

Expected production redirect URI:

- `https://cal.shehao.app/oauth/callbacks/gmail`

Fix used:

1. update Google OAuth client to include the production redirect URI
2. download fresh client secret JSON
3. back up old server secret
4. replace:
   - `/home/ubuntu/secrets/google_client_secret.json`
5. restart `public-service`

Verification:

```bash
curl -X POST https://cal.shehao.app/api/backend/onboarding/gmail/oauth-sessions \
  -H "X-API-Key: <APP_API_KEY>" \
  -H "Content-Type: application/json" \
  -b <session-cookie>
```

Expected:

- returns 201
- `authorization_url` contains redirect URI:
  - `https://cal.shehao.app/oauth/callbacks/gmail`

## Production onboarding smoke

Validated path:

1. register fresh smoke user
2. login
3. onboarding
4. connect Canvas ICS
5. optionally skip Gmail
6. save monitoring window
7. enter workspace

Admin path also validated:

1. login as bootstrap admin
2. connect Canvas ICS
3. connect Gmail
4. verify:
   - `onboarding/status`
   - `sources`
   - `sources/{id}/observability`
   - `changes/summary`

## Current production outcome

Production state after launch:

- bootstrap admin exists
- Canvas ICS connected
- Gmail connected
- onboarding complete
- `workspace_posture.phase = initial_review`
- baseline review queue populated and usable

## Guardrails

- keep `GMAIL_SECONDARY_FILTER_MODE=off`
- keep `GMAIL_SECONDARY_FILTER_PROVIDER=noop`
- treat BERT / Gmail secondary filtering as an optional pluggable module
- do not block release on BERT model availability, endpoint health, or threshold tuning
- do not deploy uncommitted local worktree state directly
- do not modify `rpg.shehao.app` while releasing CalendarDIFF
