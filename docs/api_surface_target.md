# API Surface Target Mapping

This document records the intentional breaking changes introduced by the API consolidation.

## New Endpoints

1. `GET /v1/workspace/bootstrap`

## Path Changes

1. `PATCH /v1/inputs/{input_id}/changes/{change_id}/viewed` -> `PATCH /v1/changes/{change_id}/viewed`
2. `GET /v1/emails/queue` -> `GET /v1/review/emails`
3. `POST /v1/emails/{email_id}/route` -> `PATCH /v1/review/emails/{email_id}/route`
4. `POST /v1/emails/{email_id}/mark_viewed` -> `POST /v1/review/emails/{email_id}/viewed`
5. `POST /v1/emails/{email_id}/apply` -> `POST /v1/review/emails/{email_id}/apply`

## Removed Endpoints

1. `POST /v1/inputs/ics`
2. `GET /v1/inputs/{input_id}/changes`
3. `GET /v1/inputs/{input_id}/snapshots`

## Unchanged Core Endpoints

1. `GET /v1/inputs`
2. `POST /v1/inputs/email/gmail/oauth/start`
3. `POST /v1/inputs/{input_id}/sync`
4. `DELETE /v1/inputs/{input_id}`
5. `GET /v1/feed`
6. `GET /v1/changes/{change_id}/evidence/{side}/preview`
7. `GET /v1/events` (retained as a non-main UI endpoint)
8. `GET /health`
