# Demo UI Acceptance (Converged v3)

## 1) Startup

1. `cd frontend && npm ci && npm run build && cd ..`
2. `docker compose up -d postgres`
3. `scripts/reset_postgres_db.sh`
4. `source .venv/bin/activate`
5. `uvicorn app.main:app --reload`

Open:

1. `http://localhost:8000/ui`

## 2) Expected Page Set

Only these routes are valid:

1. `/ui/onboarding`
2. `/ui/processing`
3. `/ui/feed`
4. `/ui/emails/review`

Removed pages should 404:

1. `/ui/inputs`
2. `/ui/runs`
3. `/ui/dev`

## 3) Core Flow Acceptance

1. onboarding register with `notify_email + ics.url`
2. redirected to processing on success
3. processing can run manual sync
4. feed shows canonical changes only
5. evidence panel auto-loads structured preview (old/new)
6. email review queue supports:
   - apply
   - archive
   - drop
   - mark viewed
7. apply creates canonical change visible in feed

## 4) Evidence Preview Checks

1. endpoint used is `/v1/changes/{change_id}/evidence/{side}/preview`
2. no download button
3. malformed ICS returns `422 detail.code=evidence_parse_failed`
4. missing evidence returns `404`

## 5) Single-ICS Checks

1. user has at most one ICS input row
2. re-onboarding with new ICS replaces old row
3. replacement baseline failure clears ICS and onboarding returns `needs_ics`

## 6) Optional Integration Checks

1. Gmail/SMTP can be unconfigured; ICS loop still works
2. digest delivery is fixed-slot and not required for base ICS demo
