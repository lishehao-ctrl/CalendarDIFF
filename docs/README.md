# Docs

This directory contains two kinds of files:

- stable repo truth
- active runbooks for operation, validation, and MCP usage

It is not a general archive.

## Stable Repo Truth

- `docs/project_structure.md`
  - active top-level directories, dataset boundaries, and retired repo surfaces
- `docs/architecture.md`
  - current monolith runtime, module boundaries, and service ownership
- `docs/api_surface_current.md`
  - current public/backend and MCP-adjacent HTTP surface
- `docs/api_layering_contract.md`
  - surface ownership rules for web, agent, and MCP callers
- `docs/deployment.md`
  - current local/AWS runtime defaults and release posture
- `docs/event_contracts.md`
  - canonical persisted handoff objects and semantic flow
- `docs/frontend_backend_contracts.md`
  - frontend-consumable backend contract fields and copy strategy
- `docs/api_consistency_test_plan.md`
  - strict cross-endpoint consistency expectations

## Runbooks And External Surfaces

- `docs/mcp_server.md`
  - CalendarDIFF MCP server entrypoint, tool surface, and token/audit behavior
- `docs/openclaw_integration.md`
  - OpenClaw/QClaw integration notes for the current MCP contract
- `docs/claw_smoke_runbook.md`
  - shortest manual validation path for the Claw-first workflow
- `docs/agent_claw_closeout.md`
  - frozen Claw-facing contract and closeout boundary
- `docs/nginx_live_routing_architecture.md`
  - live shared-host nginx ownership and routing rules

## Rule

If a document is a finished handoff, dated rollout note, or historical memo instead of current truth or an active runbook, delete it instead of archiving it in `docs/`.
