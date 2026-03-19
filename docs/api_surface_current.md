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

Important:

- some legacy public endpoints still exist on this branch
- they should not define new product language or new UI concepts

## Public endpoints
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`
- `GET /profile/me`
- `PATCH /profile/me`
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
- `POST /onboarding/term-binding`
- `GET /review/summary`
- `GET /review/changes`
- `GET /review/changes/{change_id}`
- `PATCH /review/changes/{change_id}/views`
- `POST /review/changes/{change_id}/decisions`
- `POST /review/changes/batch/decisions`
- `GET /review/changes/{change_id}/edit-context`
- `GET /review/changes/{change_id}/evidence/{side}/preview`
- `POST /review/edits/preview`
- `POST /review/edits`
- `POST /review/changes/{change_id}/label-learning/preview`
- `POST /review/changes/{change_id}/label-learning`
- `GET /review/raw-type-suggestions`
- `POST /review/raw-type-suggestions/{suggestion_id}/decisions`
- `GET /review/course-work-item-families`
- `POST /review/course-work-item-families`
- `PATCH /review/course-work-item-families/{family_id}`
- `GET /review/course-work-item-families/status`
- `GET /review/course-work-item-families/courses`
- `GET /review/course-work-item-raw-types`
- `POST /review/course-work-item-raw-types/relink`
- `GET /events/manual`
- `POST /events/manual`
- `PATCH /events/manual/{entity_uid}`
- `DELETE /events/manual/{entity_uid}`
- `GET /health`
