# Legacy Cleanup Matrix (Core Simplified)

This file tracks what has been removed from runtime surface after the core simplification pass.

## Removed

1. Term runtime data model:
   - `user_terms`
   - `input_term_baselines`
   - `inputs.user_term_id`
   - `changes.user_term_id`
2. Feed term contract:
   - removed query params `term_scope`, `term_id`
   - removed response fields `term_id`, `term_code`, `term_label`, `term_scope`
3. Legacy review-candidate domain:
   - dropped table `email_rule_candidates`
   - removed API `/v1/review_candidates*`
4. Legacy user initialization/term endpoints:
   - removed `POST /v1/user`
   - removed `/v1/user/terms*`
5. Busy compatibility bridge:
   - removed `legacy_code=source_busy`
   - manual sync contention keeps only `detail.code=input_busy`
6. Legacy source naming in sync runtime:
   - `list_due_sources -> list_due_inputs`
   - `sync_source -> sync_input`
   - `_sync_email_source -> _sync_email_input`
   - `_handle_source_error -> _handle_input_error`
7. Legacy evidence endpoints:
   - removed `GET /v1/inputs/{input_id}/changes/{change_id}/evidence/{side}/preview`
   - removed `GET /v1/inputs/{input_id}/changes/{change_id}/evidence/{side}/download`
   - kept `GET /v1/changes/{change_id}/evidence/{side}/preview` as the only preview path
8. Scheduler lock config naming:
   - removed `source_lock_namespace`
   - replaced with `input_lock_namespace`

## Guardrails

1. Runtime code uses `/v1/emails/*` as the only email review API.
2. Runtime code has no `review_candidates`, `legacy_code`, `source_busy`, or `source_lock_namespace` symbols.
3. Initialization path is onboarding-first (`POST /v1/onboarding/register`).
