# CalendarDIFF

CalendarDIFF is a single-host, monolith-style app for keeping grade-relevant deadline changes in one workflow.

It does not try to classify all course communication.
Its job is to:

1. ingest Canvas ICS and Gmail signals
2. build a canonical event baseline
3. surface safe review proposals
4. keep ongoing replay changes in one daily review lane

## Product shape

Current user-facing product lanes:

- `Overview`
- `Sources`
- `Changes`
- `Families`
- `Manual`
- `Settings`

Important workflow distinction:

- `Initial Review` is a temporary baseline-review workspace after first import
- `Changes` is the normal daily replay-review workspace after baseline is established

The intended user flow is:

1. register or sign in
2. finish onboarding
3. connect required Canvas ICS
4. optionally connect Gmail
5. choose the initial monitoring window
6. complete `Initial Review`
7. use `Changes` for day-to-day review

## Runtime model

CalendarDIFF now runs as one backend process by default.

- Backend: `services.app_api.main:app`
- Frontend: Next.js app in `frontend/`
- Infra: PostgreSQL + Redis

Default local ports:

- Backend: `8200`
- Frontend: `3000`
- PostgreSQL: `5432`
- Redis: `6379`

Legacy split-service entrypoints are no longer the default repo path.

## Local setup

1. Copy `.env.example` to `.env` and fill in required values.
2. Install backend dependencies.
3. Install frontend dependencies:

```bash
cd frontend && npm install
```

4. Start the default stack:

```bash
./scripts/dev_stack.sh up
```

Useful commands:

```bash
./scripts/dev_stack.sh status
./scripts/dev_stack.sh logs backend
./scripts/dev_stack.sh logs frontend
./scripts/dev_stack.sh down
./scripts/dev_stack.sh down --infra
./scripts/dev_stack.sh reset
```

Health check:

```bash
curl http://127.0.0.1:8200/health
```

Full local validation:

```bash
python scripts/run_full_repo_validation.py
```

Validation rule:

- local Redis is expected on `127.0.0.1:6379`
- the validation runner reuses isolated Redis DB indexes per phase
- Docker Desktop is optional if PostgreSQL on `5432` and Redis on `6379` are already reachable

## Direct backend run

```bash
SERVICE_NAME=backend RUN_MIGRATIONS=true PORT=8200 ./scripts/start_service.sh
```

`SERVICE_NAME` only accepts `backend`.

## Public HTTP surface

Current public route groups:

- `/auth/*`
- `/agent/*`
- `/settings/profile`
- `/settings/mcp-*`
- `/settings/channel-*`
- `/sources/*`
- `/sync-requests/*`
- `/onboarding/*`
- `/changes*`
- `/families*`
- `/manual/events*`
- `/health`

Current onboarding endpoints include:

- `POST /onboarding/registrations`
- `GET /onboarding/status`
- `POST /onboarding/canvas-ics`
- `POST /onboarding/gmail/oauth-sessions`
- `POST /onboarding/gmail-skip`
- `POST /onboarding/monitoring-window`

## Runtime truth

`sync_requests` is the single user-visible runtime state machine.

Fine-grained runtime truth lives on:

- `stage`
- `substage`
- `stage_updated_at`
- `progress_json`

User-facing source posture and workbench posture are derived from explicit runtime state rather than old incidental payload inference.

## Product contracts already in use

Current backend contracts exposed to the frontend include:

- `GET /changes/summary`
  - `workspace_posture`
- `GET /changes`
  - `decision_support` on each change item
- `GET /sources`
  - `source_product_phase`
  - `source_recovery`
- `GET /sources/{source_id}/observability`
  - `bootstrap_summary`
  - `source_product_phase`
  - `source_recovery`

## Optional integrations

Supported integrations remain:

- Gmail OAuth
- Canvas ICS
- SMTP delivery
- fixture builders and probe scripts

## Agent generation gateway

The agent proposal/approval/MCP contract remains deterministic by default.

An optional internal proposal-copy gateway can ride on top of `llm_gateway`:

- `AGENT_GENERATION_MODE=deterministic` keeps the current stable behavior
- `AGENT_GENERATION_MODE=llm_assisted` lets the backend rewrite proposal `summary` and `reason` via `profile_family="agent"`

This gateway must not change:

- suggested action
- payload kind
- approval-ticket eligibility
- MCP tool surface
- confirm-time drift protection

## LLM gateway

`llm_gateway` is now the shared model-invocation kernel for:

- named provider registry
- vendor/protocol adapters
- structured JSON extraction
- streaming normalization
- same-vendor fallback
- per-call trace and usage persistence

Current supported vendor families:

- `openai`
- `gemini`
- `dashscope_openai`

Current supported protocols:

- `responses`
- `chat_completions`
- `gemini_generate_content`

Configuration rule:

- prefer named providers via `INGESTION_LLM_PROVIDER_ID` and `AGENT_LLM_PROVIDER_ID`
- runtime queue orchestration still lives in `runtime.llm`; `llm_gateway` does not own parse-task claim/ack/retry

## Internal agent gateway

Agent reads, proposal creation, approval tickets, and recent activity now share one backend application boundary:

- internal entry: `app/modules/agents/gateway.py`
- web surface: `app/modules/agents/router.py`
- MCP surface: `services/mcp_server/main.py`

Design rule:

- router and MCP should reuse `agents.gateway`
- `agents.gateway` may reuse context/proposal/approval services
- future frontend copilot entrypoints should bind to the same gateway contract instead of stitching lower-level services directly

Operational rule:

- BERT / Gmail secondary filtering is not part of the required deployable path
- production should continue to work with:
  - `GMAIL_SECONDARY_FILTER_MODE=off`
  - `GMAIL_SECONDARY_FILTER_PROVIDER=noop`

Recommended architecture stance:

- treat the Gmail secondary filter as a pluggable module, not a required runtime dependency
- keep training/evaluation artifacts separate from the production-critical path
- allow runtime switching by config only:
  - `off`
  - `shadow`
  - `enforce`
- never make onboarding, source intake, review, or deploy health depend on the BERT module being available

## OpenAPI

Canonical snapshot:

```text
contracts/openapi/public-service.json
```

Refresh it with:

```bash
python scripts/update_openapi_snapshots.py
```

## Deployment

Current production host:

- domain: `cal.shehao.app`
- host: `ubuntu@54.152.242.119`
- app dir: `/home/ubuntu/apps/CalendarDIFF`

Shared-host rule:

- CalendarDIFF owns only `cal.shehao.app`
- RPG stays separate on `rpg.shehao.app`

Read these before host changes:

- `skills/aws-release/SKILL.md`
- `docs/deployment.md`
- `docs/nginx_live_routing_architecture.md`

Normal AWS sync path:

```bash
scripts/release_aws_main.sh
```

That script is a full release step, not just a git sync:

- syncs the AWS checkout to local `HEAD`
- rebuilds and restarts `frontend`, `public-service`, and `mcp-service`
- verifies `health` and `login`

## Docs map

Current repo truth is split into a small set of stable docs:

- `docs/README.md`
- `docs/project_structure.md`
- `docs/architecture.md`
- `docs/api_surface_current.md`
- `docs/deployment.md`
- `docs/event_contracts.md`
- `docs/frontend_backend_contracts.md`

Use `specs/` only for dated implementation handoffs, not as the current source of truth.

## Verification baseline

Backend regression:

```bash
pytest tests/test_review_items_summary_api.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_source_sync_progress_api.py \
  tests/test_source_read_bridge.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_review_changes_unified.py \
  tests/test_review_changes_batch_api.py \
  tests/test_review_edits_api.py
```

Frontend regression:

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

Full repo validation wraps those checks plus:

- `scripts/run_agent_claw_strict_eval.py`
- `scripts/run_year_timeline_replay_smoke.py`
