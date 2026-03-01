# Scheduler Multi-Instance Acceptance (V2)

## Goal

Validate multi-instance orchestration with shared PostgreSQL:

1. requests are queued once,
2. jobs are processed once-effect,
3. replay APIs work for dead-letter jobs.

## Quick Path

```bash
scripts/smoke_scheduler_multi_instance.sh
```

## Manual Checks

1. Health:
   - `curl http://127.0.0.1:8000/health`
2. Source list:
   - `curl -H "X-API-Key: <APP_API_KEY>" "http://127.0.0.1:8000/v2/input-sources"`
3. Sync request create:
   - `curl -X POST -H "X-API-Key: <APP_API_KEY>" -H "Content-Type: application/json" -d '{"source_id":<id>}' "http://127.0.0.1:8000/v2/sync-requests"`
4. Sync request status:
   - `curl -H "X-API-Key: <APP_API_KEY>" "http://127.0.0.1:8000/v2/sync-requests/<request_id>"`
5. Change feed:
   - `curl -H "X-API-Key: <APP_API_KEY>" "http://127.0.0.1:8000/v2/change-events?source_id=<id>&limit=20"`

## Replay APIs

1. Single job replay:
   - `POST /internal/v2/ingest-jobs/{job_id}/replays`
2. Dead-letter batch replay:
   - `POST /internal/v2/ingest-jobs/dead-letter/replays?limit=100`
