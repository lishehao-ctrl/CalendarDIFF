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
- local/dev uses frontend `127.0.0.1:3000` and backend `127.0.0.1:8200`
- the AWS host runs `frontend` on `127.0.0.1:3000` and `public-service` on `127.0.0.1:8000`
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
- `INGESTION_LLM_PROVIDER_ID`
- `AGENT_LLM_PROVIDER_ID`

Canonical LLM settings:
- `INGESTION_LLM_PROVIDER_ID`
- `AGENT_LLM_PROVIDER_ID`
- `LLM_PROVIDER_<ID>_VENDOR`
- `LLM_PROVIDER_<ID>_PROTOCOL`
- `LLM_PROVIDER_<ID>_MODEL`
- `LLM_PROVIDER_<ID>_BASE_URL`
- `LLM_PROVIDER_<ID>_API_KEY`
- optional `LLM_PROVIDER_<ID>_CHAT_BASE_URL`
- optional `LLM_PROVIDER_<ID>_RESPONSES_BASE_URL`
- optional `LLM_PROVIDER_<ID>_FALLBACK_PROVIDER_IDS`

Optional bounded agent-generation settings:
- `AGENT_GENERATION_MODE=deterministic|llm_assisted`
- `AGENT_LLM_PROVIDER_ID`

Operational rule:
- keep the Claw / approval / MCP contract deterministic
- `AGENT_GENERATION_MODE=llm_assisted` may rewrite proposal summary/reason copy only
- action selection, payload kind, execution boundary, and approval safety checks must remain deterministic

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
After deploy, verify the public host mapping through nginx:

```bash
curl https://cal.shehao.app/health
```

For local stack verification, use:

```bash
./scripts/dev_stack.sh up
./scripts/dev_stack.sh status
```

## Full local validation

Canonical local validation entrypoint:

```bash
python scripts/run_full_repo_validation.py
```

The validation runner executes:

1. preflight
2. backend `pytest -q`
3. frontend `typecheck/lint/build`
4. `scripts/run_agent_claw_strict_eval.py`
5. `scripts/run_year_timeline_replay_smoke.py`

Local infra expectation:

- PostgreSQL on `127.0.0.1:5432`
- Redis on `127.0.0.1:6379`

Validation-specific Redis DB indexes:

- pytest: `/15`
- strict eval: `/14`
- replay: `/13`

Docker daemon is optional for local validation if PostgreSQL and Redis are already reachable.
