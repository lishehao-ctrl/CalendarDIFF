# Semester Demo Test Report (English)

## Scope
- Goal: validate the end-to-end integration of `ICS fake source + Gmail-compatible fake inbox + input/ingest/llm/review/notify`.
- Real component: LLM calls use the configured live `INGESTION_LLM_*` endpoint.
- Simulated components: Gmail inbox uses the fake provider; notifications use the `jsonl` sink and `POST /internal/notifications/flush`.
- Excluded: OAuth/Gmail callback/redirect/client secrets and real SMTP delivery.

## Environment Snapshot
- Database: isolated test database `deadline_diff_test`, recreated and migrated to head.
- Redis: host-visible Redis at `127.0.0.1:6379`, flushed before the integration run.
- Services: `input(8001)`, `review(8000)`, `ingest(8002)`, `notification(8004)`, and `llm(8005)` all returned `/health=200`.
- Runtime mode:
  - `ENABLE_NOTIFICATIONS=true`
  - `NOTIFY_SINK_MODE=jsonl`
  - `NOTIFICATION_SERVICE_ENABLE_WORKER=false`
  - `INGEST_SERVICE_ENABLE_WORKER=true`
  - `REVIEW_SERVICE_ENABLE_APPLY_WORKER=true`
  - `LLM_SERVICE_ENABLE_WORKER=true`
  - `GMAIL_API_BASE_URL=http://127.0.0.1:8765/gmail/v1/users/me`

## Commands Executed
- Offline guard and regression suite: 14 related test files, result `30 passed`.
- Main integration run:
  - `python scripts/smoke_semester_demo.py --input-api-base http://127.0.0.1:8001 --review-api-base http://127.0.0.1:8000 --ingest-api-base http://127.0.0.1:8002 --notify-api-base http://127.0.0.1:8004 --llm-api-base http://127.0.0.1:8005 --api-key "$APP_API_KEY" --ops-token "$INTERNAL_SERVICE_TOKEN_OPS" --notification-jsonl data/smoke/notify_sink.jsonl --report data/synthetic/semester_demo/qa/semester_demo_report.json`
- Quality gates:
  - `mypy .`
  - `flake8 .`
  - `python -m build`

## Result Summary
- Offline guards: passed.
- Main integration run: passed.
- Quality gates: passed.
- Final verdict: `PASS`.

## Acceptance Checks
- Structured report: `semester_demo_report.json` has `passed=true`.
- `fatal_errors=[]`
- `failed_assertions=0`
- Per-semester volume:
  - Semester 1: `ICS=100`, `Gmail=100`
  - Semester 2: `ICS=100`, `Gmail=100`
  - Semester 3: `ICS=100`, `Gmail=100`
- Notification path:
  - `notification_flush.batches_flushed=30`
  - `notification_flush.enqueued_notifications=30`
  - `notification_flush.processed_slots=2`
  - `notification_flush.sent_count=1`
  - `notification_flush.failed_count=0`
- JSONL sink:
  - `rows_delta=1`

## Edge Case Analysis
- Covered and validated during the integration run:
  - missing suffix: `suffix_required_missing`
  - suffix mismatch: `suffix_mismatch`
  - exact suffix match: `auto_link`
  - alias / casing / separator variants for the same course
  - Gmail baseline round 0
  - `label_id=INBOX` filtering path
  - explicit notification flush path
  - JSONL sink propagation of `run_id/semester/batch`
  - fake inbox preservation of `thread_id/from_header/label_ids/internalDate`
- Scale decision: the current baseline already covers the target edge cases; scaling to `3x15x15` is not required at this stage.

## LLM Behavior Analysis
- Real LLM calls were successfully executed and participated in the main integration run.
- Service logs show repeated successful `200` responses for:
  - `calendar_event_enrichment`
  - `gmail_message_extract`
- No evidence of:
  - rate limiting
  - retry scheduling
  - notification failure
- Conclusion: the LLM call chain is now connected and stable for the current baseline workload.

## Issues Fixed Before Final Pass
The following blockers were fixed before the successful run:
- `xautoclaim` return-shape compatibility
- `LLM_ENQUEUE_PENDING` being incorrectly gated by `next_retry_at`
- indentation bug in the Gmail branch of `parse_pipeline`
- legacy `uid` leaking from calendar delta records
- incorrect ack behavior in `MessagePreflight` under DB/queue race conditions
- `APP_LLM_OPENAI_MODEL` fallback for `INGESTION_LLM_MODEL`
- live smoke pytest environment pollution from `tests/conftest.py`
- incorrect review decision response comparison (`approve` vs `approved`)

## Risks and Recommendations
- The main integration run is now a valid backend closure baseline.
- The online pytest wrapper still re-runs a full smoke and therefore remains expensive; consider adding a faster mode or smaller default scale later.
- Only consider scaling to `3x15x15` after a dedicated higher-confidence stress round is actually needed.

## Final Verdict
- Verdict: `PASS`
- This run validates that the backend loop of fake ICS/fake Gmail inbox + real LLM + review + notify now works end to end.
