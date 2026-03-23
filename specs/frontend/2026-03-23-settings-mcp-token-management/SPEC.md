# Settings MCP Token Management

## Summary

Expose the new backend MCP token capability inside `Settings` so real users can self-serve QClaw/OpenClaw access without touching raw API calls.

This is not a generic API key screen.
It is a focused product surface for:

- creating a CalendarDIFF MCP token
- seeing existing MCP tokens
- revoking a token
- understanding how to use the token with QClaw/OpenClaw

This should stay thin and safe.

## Product Goal

The user should be able to answer these questions immediately:

1. what is this token for
2. how do I create one
3. where do I paste it
4. can I revoke it later
5. which token was used most recently

## Constraints

- Do not invent backend state that the API does not return.
- Do not ever re-display a token after the create response disappears.
- Do not imply that revoked tokens can be restored.
- Do not mix MCP token management into the main timezone form in a confusing way.
- Keep this under `Settings`, not a new top-level lane.
- Use the existing bilingual/i18n system.

## Backend Contract

Existing endpoints:

- `GET /settings/mcp-tokens`
- `POST /settings/mcp-tokens`
- `DELETE /settings/mcp-tokens/{token_id}`

### `GET /settings/mcp-tokens`

Returns list items:

- `token_id`
- `label`
- `scopes`
- `last_used_at`
- `expires_at`
- `revoked_at`
- `created_at`

### `POST /settings/mcp-tokens`

Request:

- `label`
- `expires_in_days`

Response:

- all list fields above
- plus one extra field:
  - `token`

Important:

- `token` is only returned on creation
- the UI must treat it as one-time visible secret

### `DELETE /settings/mcp-tokens/{token_id}`

Returns the token row with updated `revoked_at`.

## Page Placement

Add a second card/section inside `SettingsPanel`.

Current section:
- account / timezone / language

New section:
- MCP access

Recommended order:

1. account/timezone
2. MCP access

## UI Shape

## Section header

Eyebrow:
- `MCP Access`

Title:
- `Connect QClaw or OpenClaw`

Summary:
- explain that MCP tokens let external agent clients access this user's CalendarDIFF account
- explicitly say each token belongs to this account only

## Create token card

Fields:
- `Token label`
- `Expires in`

Recommended `Expires in` options:
- `7 days`
- `30 days`
- `90 days`
- `365 days`

CTA:
- `Create MCP token`

After success:
- show a one-time result panel containing:
  - token value
  - copy button
  - warning that it will not be shown again
  - short “how to use with QClaw/OpenClaw” text

Secondary CTA in success panel:
- `Close`

## Token list

Each row should show:
- label
- status
- created time
- expires time
- last used time
- scope summary

Status mapping:
- if `revoked_at` exists -> `Revoked`
- else if `expires_at` exists and already in past -> `Expired`
- else -> `Active`

Actions per row:
- if active -> `Revoke`
- if revoked or expired -> no primary action

Do not show:
- raw token secret

## Empty state

Title:
- `No MCP tokens yet`

Description:
- tell user that they can create a token when they want to connect QClaw/OpenClaw

## Loading state

Use existing `LoadingState`

## Error state

Use existing `ErrorState`

Create-token failure:
- inline banner on the MCP card

Revoke failure:
- inline row or section banner

## Interaction Rules

### Create

Flow:

1. user fills label and expiry
2. submit
3. POST `/settings/mcp-tokens`
4. refresh token list
5. show one-time secret panel

Important:

- do not clear the one-time secret until the user dismisses it
- if the list refresh fails but create succeeds, keep showing the token panel and show a soft warning

### Copy

Requirements:

- one-click copy for token value
- visual confirmation after copy

### Revoke

Flow:

1. click revoke
2. confirmation dialog
3. DELETE `/settings/mcp-tokens/{token_id}`
4. refresh token list

Confirmation copy should make it obvious:
- existing clients using this token will stop working

## Bilingual Copy Requirements

Add dictionary entries for:

- MCP access section title/summary
- token label
- expires in
- create token
- one-time secret warning
- copy token
- copied state
- revoke action
- revoke confirm title/body
- no tokens empty state
- last used / created / expires labels
- active / revoked / expired badges
- QClaw/OpenClaw usage hint

Do not translate:
- the token value itself
- literal product names `QClaw`, `OpenClaw`, `MCP`

## API Client Work

Add frontend API helpers in `frontend/lib/api/settings.ts`:

- `getMcpTokens()`
- `createMcpToken(payload)`
- `revokeMcpToken(tokenId)`

Add frontend types in `frontend/lib/types.ts`:

- `McpAccessToken`
- `McpAccessTokenCreateResponse`

## Suggested Component Structure

Inside `SettingsPanel`:

- keep existing account/timezone card unchanged as much as possible
- add a new presentational block:
  - `McpAccessCard`
    - create form
    - token list
    - one-time token reveal panel

If splitting helps readability, create:

- `frontend/components/settings-mcp-access-card.tsx`

## Suggested Usage Hint

Include a compact hint block like:

- `Server URL: https://cal.shehao.app/mcp`
- `Auth: Bearer token`

This is helpful because users otherwise won't know what they are creating the token for.

## Non-goals

- no OAuth client setup UI
- no scope editor UI
- no usage analytics dashboard
- no token rename flow
- no secret re-show after creation
- no public docs page rewrite in this pass

## Validation

Frontend required:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

Manual acceptance:

1. open `Settings`
2. create a token
3. copy the token
4. refresh page
5. confirm token secret is no longer visible
6. revoke token
7. confirm list status updates to revoked
