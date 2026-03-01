# Gmail Email Input Runbook (V2)

## Goal

1. Gmail sync writes actionable rows to review queue.
2. Canonical changes appear after review apply.

## Prerequisites

1. Backend running at `http://localhost:8000`.
2. OAuth client configured.
3. Redirect URI includes `http://localhost:8000/v2/oauth-callbacks/gmail`.

## Setup

1. Create user profile: `POST /v2/onboarding/registrations`.
2. Create Gmail source: `POST /v2/input-sources`.
3. Start OAuth: `POST /v2/oauth-sessions`.
4. Complete callback at `GET /v2/oauth-callbacks/gmail`.
5. Trigger sync: `POST /v2/sync-requests`.
6. Poll sync status: `GET /v2/sync-requests/{request_id}`.

## Verification APIs

1. `GET /v2/input-sources`
2. `GET /v2/sync-requests/{request_id}`
3. `GET /v2/review-items/emails?route=review`
4. `POST /v2/review-items/emails/{email_id}/applications`
5. `GET /v2/change-events`

## Troubleshooting

1. OAuth fails: verify callback URI and secrets file permissions.
2. Sync returns `AUTH_FAILED`: reconnect Gmail source.
3. Review queue empty: trigger another sync and inspect `connector_result` in sync status.
