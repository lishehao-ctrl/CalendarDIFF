# Deployment Notes

This document now describes the default monolith deployment, despite the historical filename.

## Container topology
Default `docker-compose.yml` contains four services only:
- `public-service` for the monolith backend
- `frontend`
- `postgres`
- `redis`

## Backend container
`public-service` runs:

```text
/app/scripts/start_service.sh
```

with:
- `SERVICE_NAME=backend`
- `RUN_MIGRATIONS=true`
- `PORT=8000`

## Required environment
Minimum runtime settings:
- `APP_API_KEY`
- `APP_SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `INGESTION_LLM_MODEL`
- `INGESTION_LLM_API_KEY`

LLM endpoint settings:
- `INGESTION_LLM_API_MODE`
- `INGESTION_LLM_CHAT_BASE_URL` for `chat_completions`
- `INGESTION_LLM_RESPONSES_BASE_URL` for `responses`
- `INGESTION_LLM_BASE_URL` remains a legacy fallback when you intentionally use one shared root for both modes

Optional OAuth/SMTP settings still apply when those integrations are enabled.

## Release posture
The default deployment assumption is one backend process per environment. Ingest/review/notification/llm work still happen, but as background tasks in that process.

## OpenAPI
Only one default snapshot is maintained:

```text
contracts/openapi/public-service.json
```

Refresh it with:

```bash
python scripts/update_openapi_snapshots.py
```

## Verification
After deploy, verify:

```bash
curl http://127.0.0.1:8200/health
```

and, for local stack verification:

```bash
./scripts/dev_stack.sh up
./scripts/dev_stack.sh status
```
