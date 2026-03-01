# Manual Email Test (V2 APIs)

## Preconditions

1. Backend is running at `http://localhost:8000`.
2. `APP_API_KEY` is available for `X-API-Key`.
3. PostgreSQL schema is ready.
4. SMTP test sink (for example MailHog) is running.

## 1) Register User

```bash
curl -sS -X POST "http://localhost:8000/v2/onboarding/registrations" \
  -H "X-API-Key: ${APP_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"notify_email":"notify@example.com"}' | python3 -m json.tool
```

## 2) Create Gmail Source

```bash
SOURCE_JSON=$(
  curl -sS -X POST "http://localhost:8000/v2/input-sources" \
    -H "X-API-Key: ${APP_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{
      "source_kind":"email",
      "provider":"gmail",
      "display_name":"Manual Gmail Source",
      "poll_interval_seconds":900,
      "config":{},
      "secrets":{}
    }'
)
SOURCE_ID=$(echo "${SOURCE_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["source_id"])')
echo "SOURCE_ID=${SOURCE_ID}"
```

## 3) Start OAuth Session

```bash
curl -sS -X POST "http://localhost:8000/v2/oauth-sessions" \
  -H "X-API-Key: ${APP_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"source_id\": ${SOURCE_ID}, \"provider\": \"gmail\"}" | python3 -m json.tool
```

Open `authorization_url` in browser and complete consent.

## 4) Trigger Manual Sync

```bash
REQUEST_JSON=$(
  curl -sS -X POST "http://localhost:8000/v2/sync-requests" \
    -H "X-API-Key: ${APP_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"source_id\": ${SOURCE_ID}}"
)
REQUEST_ID=$(echo "${REQUEST_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["request_id"])')
echo "REQUEST_ID=${REQUEST_ID}"
```

Poll status:

```bash
curl -sS "http://localhost:8000/v2/sync-requests/${REQUEST_ID}" \
  -H "X-API-Key: ${APP_API_KEY}" | python3 -m json.tool
```

## 5) Verify Review Queue + Feed

```bash
curl -sS "http://localhost:8000/v2/review-items/emails?route=review" -H "X-API-Key: ${APP_API_KEY}" | python3 -m json.tool
curl -sS "http://localhost:8000/v2/change-events?limit=50" -H "X-API-Key: ${APP_API_KEY}" | python3 -m json.tool
```
