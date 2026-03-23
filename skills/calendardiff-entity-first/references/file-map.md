# File Map

Use this file when you need to locate the main product and runtime surfaces quickly.

## Product truth
- `PURPOSE.md`: product objective, source roles, detection contract
- `ENTITY_FIRST_SEMANTIC_SPEC.md`: canonical semantic and repo cleanup rules

## Current repo truth
- `docs/api_surface_current.md`: active public routes
- `docs/architecture.md`: current module boundaries and runtime model
- `docs/deployment.md`: monolith deploy/runtime defaults
- `docs/project_structure.md`: active repo layout and directory responsibilities

## Core backend modules
- `services/app_api/main.py`: monolith backend entrypoint
- `app/modules/runtime/monolith_workers.py`: background worker tasks inside the monolith
- `app/modules/runtime/connectors/clients/`: Gmail/ICS provider client adapters
- `app/modules/settings/`: `/settings/profile`
- `app/modules/manual/`: `/manual/events*`
- `app/modules/changes/`: review proposals, decisions, edits, evidence, label learning
- `app/modules/families/`: family/raw-type management under `/families*`
- `app/modules/sources/`: sources, OAuth sessions, sync requests, webhooks
- `app/modules/settings/serializers.py`: profile/settings response serialization helpers

## Core tests
 - `tests/test_review_*.py`: review, edits, summary, label learning
- `tests/test_manual_events_api.py`: manual event CRUD
- `tests/test_course_work_item_families_api.py`: family CRUD surface
- `tests/test_course_raw_types_api.py`: raw-type list/relink surface
- `tests/test_users_timezone_api.py`: `/settings/profile`
- `tests/test_openapi_contract_snapshots.py`: canonical OpenAPI snapshot
- `tests/test_runtime_entrypoints.py`: monolith runtime entrypoints

## Frontend surfaces
- `frontend/lib/api/changes.ts`: changes/edit API callers
- `frontend/lib/api/families.ts`: family/raw-type API callers
- `frontend/lib/api/manual.ts`: manual API callers
- `frontend/lib/api/settings.ts`: settings API callers
- `frontend/components/manual-workbench-panel.tsx`: manual events
- `frontend/components/family-management-panel.tsx`: family editor
- `frontend/components/settings-panel.tsx`: profile settings
