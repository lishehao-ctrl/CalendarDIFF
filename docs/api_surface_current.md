# API Surface

## Default base URL
- Public/backend API: `http://localhost:8200`

## Product lanes

User-facing product lanes should be interpreted as:

- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

This document is the current public contract. Retired legacy public paths should return `404`.

## Public endpoints
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`
- `GET /settings/profile`
- `PATCH /settings/profile`
- `GET /sources`
- `GET /sources/{source_id}/observability`
- `GET /sources/{source_id}/sync-history`
- `POST /sources`
- `PATCH /sources/{source_id}`
- `POST /sources/{source_id}/oauth-sessions`
- `POST /sources/{source_id}/sync-requests`
- `GET /sync-requests/{request_id}`
- `POST /onboarding/registrations`
- `GET /onboarding/status`
- `POST /onboarding/canvas-ics`
- `POST /onboarding/gmail/oauth-sessions`
- `POST /onboarding/gmail-skip`
- `POST /onboarding/monitoring-window`
- `GET /changes/summary`
  - returns workbench/intake summary across `Changes`, `Families`, `Manual`, and `Sources`
- `GET /changes`
- `GET /changes/{change_id}`
- `PATCH /changes/{change_id}/views`
- `POST /changes/{change_id}/decisions`
- `POST /changes/batch/decisions`
- `GET /changes/{change_id}/edit-context`
- `GET /changes/{change_id}/evidence/{side}/preview`
- `POST /changes/edits/preview`
- `POST /changes/edits`
- `POST /changes/{change_id}/label-learning/preview`
- `POST /changes/{change_id}/label-learning`
- `GET /families/raw-type-suggestions`
- `POST /families/raw-type-suggestions/{suggestion_id}/decisions`
- `GET /families`
- `POST /families`
- `PATCH /families/{family_id}`
- `GET /families/status`
- `GET /families/courses`
- `GET /families/raw-types`
- `POST /families/raw-types/relink`
- `GET /manual/events`
- `POST /manual/events`
- `PATCH /manual/events/{entity_uid}`
- `DELETE /manual/events/{entity_uid}`
- `GET /health`
