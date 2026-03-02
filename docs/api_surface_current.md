# API Surface Snapshot (Current, V2 Hard-Cut)

This file captures the runtime API surface after the V2 hard cut.

## Workspace

1. `GET /health`

## Onboarding + User

1. `GET /v2/onboarding/status`
2. `POST /v2/onboarding/registrations`
3. `GET /v2/users/me`
4. `PATCH /v2/users/me`

## Input Sources + Sync

1. `POST /v2/input-sources`
2. `GET /v2/input-sources`
3. `PATCH /v2/input-sources/{source_id}`
4. `DELETE /v2/input-sources/{source_id}`
5. `POST /v2/sync-requests`
6. `GET /v2/sync-requests/{request_id}`
7. `POST /v2/oauth-sessions`
8. `GET /v2/oauth-callbacks/{provider}`
9. `POST /v2/webhook-events/{source_id}/{provider}`

## Timeline + Change Events

1. `GET /v2/timeline-events`
2. `GET /v2/change-events`
3. `PATCH /v2/change-events/{change_id}`
4. `GET /v2/change-events/{change_id}/evidence/{side}/preview`

## Review

1. `GET /v2/review-items/emails`
2. `PATCH /v2/review-items/emails/{email_id}`
3. `POST /v2/review-items/emails/{email_id}/views`
4. `POST /v2/review-items/emails/{email_id}/applications`

## Internal APIs

1. `POST /internal/v2/ingest-results/applications`
2. `GET /internal/v2/ingest-results/{request_id}`
3. `POST /internal/v2/ingest-jobs/{job_id}/replays`
4. `POST /internal/v2/ingest-jobs/dead-letter/replays`

## Runtime Parsing Status

1. `calendar` and `gmail` connectors call V2 LLM parsers through `app/modules/llm_gateway/*`.
2. LLM is configured only by environment variables:
   - `INGESTION_LLM_MODEL`
   - `INGESTION_LLM_BASE_URL`
   - `INGESTION_LLM_API_KEY`
3. Gateway is OpenAI-compatible `chat/completions` API only.
4. Parser failures surface through connector errors:
   - `parse_llm_calendar_schema_invalid`
   - `parse_llm_gmail_schema_invalid`
   - `parse_llm_calendar_upstream_error`
   - `parse_llm_gmail_upstream_error`
   - `parse_llm_timeout`
   - `parse_llm_empty_output`
5. Parse failures follow normal retry/dead-letter semantics in ingest jobs.
