# Input Microservices Cutover Notes (Historical)

This document is retained for historical context only.

Status as of current runtime:

1. The previous split topology (`input-control-plane-api`, `core-api`, gateway, separate orchestrator/connector/apply workers) is retired.
2. Active deployment is the three-layer model documented in:
   - `docs/architecture.md`
   - `docs/deploy_three_layer_runtime.md`

Current runtime units:

1. `api` (`app.main:app`)
2. `ingestion-worker` (`services.ingestion_runtime.worker`)
3. `notification-worker` (`services.notification.worker`)
4. `postgres`

If you are debugging deployment startup errors, do not use legacy entrypoints referenced in old notes or scripts.
