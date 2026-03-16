# File Map

Use this file when you need to locate the main product and runtime surfaces quickly.

## Product truth
- `PURPOSE.md`: product objective, source roles, detection contract
- `ENTITY_FIRST_SEMANTIC_SPEC.md`: canonical semantic and repo cleanup rules

## Current repo truth
- `docs/api_surface_current.md`: active public routes
- `docs/architecture.md`: current module boundaries and runtime model
- `docs/deploy_three_layer_runtime.md`: monolith deploy/runtime defaults

## Core backend modules
- `services/app_api/main.py`: monolith backend entrypoint
- `app/runtime/monolith_workers.py`: background worker tasks inside the monolith
- `app/modules/profile/`: `/profile/me`
- `app/modules/events/`: `/events/manual*`
- `app/modules/review_changes/`: review proposals, decisions, edits, evidence, label learning
- `app/modules/review_links/`: link candidates, links, blocks, summary
- `app/modules/review_taxonomy/`: family/raw-type management under `/review/course-work-item-*`
- `app/modules/input_control_plane/`: sources, OAuth sessions, sync requests, webhooks
- `app/modules/users/serializers.py`: shared response serialization helpers

## Core tests
- `tests/test_review_*.py`: review, edits, summary, label learning, link candidates
- `tests/test_manual_events_api.py`: manual event CRUD
- `tests/test_course_work_item_families_api.py`: family CRUD surface
- `tests/test_course_raw_types_api.py`: raw-type list/relink surface
- `tests/test_users_timezone_api.py`: `/profile/me`
- `tests/test_openapi_contract_snapshots.py`: canonical OpenAPI snapshot
- `tests/test_runtime_entrypoints.py`: monolith runtime entrypoints

## Frontend surfaces
- `frontend/lib/api/users.ts`: profile/manual/family/raw-type API callers
- `frontend/components/manual-workbench-panel.tsx`: manual events
- `frontend/components/family-management-panel.tsx`: family editor
- `frontend/components/add-family-panel.tsx`: family creation
- `frontend/components/settings-panel.tsx`: profile settings
