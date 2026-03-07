# Ops Retention / Replay / Smoke Runbook

## Scope

This runbook covers only three operational loops for the mainline runtime:

1. Data retention for `source_event_observations` and `changes`
2. Dead-letter triage and replay SOP for ingestion jobs
3. Post-smoke cleanup to prevent historical pending-review contamination

Out of scope:

1. Public API behavior changes
2. DB schema changes/migrations
3. Canonical event rewrite outside normal review decision flow

## Retention Policy

### Policy Matrix

| Table | Keep Rule | Delete Rule | Notes |
|---|---|---|---|
| `source_event_observations` | `is_active=true` kept | `is_active=false` and `observed_at < now-30d` | Keep active observations for merge stability |
| `changes` | `review_status=pending` kept | none in minimal retention | Pending is review work-in-progress |
| `changes` | `review_status=approved` kept | none in minimal retention | Approved is audit history |
| `changes` | `review_status=rejected` kept short-term | `coalesce(reviewed_at, detected_at) < now-90d` | Rejected older history can be trimmed |

### Time Basis

1. All cutoffs use UTC
2. Script uses `datetime.now(timezone.utc)` internally

### Retention Executor

Use:

```bash
python scripts/ops_retention_minimal.py --dry-run --json
python scripts/ops_retention_minimal.py --apply --json
```

## Dead-letter Daily SOP

### Daily Triage Steps

1. Count total dead-letter jobs.
2. Group by `source_id` and `request_id`.
3. Classify root cause category before replay.

Recommended classification:

1. `auth/rate/config` -> fix configuration first, do not blind replay
2. `timeout/upstream` -> canary replay allowed
3. `parse/schema` -> verify parser/LLM runtime behavior first

### Replay Sequence

1. Single-job canary replay:

```bash
curl -X POST "http://127.0.0.1:8202/internal/ingest/jobs/<job_id>/replays" \
  -H "X-Service-Name: ops" \
  -H "X-Service-Token: ${INTERNAL_SERVICE_TOKEN_OPS}"
```

2. If canary succeeds, batch replay:

```bash
curl -X POST "http://127.0.0.1:8202/internal/ingest/jobs/dead-letter/replays?limit=50" \
  -H "X-Service-Name: ops" \
  -H "X-Service-Token: ${INTERNAL_SERVICE_TOKEN_OPS}"
```

### Stop-Loss Rule

1. If replayed jobs re-enter dead-letter at a ratio above 20%, stop batch replay.
2. Escalate to manual incident handling and fix root cause before next replay.

### Audit Record

For each replay action, record:

1. operator
2. job_id/request_id
3. reason
4. result
5. next action

## Smoke Cleanup SOP

### Goal

After real-source smoke runs, ensure no leftover pending review items for smoke sources.

### Required Flow

1. Keep `scripts/smoke_real_sources_three_rounds.py` default `--cleanup-sources` behavior.
2. Run pending cleanup by source IDs:

```bash
python scripts/ops_cleanup_smoke_state.py \
  --source-id <calendar_source_id> \
  --source-id <gmail_source_id> \
  --apply \
  --json
```

3. Verify pending is cleared for these sources:

```bash
curl -s "http://127.0.0.1:8200/review/changes?review_status=pending&limit=200" \
  -H "X-API-Key: ${APP_API_KEY}"
```

### Source IDs from Smoke Report

When smoke report is at `data/synthetic/ddlchange_160/qa/real_source_smoke_report.json`:

```bash
jq '.source' data/synthetic/ddlchange_160/qa/real_source_smoke_report.json
```

## Commands

### SQL Helpers for Dead-letter Inspection

```sql
-- total dead-letter
SELECT count(*)
FROM ingest_jobs
WHERE status = 'DEAD_LETTER';

-- dead-letter by source
SELECT source_id, count(*) AS cnt
FROM ingest_jobs
WHERE status = 'DEAD_LETTER'
GROUP BY source_id
ORDER BY cnt DESC;

-- latest dead-letter details
SELECT id, request_id, source_id, dead_lettered_at
FROM ingest_jobs
WHERE status = 'DEAD_LETTER'
ORDER BY dead_lettered_at DESC NULLS LAST, id DESC
LIMIT 100;
```

### Script Usage

```bash
# pending cleanup dry-run
python scripts/ops_cleanup_smoke_state.py --source-id 101 --source-id 102 --dry-run --json

# pending cleanup apply
python scripts/ops_cleanup_smoke_state.py --source-id 101 --source-id 102 --apply --json

# retention dry-run
python scripts/ops_retention_minimal.py --dry-run --json

# retention apply
python scripts/ops_retention_minimal.py --apply --json
```

### Cron Example

```cron
15 3 * * * cd /Users/lishehao/Desktop/Project/CalendarDIFF && /usr/bin/python scripts/ops_retention_minimal.py --apply --json >> /var/log/calendardiff-retention.log 2>&1
```

## Failure Playbook

### `ops_cleanup_smoke_state.py` failures

1. `--source-id must be positive` -> fix parameters
2. DB/connectivity errors -> verify `DATABASE_URL`, DB health, schema head
3. `truncated=true` in output -> rerun with larger `--limit` if intentional

### `ops_retention_minimal.py` failures

1. guardrail triggered (`candidate deletes exceed max_delete_per_run`) -> investigate volume and rerun with adjusted threshold only after validation
2. DB errors during delete -> retry in dry-run first, then apply

### Replay failures

1. single replay 409 -> job is not in dead-letter; verify current status first
2. repeated dead-letter after replay -> stop and root-cause before next batch

## Ownership & Cadence

1. Daily:
2. dead-letter triage + replay decision
3. smoke cleanup when smoke run executed
4. Weekly:
5. retention dry-run review
6. retention apply in off-peak window
7. Monthly:
8. trend review for dead-letter volume and retention deletion volume

## Safety Guardrails

1. Scripts default to dry-run.
2. Apply requires explicit `--apply`.
3. Never hard-delete pending review items in production flow.
4. Replay order is always canary first, batch second.
5. Batch replay stop-loss >20% re-dead-letter ratio.
6. Retention apply is blocked by `--max-delete-per-run` guardrail by default.
