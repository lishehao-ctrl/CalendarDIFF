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

Core workspace routes:

1. `/ui/onboarding`
2. `/ui/inputs`
3. `/ui/processing`
4. `/ui/feed`
5. `/ui/emails/review`

## 3) Core Flow Acceptance

1. onboarding register with `notify_email + ics.url`
2. ready user visiting `/ui/onboarding` is redirected to `/ui/processing`
3. pages bootstrap via `GET /v1/workspace/bootstrap` (onboarding/user/inputs/config summary)
4. `/ui/inputs` can connect Gmail and soft-delete email inputs
5. processing can run manual sync for active inputs
6. feed shows canonical changes only
7. evidence panel auto-loads structured preview (old/new)
8. email review queue supports:
   - apply
   - archive
   - drop
   - mark viewed
9. apply creates canonical change visible in feed

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
