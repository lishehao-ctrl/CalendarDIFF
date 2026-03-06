# Semester Demo Test Report (English)

## Scope
- Goal: validate the end-to-end integration of `ICS fake source + Gmail-compatible fake inbox + input/ingest/llm/review/notify`.
- Real component: LLM calls must use the configured live `INGESTION_LLM_*` endpoint.
- Simulated components: Gmail inbox uses the fake provider; notifications use the `jsonl` sink plus `POST /internal/notifications/flush`.
- Excluded: OAuth/Gmail callback/redirect/client secrets and real SMTP delivery.

## Environment Snapshot
- Database: `postgres` was started and migrated with `alembic upgrade head`.
- Redis: an additional host-visible `redis:7-alpine` container was started on `127.0.0.1:6379` so local services could reach Redis.
- Services: `input(8001)`, `review(8000)`, `ingest(8002)`, `notification(8004)`, and `llm(8005)` all returned `/health = 200`.
- Runtime mode:
  - `ENABLE_NOTIFICATIONS=true`
  - `NOTIFY_SINK_MODE=jsonl`
  - `NOTIFICATION_SERVICE_ENABLE_WORKER=false`
  - `INGEST_SERVICE_ENABLE_WORKER=true`
  - `REVIEW_SERVICE_ENABLE_APPLY_WORKER=true`
  - `LLM_SERVICE_ENABLE_WORKER=true`
  - `GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me`

## Commands Executed
- Offline guards:
  - `pytest -q tests/test_notify_jsonl_sink.py tests/test_notify_flush_api.py tests/test_fake_source_provider_semester_contract.py tests/test_semester_demo_scenarios.py tests/test_semester_demo_report_schema.py tests/test_internal_service_auth.py tests/test_digest_scheduler_idempotency.py tests/test_email_notifications.py tests/test_fake_source_provider_contract.py tests/test_real_source_smoke_report_schema.py`
- Main integration run:
  - `python scripts/smoke_semester_demo.py --input-api-base http://127.0.0.1:8001 --review-api-base http://127.0.0.1:8000 --ingest-api-base http://127.0.0.1:8002 --notify-api-base http://127.0.0.1:8004 --llm-api-base http://127.0.0.1:8005 --api-key "$APP_API_KEY" --ops-token "$INTERNAL_SERVICE_TOKEN_OPS" --notification-jsonl data/smoke/notify_sink.jsonl --report data/synthetic/semester_demo/qa/semester_demo_report.json`
- Online wrapper:
  - `RUN_SEMESTER_DEMO_SMOKE=true pytest -q tests/test_semester_demo_online.py`
- Quality gates:
  - `mypy .`
  - `flake8 .`
  - `python -m build`

## Result Summary
- Offline guard suite: passed, `20 passed`.
- Quality gates: passed, `mypy . / flake8 . / python -m build` all succeeded.
- Main integration run: failed.
- Online pytest wrapper: failed.
- Final verdict: `FAIL`.

## Acceptance Checks
- Service health: passed.
- Fake Gmail inbox contract: passed offline, and ingest logs confirmed calls to the fake provider at runtime.
- Suffix assertions: not reached at runtime.
- Notification flush: not reached in the business flow; no JSONL rows were produced.
- Real LLM invocation: not successfully reached.

## Key Evidence
- Main report: `data/synthetic/semester_demo/qa/semester_demo_report.json`
- Final blocking error from the main run:
  - `fatal_errors = ["sync request timed out request_id=3ec2b84f22804036b519e57a5f01c3aa"]`
  - Failure point: `semester=1 / batch=1 / source=ics`
- Database evidence:
  - `sync_requests` still contained 4 pending/running rows.
  - Latest `ingest_jobs` were stuck at `status=CLAIMED` with `workflow_stage=LLM_ENQUEUE_PENDING`.
- Metrics evidence:
  - input metrics: `sync_requests_pending=4`
  - ingest metrics: `ingest_jobs_pending=4`, `ingest_jobs_dead_letter=2`
  - llm metrics: `queue_depth_stream=0`, `queue_depth_retry=0`, `llm_calls_total_1m=0`
  - notify status: `notification_pending=0`, `notification_sent=0`, `digest_sent=0`
- Log evidence:
  - ingest logs confirmed fake-provider access: `ingest_fake_gmail_calls=23`
  - however, the pipeline never progressed into LLM execution or notification delivery
  - `notify_sink.jsonl` row count: `0`

## Edge Case Analysis
- Covered at the offline/contract level:
  - missing suffix
  - suffix mismatch
  - exact suffix match
  - fake inbox preservation of `thread_id / from_header / label_ids / internalDate`
  - empty flush state and JSONL context propagation
- Not covered at runtime because the pipeline was blocked:
  - runtime suffix assertion hits
  - mixed review decisions followed by notification flush
  - notification JSONL growth
  - LLM latency / formatting retries / output stability
- Conclusion: the current issue is not insufficient scale; the pipeline is blocked before completing batch 1. Increasing scale is not justified yet.

## LLM Behavior Analysis
- This run required real LLM usage, but the observed result was:
  - `llm-service /internal/metrics` reported `llm_calls_total_1m = 0`
  - meaning no successful LLM call was made during the integration run
- Therefore the following could not be evaluated in this round:
  - latency distribution
  - format retry behavior
  - output stability
  - rate limit / timeout operational impact

## Issues and Root Cause
### Blocking Issue 1: tasks never reached the LLM queue
- Symptom: `ingest_jobs` remained at `CLAIMED + LLM_ENQUEUE_PENDING`.
- At the same time, `llm-service` metrics showed zero queue depth and zero LLM calls.
- Interpretation: connector fetch succeeded for fake ICS/Gmail content, but parse tasks were never successfully pushed into the LLM stream queue.
- Impact: `sync_request` never reached `SUCCEEDED+applied`, so the flow stopped before review and notification.

### Blocking Issue 2: online pytest wrapper uses a different API key than the live services
- `tests/test_semester_demo_online.py` failed with: `GET /onboarding/status failed status=401 body={"detail":"Invalid API key"}`.
- Interpretation: the `APP_API_KEY` visible to the pytest subprocess did not match the key used by the already running live `input-service`.
- Impact: the wrapper is not yet a reliable live-system entry point.

## Risks and Recommendations
- Fix the transition from `LLM_ENQUEUE_PENDING` into the parse queue first, then rerun at the same baseline size.
- Do not scale up yet. First confirm on the current `3x10x10` baseline that:
  - `llm_calls_total_1m > 0`
  - all `suffix_assertions` pass
  - `notification_sink.rows_delta > 0`
- Harmonize the source of `APP_API_KEY` so the live services and `tests/test_semester_demo_online.py` use the same value.
- In the next round, additionally record:
  - per-batch LLM call count
  - per-batch flush `sent_count`
  - per-semester edge-case hit counts

## Final Verdict
- Verdict: `FAIL`
- Reason: the fake inbox fetch path worked, but the pipeline was blocked at `LLM_ENQUEUE_PENDING -> LLM queue`, so real LLM, review, and notification could not be validated end-to-end.
