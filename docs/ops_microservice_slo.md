# Microservice SLO Runbook (Minimal)

## Scope

This runbook defines the minimal SLO checks for the 5-service runtime:

1. `input-service`
2. `ingest-service`
3. `llm-service`
4. `review-service`
5. `notification-service`

All checks are read from `GET /internal/metrics` using service token headers:

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

Ingest delta observability fields (non-blocking but must be present):

1. `ics_delta_components_total_1m`
2. `ics_delta_changed_components_1m`
3. `ics_delta_removed_components_1m`
4. `ics_delta_parse_failures_1h`

`llm-service` metrics are required contract fields for closure gating:

1. `queue_depth_stream`
2. `queue_depth_retry`
3. `llm_calls_total_1m`
4. `llm_calls_rate_limited_1m`
5. `llm_call_latency_ms_p95_5m`
6. `limiter_reject_rate_1m`

`review-service` linker governance metrics (non-blocking, required fields):

1. `linker_auto_link_total`
2. `linker_candidate_total`
3. `linker_unlinked_total`
4. `linker_block_hit_total`
5. `linker_candidate_decision_approve_total`
6. `linker_candidate_decision_reject_total`
7. `linker_false_link_corrections_total`

## Command

```bash
python scripts/ops_slo_check.py \
  --input-internal-base http://127.0.0.1:8201 \
  --ingest-internal-base http://127.0.0.1:8202 \
  --llm-internal-base http://127.0.0.1:8205 \
  --review-internal-base http://127.0.0.1:8203 \
  --notify-internal-base http://127.0.0.1:8204 \
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
5. `ics_delta_parse_failures_1h` non-zero spike:
   - Validate ICS provider payload validity and recent upstream format changes.
   - Inspect ingest logs for `calendar_delta_parse_failed`.
