# Project Structure

This file is the current top-level map for CalendarDIFF.

## Mainline Runtime

- `app/`
  - backend modules, runtime stages, db models, serializers, and contracts
- `services/app_api/main.py`
  - monolith FastAPI entrypoint
- `services/mcp_server/main.py`
  - external MCP entrypoint for OpenClaw/agent clients
- `frontend/`
  - Next.js App Router frontend
- `scripts/`
  - operator scripts, release helpers, replay harnesses, probes
- `contracts/openapi/`
  - canonical public OpenAPI snapshots

## Product-Oriented Backend Modules

- `app/modules/auth`
- `app/modules/agents`
- `app/modules/onboarding`
- `app/modules/settings`
- `app/modules/sources`
- `app/modules/changes`
- `app/modules/families`
- `app/modules/manual`
- `app/modules/runtime`
- `app/modules/notify`
- `app/modules/llm_gateway`

`app/modules/workbench` is an internal summary/projection layer. It is not a separate public lane.

## Data And Fixtures

- `data/synthetic/year_timeline_demo/`
  - committed year-timeline synthetic mainline
- `data/secondary_filter/`
  - committed secondary-filter evaluation/training datasets
- `tests/fixtures/`
  - committed lightweight fixtures
- `tests/fixtures/private/`
  - local-only private or large fixtures; intentionally not committed
- `tools/datasets/`
  - synthetic dataset generators/exporters

## Optional / Non-Release-Critical Area

- `training/gmail_secondary_filter/`
  - BERT/secondary-filter experimentation
  - not required for deploy
  - production must remain valid with the secondary filter disabled

## Current Documentation Boundaries

- `docs/`
  - stable current repo truth plus a small number of active runbooks
- `specs/`
  - current active handoff bundles only

## No Longer Part Of The Active Structure

These should not be revived as active repo surfaces:

- `services/public_api/`
  - old split-service shell, now removed from the active runtime
- `ui/`
  - empty legacy shell, not a live app surface
- `output/`
  - runtime validation artifacts, not source-of-truth docs or source code

## Operator Rule

When adding new product work:

1. replace or delete the old path instead of keeping a parallel legacy shell
2. keep current truth in stable filenames under `docs/` and keep one-off execution notes out of it
3. delete finished handoff/output docs once they are no longer actively needed
