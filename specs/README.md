# Specs

This directory keeps implementation handoffs, not durable repo truth.

## Active spec surface

Only currently active handoff bundles should stay directly under:

- `specs/backend/`
- `specs/frontend/`

At the moment, those are the current `2026-03-22-*` bundles still being used for front/backend coordination.

## Historical spec surface

Older or completed bundles belong under:

- `specs/archive/`

That includes:

- finished rollout plans
- replay/acceptance execution bundles
- old UI foundation or exploratory handoffs
- optional BERT/secondary-filter experiment specs

## Rule

Do not use `specs/` as the current source of truth for repo architecture or API surface.

Current truth lives in:

- `README.md`
- `docs/README.md`
- `docs/project_structure.md`
- `docs/architecture.md`
- `docs/api_surface_current.md`
