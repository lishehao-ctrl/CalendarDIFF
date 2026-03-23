# Deployment

## Container topology
Default `docker-compose.yml` contains five services:
- `public-service` for the monolith backend
- `mcp-service` for public CalendarDIFF MCP access
- `frontend`
- `postgres`
- `redis`

## Current AWS host layout
The current production host uses:

- SSH user: `ubuntu`
- app dir: `/home/ubuntu/apps/CalendarDIFF`
- secrets dir: `/home/ubuntu/secrets`

Shared-host rule:

- CalendarDIFF owns `cal.shehao.app`
- RPG owns `rpg.shehao.app`
- CalendarDIFF runs on `127.0.0.1:3000` and `127.0.0.1:8000`
- CalendarDIFF MCP runs on `127.0.0.1:8766`
- RPG currently remains separate on `/srv/rpg-demo` with its own backend port `127.0.0.1:8010`

Reserve a sibling app dir for future non-CalendarDIFF projects when needed:

- `/home/ubuntu/apps/rpg-demo`

## Backend container
`public-service` runs:

```text
/app/scripts/start_service.sh
```

with:
- `SERVICE_NAME=backend`
- `RUN_MIGRATIONS=true`
- `PORT=8000`

## MCP container
`mcp-service` runs:

```text
python -m services.mcp_server.main
```

with:
- `CALENDARDIFF_MCP_MODE=public`
- `CALENDARDIFF_MCP_TRANSPORT=streamable-http`
- `CALENDARDIFF_MCP_HOST=0.0.0.0`
- `CALENDARDIFF_MCP_PORT=8766`

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

Optional Gmail secondary suppressor settings:
- `GMAIL_SECONDARY_FILTER_MODE`
- `GMAIL_SECONDARY_FILTER_PROVIDER`
- `GMAIL_SECONDARY_FILTER_MIN_CONFIDENCE`

Deployment default:
- `GMAIL_SECONDARY_FILTER_MODE=off`

Recommended rollout order:
- `off`
- `shadow`
- `enforce`

Behavior:
- `off`: secondary filter is not part of runtime execution
- `shadow`: secondary filter may run for observation, but must not suppress the main result path
- `enforce`: secondary filter may suppress after the deterministic recall-first prefilter

Operational rule:
- do not make deployment depend on a BERT / secondary model being online
- the main deployable path remains deterministic prefilter -> LLM -> Changes/Families/Manual/Sources

Release rule:
- treat the Gmail secondary filter as an optional pluggable module
- production release must succeed with `off/noop`
- `shadow` and `enforce` are upgrade modes, not release prerequisites
- keep BERT training scripts, evaluation scripts, and threshold tuning outside the critical release checklist

## Release posture
The default deployment assumption is one backend process per environment. Ingest/review/notification/llm work still happen, but as background tasks in that process.

## AWS release script behavior
`scripts/release_aws_main.sh` is the default production sync path.

It now performs the full release sequence:

1. push local `HEAD` to `origin/main`
2. sync the AWS checkout via git bundle
3. rebuild and restart `frontend`, `public-service`, and `mcp-service`
4. verify nginx plus `health` and `login`

Operational rule:

- a release is not complete after git sync alone
- the production host must be running newly rebuilt `frontend`, `public-service`, and `mcp-service` containers
- `postgres` and `redis` stay untouched during the normal release path
- `rpg.shehao.app` remains untouched

Optional override:

```bash
DEPLOY_SERVICES="frontend public-service mcp-service" scripts/release_aws_main.sh
```

Use that variable only when you intentionally need a different compose target set.

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
