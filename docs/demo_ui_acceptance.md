# Demo UI Acceptance (V2)

## 1) Startup

1. `cd frontend && npm ci && npm run build && cd ..`
2. `docker compose up -d postgres`
3. `scripts/reset_postgres_db.sh`
4. `source .venv/bin/activate`
5. `uvicorn app.main:app --reload`

Open:

1. `http://localhost:8000/ui`

## 2) Expected Page Set

1. `/ui/onboarding`
2. `/ui/inputs`
3. `/ui/processing`
4. `/ui/feed`
5. `/ui/emails/review`

## 3) Core Flow Acceptance

1. onboarding register with `notify_email`
2. connect at least one source from `/ui/inputs` (Gmail OAuth or calendar source API)
3. ready user visiting `/ui/onboarding` is redirected out
4. processing page can trigger manual sync through `POST /v2/sync-requests` + polling
5. feed shows canonical changes via `GET /v2/change-events`
6. review queue works under `/v2/review-items/emails*`

## 4) Evidence Preview Checks

1. endpoint is `/v2/change-events/{change_id}/evidence/{side}/preview`
2. ICS evidence preview is raw text (`events=[]`, `event_count=0`, `preview_text` present)
3. missing evidence returns `404`

## 5) Runtime Failure Semantics

1. sync requests for calendar/gmail sources can end in `FAILED` with:
   - `parse_llm_calendar_schema_invalid`
   - `parse_llm_gmail_schema_invalid`
   - `parse_llm_calendar_upstream_error`
   - `parse_llm_gmail_upstream_error`
   - `parse_llm_timeout`
   - `parse_llm_empty_output`
2. these failures follow normal retry/dead-letter behavior in ingestion workers.
