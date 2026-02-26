# Gmail Email Input Runbook (Queue-First)

## Goal

Validate Gmail ingestion under current runtime semantics:

1. Gmail sync writes actionable rows to `email_*` review queue
2. Gmail sync does not create feed changes directly
3. canonical changes appear only after review `apply`

## Prerequisites

1. backend is running (`http://localhost:8000`)
2. PostgreSQL schema is at head
3. `.env` has OAuth values:

```env
APP_BASE_URL=http://localhost:8000
GMAIL_OAUTH_CLIENT_ID=...
GMAIL_OAUTH_CLIENT_SECRET=...
GMAIL_OAUTH_REDIRECT_URI=http://localhost:8000/v1/oauth/gmail/callback
GMAIL_OAUTH_SCOPE=https://www.googleapis.com/auth/gmail.readonly
```

## Setup

1. complete onboarding first
2. from processing page, connect Gmail input via OAuth
3. run manual sync on the Gmail input

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
