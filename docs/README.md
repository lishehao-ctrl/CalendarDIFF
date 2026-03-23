# Docs

This directory now separates stable repo truth from dated execution records.

## Read These First

- `docs/project_structure.md`
  - active top-level directories, dataset boundaries, and what is no longer part of the mainline
- `docs/architecture.md`
  - monolith runtime, module boundaries, sync runtime model
- `docs/api_surface_current.md`
  - current public backend route families
- `docs/deployment.md`
  - current deploy/runtime defaults for local and AWS
- `docs/event_contracts.md`
  - canonical persisted handoff objects and semantic flow
- `docs/frontend_backend_contracts.md`
  - current frontend-consumable backend contract fields and code-based copy strategy
- `docs/api_consistency_test_plan.md`
  - strict cross-endpoint consistency matrix for truth, posture, preview, and write-after-read checks
- `docs/agent_rollout_todo.md`
  - phased agent/channel rollout checklist
- `docs/agent_api_layering_spec.md`
  - Phase 0 API layering boundary for agent/social/MCP integration
- `docs/mcp_server.md`
  - CalendarDIFF MCP server entrypoint, tool/resource surface, and OpenClaw integration shape
- `docs/openclaw_integration.md`
  - practical OpenClaw + CalendarDIFF MCP integration notes and workspace skill usage
- `docs/nginx_live_routing_architecture.md`
  - live shared-host nginx ownership and routing rules

## Historical Material

- `docs/archive/`
  - dated memos, rollout checklists, release notes, audits, and superseded guidance
- `specs/`
  - active implementation handoffs only
- `specs/archive/`
  - completed or historical implementation handoffs and execution artifacts

## Rule

If a document is date-stamped and describes one execution pass, rollout, or audit, it belongs in `docs/archive/` or `specs/`, not in the root of `docs/`.
