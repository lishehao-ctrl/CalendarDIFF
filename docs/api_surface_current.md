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

## Agent context endpoints

- `GET /agent/context/workspace`
- `GET /agent/context/changes/{change_id}`
- `GET /agent/context/sources/{source_id}`
- `GET /agent/context/families/{family_id}`

## Agent proposal endpoints

- `GET /agent/proposals`
- `POST /agent/proposals/change-decision`
- `POST /agent/proposals/change-edit-commit`
- `POST /agent/proposals/family-relink-preview`
- `POST /agent/proposals/family-relink-commit`
- `POST /agent/proposals/label-learning-commit`
- `POST /agent/proposals/source-recovery`
- `GET /agent/proposals/{proposal_id}`

## Agent approval endpoints

- `GET /agent/activity/recent`
- `GET /agent/approval-tickets`
- `POST /agent/approval-tickets`
- `GET /agent/approval-tickets/{ticket_id}`
- `POST /agent/approval-tickets/{ticket_id}/confirm`
- `POST /agent/approval-tickets/{ticket_id}/cancel`

Current execution scope is intentionally narrow:

- executable:
  - change decision proposals with direct `approve` / `reject`
  - pending proposal edit commit proposals on `due_date` / `due_time` / `time_precision` / `event_name`
  - source recovery proposals whose action is `run_source_sync`
  - low-risk family relink commit proposals
  - low-risk label-learning add-alias proposals
- not yet executable:
  - reconnect / settings-update proposals
  - canonical edit or broader free-form edit proposals
  - web-only high-risk review proposals

## MCP access token endpoints

Users can now create per-account MCP access tokens through Settings:

- `GET /settings/mcp-tokens`
- `POST /settings/mcp-tokens`
- `DELETE /settings/mcp-tokens/{token_id}`
- `GET /settings/mcp-invocations`

Social channel foundation now lives in Settings too:

- `GET /settings/channel-accounts`
- `POST /settings/channel-accounts`
- `DELETE /settings/channel-accounts/{account_id}`
- `GET /settings/channel-deliveries`

## Public endpoints
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/session`
- `GET /agent/context/workspace`
- `GET /agent/context/changes/{change_id}`
- `GET /agent/context/sources/{source_id}`
- `GET /agent/context/families/{family_id}`
- `GET /agent/proposals`
- `POST /agent/proposals/change-decision`
- `POST /agent/proposals/change-edit-commit`
- `POST /agent/proposals/family-relink-preview`
- `POST /agent/proposals/family-relink-commit`
- `POST /agent/proposals/label-learning-commit`
- `POST /agent/proposals/source-recovery`
- `GET /agent/proposals/{proposal_id}`
- `GET /agent/activity/recent`
- `GET /agent/approval-tickets`
- `POST /agent/approval-tickets`
- `GET /agent/approval-tickets/{ticket_id}`
- `POST /agent/approval-tickets/{ticket_id}/confirm`
- `POST /agent/approval-tickets/{ticket_id}/cancel`
- `GET /settings/profile`
- `PATCH /settings/profile`
- `GET /settings/mcp-tokens`
- `POST /settings/mcp-tokens`
- `DELETE /settings/mcp-tokens/{token_id}`
- `GET /settings/mcp-invocations`
- `GET /settings/channel-accounts`
- `POST /settings/channel-accounts`
- `DELETE /settings/channel-accounts/{account_id}`
- `GET /settings/channel-deliveries`
- `GET /sources`
- `GET /sources/{source_id}/observability`
- `GET /sources/{source_id}/sync-history`
- `GET /sources/{source_id}/llm-invocations`
- `POST /sources`
- `PATCH /sources/{source_id}`
- `DELETE /sources/{source_id}`
- `POST /sources/{source_id}/oauth-sessions`
- `POST /sources/{source_id}/sync-requests`
- `POST /sources/{source_id}/webhooks/{provider}`
- `GET /sync-requests/{request_id}`
- `GET /sync-requests/{request_id}/llm-invocations`
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
