# Microservice SLO Runbook (Minimal)

## Scope

This runbook defines the minimal SLO checks for the 4-service runtime:

1. `input-service`
2. `ingest-service`
3. `review-service`
4. `notification-service`

All checks are read from `GET /internal/v2/metrics` using service token headers:

- `X-Service-Name: ops`
- `X-Service-Token: ${INTERNAL_SERVICE_TOKEN_OPS}`

## Metrics Contract

Each service returns:

```json
{
  "service_name": "review-service",
  "timestamp": "2026-03-03T00:00:00+00:00",
  "metrics": {}
}
```

## SLO Thresholds

Default thresholds:

1. `ingest.dead_letter_rate_1h <= 0.2`
2. `review.pending_backlog_age_seconds_max <= 900`
3. `notification.notify_fail_rate_24h <= 0.2`
4. `ingest.event_lag_seconds_p95 <= 120`

## Command

```bash
python scripts/ops_slo_check.py \
  --input-base http://127.0.0.1:8001 \
  --ingest-base http://127.0.0.1:8002 \
  --review-base http://127.0.0.1:8000 \
  --notify-base http://127.0.0.1:8004 \
  --ops-token "${INTERNAL_SERVICE_TOKEN_OPS}" \
  --json
```

Exit code:

1. `0`: all checks passed
2. `1`: one or more checks failed, or metrics endpoint unavailable

## Failure Triage

1. `dead_letter_rate_1h` high:
   - Inspect dead-letter jobs in ingest-service.
   - Run replay canary before bulk replay.
2. `pending_backlog_age_seconds_max` high:
   - Check review apply worker health and queue growth.
   - Validate ingest.result.ready consumption.
3. `notify_fail_rate_24h` high:
   - Check SMTP credentials and provider availability.
   - Review digest_send_log failures.
4. `event_lag_seconds_p95` high:
   - Check outbox processing delays and worker saturation.
   - Validate DB latency and lock contention.
