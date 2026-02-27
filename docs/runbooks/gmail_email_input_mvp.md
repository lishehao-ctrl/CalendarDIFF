# Gmail Email Input Runbook (Queue-First)

## Goal

Validate Gmail ingestion under current runtime semantics:

1. Gmail sync writes actionable rows to `email_*` review queue
2. Gmail sync does not create feed changes directly
3. canonical changes appear only after review `apply`

## Prerequisites

1. backend is running (`http://localhost:8000`)
2. PostgreSQL schema is at head
3. `.env` starts from the README `Core (required)` profile.
4. Google Cloud OAuth setup is complete:
   - Gmail API enabled
   - OAuth consent screen configured
   - test Gmail account added to Test users (Testing mode)
   - OAuth client type is `Web application`
   - first redirect URI in client secrets file is exactly `http://localhost:8000/v1/oauth/gmail/callback`
5. append OAuth values to `.env` (from README `Gmail OAuth` profile):

```env
APP_BASE_URL=http://localhost:8000
GMAIL_OAUTH_CLIENT_SECRETS_FILE=/Users/<you>/.secrets/calendar-diff/client_secret.jsonl
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
```

6. security requirements for client secrets file:
   - place it outside repository directory
   - recommended permission: `chmod 600 /path/to/client_secret.jsonl`
   - file extension can be `.json` or `.jsonl`; content must be Google client secrets JSON (`web` object)

## Setup

1. complete onboarding first
2. open `/ui/inputs` and click `Connect Gmail`
3. run manual sync on the Gmail input

## OAuth Token Behavior

1. first Gmail authorization must return `refresh_token`; callback fails if it is missing.
2. repeated authorization may not return `refresh_token`; runtime keeps the existing stored refresh token.
3. if token refresh fails, sync keeps the input active and reports a reconnect-required error.

## Expected Behavior

### First Gmail sync

1. cursor is initialized
2. `changes_created=0`
3. no feed changes

### Incremental Gmail sync

1. new actionable messages create review queue rows
2. queue visible in `/ui/emails/review` and `/v1/emails/queue`
3. feed still unchanged until apply

### Review apply

1. apply mode creates canonical change (`created|due_changed|removed`)
2. applied item moves to `archive`
3. resulting change becomes visible in `/ui/feed`

## Verification APIs

1. `GET /v1/inputs`
2. `POST /v1/inputs/{input_id}/sync`
3. `GET /v1/emails/queue?route=review`
4. `POST /v1/emails/{email_id}/apply`
5. `GET /v1/feed`

## Troubleshooting

1. `redirect_uri_mismatch`
   - verify first `redirect_uris` value in client secrets file matches callback URI exactly.
2. `Gmail OAuth client secrets file is not configured`
   - verify `.env` has `GMAIL_OAUTH_CLIENT_SECRETS_FILE`.
3. `Gmail OAuth client secrets file must be outside the repository`
   - move file to external path (for example `~/.secrets/...`) and update env.
4. `Gmail OAuth client secrets file permissions are too open`
   - run `chmod 600 /path/to/client_secret.jsonl`.
5. Sync error code `fetch_gmail_auth_refresh_failed`
   - reconnect Gmail in `/ui/inputs`; if it persists, revoke app access in Google account and reconnect.
6. Sync error code `fetch_gmail_auth_refresh_token_missing`
   - reconnect Gmail and ensure offline access consent is granted.
