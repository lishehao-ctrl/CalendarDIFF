# API Surface Snapshot (Current, V2)

This document captures the active HTTP API surface after the three-layer runtime cutover.

Deployment note:

1. Single HTTP backend entrypoint: `uvicorn app.main:app`
2. No gateway proxy and no split API services

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

Notes:

1. `GET /v2/change-events` defaults to approved changes only (`review_status=approved`).
2. `GET /v2/timeline-events` reads canonical events after review approval.
3. `source_id` mapping/filtering for new rows is based on `proposal_sources_json`.

## Review

1. `GET /v2/review-items/emails`
2. `PATCH /v2/review-items/emails/{email_id}`
3. `POST /v2/review-items/emails/{email_id}/views`
4. `POST /v2/review-items/emails/{email_id}/applications` (deprecated; migration hint only)
5. `GET /v2/review-items/changes`
6. `PATCH /v2/review-items/changes/{change_id}/views`
7. `POST /v2/review-items/changes/{change_id}/decisions`

## Internal APIs

1. `POST /internal/v2/ingest-results/applications`
2. `GET /internal/v2/ingest-results/{request_id}`
3. `POST /internal/v2/ingest-jobs/{job_id}/replays`
4. `POST /internal/v2/ingest-jobs/dead-letter/replays`

## Ingestion LLM Runtime (No API Change)

1. Calendar/Gmail parsers call `app/modules/llm_gateway/*`.
2. Gateway protocol is OpenAI-compatible `chat/completions`.
3. Runtime env:
   - `INGESTION_LLM_MODEL`
   - `INGESTION_LLM_BASE_URL`
   - `INGESTION_LLM_API_KEY`

## Eval Tooling (CLI, Not HTTP)

1. `python scripts/eval_ingestion_llm_pass_rate.py --dataset-root data/synthetic/v2_ddlchange_160 --report data/synthetic/v2_ddlchange_160/qa/llm_pass_rate_report.json --fail-on-threshold`
