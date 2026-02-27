# API Surface Snapshot (Current)

This file captures the runtime API surface after the workspace/bootstrap + review namespace refactor.

## Workspace

1. `GET /health`
2. `GET /v1/workspace/bootstrap`

## Onboarding + User

1. `GET /v1/onboarding/status`
2. `POST /v1/onboarding/register`
3. `GET /v1/user`
4. `PATCH /v1/user`

## Inputs + Processing

1. `GET /v1/inputs`
2. `POST /v1/inputs/email/gmail/oauth/start`
3. `POST /v1/inputs/{input_id}/sync`
4. `DELETE /v1/inputs/{input_id}`
5. `GET /v1/events` (debug/query endpoint)
6. `GET /v1/oauth/gmail/callback`

## Feed + Changes

1. `GET /v1/feed`
2. `PATCH /v1/changes/{change_id}/viewed`
3. `GET /v1/changes/{change_id}/evidence/{side}/preview`

## Email Review

1. `GET /v1/review/emails`
2. `PATCH /v1/review/emails/{email_id}/route`
3. `POST /v1/review/emails/{email_id}/viewed`
4. `POST /v1/review/emails/{email_id}/apply`
