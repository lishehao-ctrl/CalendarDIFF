# Legacy Cleanup Matrix

## Removed

1. `/v1/review_candidates*`
2. `email_rule_candidates` table
3. `/v1/user/terms*`
4. `/v1/status`
5. `/v1/notification_prefs*`
6. `/v1/notifications/send_digest_now`
7. `/v1/inputs/{input_id}/runs`
8. `/v1/inputs/{input_id}/deadlines`
9. `/v1/inputs/{input_id}/overrides`
10. `/v1/inputs/ics`
11. evidence download route
12. input-scoped preview route
13. `/ui/inputs`
14. `/ui/runs`
15. `/ui/dev`

## Kept (Core)

1. onboarding flow (`/v1/onboarding/*`)
2. input list + manual sync (`/v1/inputs`, `/v1/inputs/{id}/sync`)
3. feed + viewed update
4. change-scoped evidence preview
5. email review queue + apply
6. health probe (`/health`)

## Runtime Guardrails

1. `ready` user must have exactly one ICS input row
2. Gmail sync is queue-first, no direct feed change creation
3. only `created|removed|due_changed` are emitted as reminder changes
4. digest-only notification strategy with fixed slots
